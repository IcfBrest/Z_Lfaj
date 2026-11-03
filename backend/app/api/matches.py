"""人岗匹配打分 API：手动触发（全量/单岗）、结果列表与详情、四维权重。"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from .. import scoring
from ..db import get_db
from ..models import BackgroundTask, MatchResult, Resume, User
from ..task_runner import enqueue, run_with_status
from .deps import get_current_user

router = APIRouter(prefix="/api/matches", tags=["matches"])


class RunIn(BaseModel):
    resume_id: int | None = None
    limit: int = Field(default=scoring.DEFAULT_LIMIT, ge=1, le=100)
    force: bool = False


class JobScoreIn(BaseModel):
    resume_id: int | None = None
    force: bool = False


# ---------------------------------------------------------------- 后台任务


def run_match_run(task_id: str, SessionLocal_: sessionmaker) -> None:
    def work(db: Session) -> None:
        task = db.get(BackgroundTask, task_id)
        if task is None or task.user_id is None:
            raise RuntimeError("任务引用缺失")
        user = db.get(User, task.user_id)
        params = dict(task.params or {})
        resume = scoring.resolve_resume(db, user.id, params.get("resume_id"))
        summary = scoring.run_scoring(
            db,
            user,
            resume,
            limit=int(params.get("limit") or scoring.DEFAULT_LIMIT),
            force=bool(params.get("force")),
        )
        params["result"] = summary
        task.params = params
        db.commit()

    run_with_status(task_id, SessionLocal_, work)


def run_match_job(task_id: str, SessionLocal_: sessionmaker) -> None:
    def work(db: Session) -> None:
        task = db.get(BackgroundTask, task_id)
        if task is None or task.user_id is None or task.ref_type is None or task.ref_id is None:
            raise RuntimeError("任务引用缺失")
        user = db.get(User, task.user_id)
        params = dict(task.params or {})
        resume = scoring.resolve_resume(db, user.id, params.get("resume_id"))
        job = scoring.load_job(db, task.ref_type, task.ref_id, user_id=user.id)
        if job is None:
            raise RuntimeError("岗位不存在或已下架")
        row = scoring.score_one(db, user, resume, job, force=bool(params.get("force")))
        params["result"] = {"match_id": row.id, "score": row.score}
        task.params = params
        db.commit()

    run_with_status(task_id, SessionLocal_, work)


# ---------------------------------------------------------------- 触发打分


@router.post("/run", status_code=202)
def run_full_scoring(
    body: RunIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """全量打分：硬规则过滤 → 粗排取 limit → 逐个精排（缓存命中不重复调用）。"""
    try:
        resume = scoring.resolve_resume(db, user.id, body.resume_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not resume.parsed_profile_json:
        raise HTTPException(400, "简历尚未解析完成，无法打分")

    task_id = enqueue(
        background_tasks,
        db,
        "match_run",
        user.id,
        run_match_run,
        "resume",
        resume.id,
        {"resume_id": resume.id, "limit": body.limit, "force": body.force},
    )
    return {"task_id": task_id, "resume_id": resume.id, "limit": body.limit, "force": body.force}


@router.post("/jobs/{ref_type}/{job_id}", status_code=202)
def score_single_job(
    ref_type: str,
    job_id: int,
    body: JobScoreIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if ref_type not in scoring.JOB_REF_TYPES:
        raise HTTPException(400, f"不支持的岗位类型：{ref_type}")
    job = scoring.load_job(db, ref_type, job_id, user_id=user.id)
    if job is None:
        raise HTTPException(404, "岗位不存在或已下架")
    try:
        resume = scoring.resolve_resume(db, user.id, body.resume_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not resume.parsed_profile_json:
        raise HTTPException(400, "简历尚未解析完成，无法打分")

    task_id = enqueue(
        background_tasks,
        db,
        "match_job",
        user.id,
        run_match_job,
        ref_type,
        job_id,
        {"resume_id": resume.id, "force": body.force},
    )
    return {"task_id": task_id, "resume_id": resume.id, "job_ref_type": ref_type, "job_ref_id": job_id}


# ---------------------------------------------------------------- 结果读取


def _match_dict(db: Session, row: MatchResult, user_id: int) -> dict:
    payload = row.payload_json or {}
    job = scoring.load_job(db, row.job_ref_type, row.job_ref_id, user_id=user_id)
    return {
        "id": row.id,
        "resume_id": row.resume_id,
        "resume_version": row.resume_version,
        "job_ref_type": row.job_ref_type,
        "job_ref_id": row.job_ref_id,
        "title": job.title if job else None,
        "company": job.company if job else None,
        "location": job.location if job else None,
        "score": row.score,
        "verdict": payload.get("verdict"),
        "dimension_scores": payload.get("dimension_scores") or {},
        "missing_dimensions": payload.get("missing_dimensions") or [],
        "created_at": row.created_at.isoformat(),
    }


@router.get("")
def list_matches(
    resume_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    query = db.query(MatchResult).filter_by(user_id=user.id)
    if resume_id is not None:
        query = query.filter(MatchResult.resume_id == resume_id)
    rows = query.order_by(MatchResult.score.is_(None), MatchResult.score.desc(), MatchResult.id.desc()).limit(
        max(1, min(limit, 500))
    ).all()
    return [_match_dict(db, row, user.id) for row in rows]


@router.get("/weights/current")
def get_weights(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return {"weights": scoring.resolve_weights(user), "dimensions": list(scoring.DIMENSIONS)}


@router.put("/weights")
def put_weights(
    body: dict[str, float],
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """设置四维权重：必须给出全部四维，每维 0~100，总和 > 0。"""
    if set(body) != set(scoring.DIMENSIONS):
        raise HTTPException(400, "权重必须且只能包含四个维度：" + "、".join(scoring.DIMENSIONS))
    cleaned: dict[str, float] = {}
    for name in scoring.DIMENSIONS:
        try:
            value = float(body[name])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"维度「{name}」的权重必须是数字") from exc
        if value < 0 or value > 100:
            raise HTTPException(400, f"维度「{name}」的权重必须在 0~100 之间")
        cleaned[name] = value
    if sum(cleaned.values()) <= 0:
        raise HTTPException(400, "四维权重不能全为 0")

    user.score_weights = cleaned
    db.commit()
    return {"weights": cleaned}


@router.get("/{match_id}")
def get_match(match_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """详情：维度分 + 理由/匹配点/缺口 + 岗位摘要。他人结果一律 404。"""
    row = db.query(MatchResult).filter_by(id=match_id, user_id=user.id).one_or_none()
    if row is None:
        raise HTTPException(404, "匹配结果不存在")
    out = _match_dict(db, row, user.id)
    payload = row.payload_json or {}
    job = scoring.load_job(db, row.job_ref_type, row.job_ref_id, user_id=user.id)
    out.update(
        {
            "reasons": payload.get("reasons"),
            "matching_points": payload.get("matching_points") or [],
            "gaps": payload.get("gaps") or [],
            "score_basis": payload.get("score_basis"),
            "weights": payload.get("weights"),
            "job_snapshot": payload.get("job_snapshot") or {},
            "description_excerpt": (job.description_raw[:1200] if job else None),
        }
    )
    return out
