import hashlib

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ..db import get_db
from ..models import Company, JobPosting, MatchResult, User, UserManualJob, utcnow
from ..parsers import parse_jd
from ..task_runner import enqueue, run_with_status
from .deps import get_current_user

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class ManualJobIn(BaseModel):
    jd_text: str = Field(min_length=20, max_length=20000)
    company_id: int | None = None       # admin：入库到共享库时的归属公司
    company_name: str | None = None     # 普通用户：私有岗位的公司名
    source_url: str | None = None


def _content_hash(jd_text: str) -> str:
    return hashlib.sha256(jd_text.encode()).hexdigest()


def run_job_parse(task_id: str, SessionLocal_: sessionmaker) -> None:
    def work(db: Session) -> None:
        from ..models import BackgroundTask

        task = db.get(BackgroundTask, task_id)
        if task is None or task.ref_type is None or task.ref_id is None:
            raise RuntimeError("任务引用缺失")

        if task.ref_type == "job_posting":
            job = db.get(JobPosting, task.ref_id)
            text = job.description_raw if job else ""
        else:
            job = db.get(UserManualJob, task.ref_id)
            text = job.description_raw if job else ""
        if not text:
            raise RuntimeError("岗位原文为空")

        parsed = parse_jd(db, task.user_id, text)
        if job is None:
            raise RuntimeError("岗位记录不存在")

        for field in (
            "title", "department", "location", "employment_type", "salary_range",
            "experience_required", "education_required",
        ):
            setattr(job, field, parsed.get(field))
        for field in ("skills", "responsibilities", "requirements", "nice_to_have"):
            setattr(job, field, parsed.get(field) or [])
        db.commit()

    run_with_status(task_id, SessionLocal_, work)


@router.post("/manual", status_code=202)
def create_manual_job(
    body: ManualJobIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """粘贴 JD：admin 且指定 company_id → 共享库；否则 → 本人私有库。"""
    content_hash = _content_hash(body.jd_text)

    if user.is_admin and body.company_id is not None:
        company = db.get(Company, body.company_id)
        if company is None:
            raise HTTPException(400, "公司不存在，请先创建公司")
        job = JobPosting(
            company_id=company.id,
            title="(待解析)",
            description_raw=body.jd_text,
            source_url=body.source_url,
            source_type="manual",
            content_hash=content_hash,
        )
        db.add(job)
        db.flush()
        ref_type, ref_id = "job_posting", job.id
    else:
        job = UserManualJob(
            user_id=user.id,
            company_name=body.company_name,
            title="(待解析)",
            description_raw=body.jd_text,
            source_url=body.source_url,
            source_type="manual",
            content_hash=content_hash,
        )
        db.add(job)
        db.flush()
        ref_type, ref_id = "user_manual_job", job.id
    db.commit()

    task_id = enqueue(background_tasks, db, "job_parse", user.id, run_job_parse, ref_type, ref_id)
    return {"task_id": task_id, "job_ref_type": ref_type, "job_ref_id": ref_id}


def _job_dict(job: JobPosting, company_name: str | None = None) -> dict:
    return {
        "id": job.id,
        "company": company_name,
        "title": job.title,
        "department": job.department,
        "location": job.location,
        "employment_type": job.employment_type,
        "salary_range": job.salary_range,
        "experience_required": job.experience_required,
        "education_required": job.education_required,
        "skills": job.skills or [],
        "responsibilities": job.responsibilities or [],
        "requirements": job.requirements or [],
        "nice_to_have": job.nice_to_have or [],
        "source_url": job.source_url,
        "source_type": job.source_type,
        "is_active": job.is_active,
        "scraped_at": (
            job.scraped_at.isoformat() if getattr(job, "scraped_at", None) else None
        ),
    }


def _match_map(db: Session, user: User, ref_type: str, ids: list[int]) -> dict[int, dict]:
    """当前用户在这些岗位上的最新一条打分（没有则不计入结果）。"""
    if not ids:
        return {}
    rows = (
        db.query(MatchResult)
        .filter(
            MatchResult.user_id == user.id,
            MatchResult.job_ref_type == ref_type,
            MatchResult.job_ref_id.in_(ids),
        )
        .order_by(MatchResult.id.desc())
        .all()
    )
    latest: dict[int, dict] = {}
    for row in rows:
        latest.setdefault(row.job_ref_id, {"match_id": row.id, "match_score": row.score})
    return latest


def _decorate(items: list[dict], scores: dict[int, dict], sort: str | None) -> list[dict]:
    for item in items:
        item.update(scores.get(item["id"], {"match_id": None, "match_score": None}))
    if sort == "score":
        # 已打分的按分数降序在前，未打分的保持原顺序在后
        items.sort(key=lambda item: (item["match_score"] is None, -(item["match_score"] or 0)))
    return items


@router.get("/shared")
def list_shared_jobs(
    company_id: int | None = None,
    sort: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    query = db.query(JobPosting, Company.name).join(Company, JobPosting.company_id == Company.id)
    if company_id is not None:
        query = query.filter(JobPosting.company_id == company_id)
    query = query.filter(JobPosting.is_active.is_(True))
    items = [_job_dict(job, name) for job, name in query.order_by(JobPosting.id.desc()).limit(500).all()]
    scores = _match_map(db, user, "job_posting", [item["id"] for item in items])
    return _decorate(items, scores, sort)


@router.get("/shared/{job_id}")
def get_shared_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    row = (
        db.query(JobPosting, Company.name)
        .join(Company, JobPosting.company_id == Company.id)
        .filter(JobPosting.id == job_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "岗位不存在")
    job, name = row
    out = _job_dict(job, name)
    out["description_raw"] = job.description_raw
    return out


@router.get("/mine")
def list_my_jobs(
    sort: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    jobs = (
        db.query(UserManualJob)
        .filter_by(user_id=user.id)
        .order_by(UserManualJob.id.desc())
        .limit(500)
        .all()
    )
    out = []
    for job in jobs:
        d = _job_dict(job, job.company_name)
        d.pop("scraped_at", None)
        out.append(d)
    scores = _match_map(db, user, "user_manual_job", [item["id"] for item in out])
    return _decorate(out, scores, sort)


@router.get("/mine/{job_id}")
def get_my_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    job = db.query(UserManualJob).filter_by(id=job_id, user_id=user.id).one_or_none()
    if job is None:
        raise HTTPException(404, "岗位不存在")
    out = _job_dict(job, job.company_name)
    out["description_raw"] = job.description_raw
    return out
