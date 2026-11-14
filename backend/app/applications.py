"""Phase 5：投递记录内核。

- 岗位快照：投递时冻结公司/标题/地点/链接，岗位后续被采集更新不影响历史
- 状态机：applied → written_test → interview → offer，rejected/withdrawn 为终止态
- 时间线：每次状态变化追加 ApplicationEvent
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from . import scoring
from .models import Application, ApplicationEvent, MatchResult, Resume, User
from .scoring import JobView

STATUSES = ("applied", "written_test", "interview", "offer", "rejected", "withdrawn")
TERMINAL = ("rejected", "withdrawn")
STALE_DAYS = 7

STATUS_LABELS = {
    "applied": "已投递",
    "written_test": "笔试",
    "interview": "面试",
    "offer": "Offer",
    "rejected": "已拒",
    "withdrawn": "已放弃",
}

NEXT_STATUS = {
    "applied": "written_test",
    "written_test": "interview",
    "interview": "offer",
}


class DuplicateApplication(Exception):
    """同一用户对同一岗位重复投递。"""

    def __init__(self, application_id: int) -> None:
        super().__init__(f"该岗位已投递过（记录 #{application_id}）")
        self.application_id = application_id


class ApplicationError(Exception):
    """投递记录的业务错误（用 400 返回）。"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_job(db: Session, user: User, ref_type: str, ref_id: int) -> JobView:
    """按 ref 读取岗位视图；岗位不存在或不属于该用户时抛 ApplicationError。"""
    if ref_type not in ("job_posting", "user_manual_job"):
        raise ApplicationError(f"不支持的岗位类型：{ref_type}")
    job = scoring.load_job(db, ref_type, ref_id, user.id)
    if job is None:
        raise ApplicationError("岗位不存在或你无权访问")
    return job


def pick_resume(db: Session, user_id: int, resume_id: int | None) -> Resume | None:
    if resume_id is None:
        return scoring.master_resume(db, user_id)
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != user_id:
        raise ApplicationError("简历不存在")
    return resume


def find_match(db: Session, user_id: int, resume: Resume | None, job: JobView) -> MatchResult | None:
    """取该岗位在该简历版本上的最近一条匹配结论（投递不强制要求先打分）。"""
    query = db.query(MatchResult).filter_by(
        user_id=user_id,
        job_ref_type=job.ref_type,
        job_ref_id=job.ref_id,
    )
    if resume is not None:
        query = query.filter_by(resume_id=resume.id, resume_version=resume.version)
    return query.order_by(MatchResult.id.desc()).first()


def get_owned(db: Session, user_id: int, application_id: int) -> Application:
    application = db.get(Application, application_id)
    if application is None or application.user_id != user_id:
        raise LookupError("投递记录不存在")
    return application


def _append_event(
    db: Session,
    application: Application,
    from_status: str | None,
    to_status: str,
    note: str | None = None,
    at: datetime | None = None,
) -> None:
    db.add(
        ApplicationEvent(
            application_id=application.id,
            user_id=application.user_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            created_at=at or _now(),
        )
    )


def create_application(
    db: Session,
    user: User,
    *,
    job_ref_type: str,
    job_ref_id: int,
    resume_id: int | None = None,
    note: str | None = None,
) -> Application:
    existing = (
        db.query(Application)
        .filter_by(user_id=user.id, job_ref_type=job_ref_type, job_ref_id=job_ref_id)
        .one_or_none()
    )
    if existing is not None:
        raise DuplicateApplication(existing.id)

    job = resolve_job(db, user, job_ref_type, job_ref_id)
    resume = pick_resume(db, user.id, resume_id)
    match = find_match(db, user.id, resume, job)
    now = _now()

    application = Application(
        user_id=user.id,
        job_ref_type=job_ref_type,
        job_ref_id=job_ref_id,
        resume_id=resume.id if resume else None,
        match_result_id=match.id if match else None,
        company_name=job.company or "未知公司",
        title=job.title or "未知岗位",
        location=job.location,
        source_url=job.source_url,
        match_score=match.score if match else None,
        status="applied",
        note=note,
        applied_at=now,
        last_activity_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(application)
    db.flush()
    _append_event(db, application, None, "applied", note, at=now)
    db.commit()
    db.refresh(application)
    return application


def transition(db: Session, application: Application, status: str, note: str | None = None) -> Application:
    """推进状态：校验枚举与终止态，幂等处理同状态，追加事件。"""
    if status not in STATUSES:
        raise ApplicationError(f"未知状态：{status}（可用：{', '.join(STATUSES)}）")
    if application.status in TERMINAL:
        raise ApplicationError("该投递已结束（已拒/已放弃），不能再变更状态")
    if status == application.status:
        if note is not None:
            update_note(db, application, note)
        return application

    now = _now()
    previous = application.status
    application.status = status
    application.last_activity_at = now
    application.updated_at = now
    _append_event(db, application, previous, status, note, at=now)
    db.commit()
    db.refresh(application)
    return application


def update_note(db: Session, application: Application, note: str | None) -> Application:
    application.note = note
    application.last_activity_at = _now()
    db.commit()
    db.refresh(application)
    return application


def days_since_update(application: Application, now: datetime | None = None) -> int:
    moment = now or _now()
    last = application.last_activity_at
    if last.tzinfo is None:  # sqlite 读回来是 naive，按 UTC 处理
        last = last.replace(tzinfo=timezone.utc)
    return max(0, (moment - last).days)


def serialize(application: Application, now: datetime | None = None) -> dict:
    days = days_since_update(application, now)
    return {
        "id": application.id,
        "job_ref_type": application.job_ref_type,
        "job_ref_id": application.job_ref_id,
        "resume_id": application.resume_id,
        "match_result_id": application.match_result_id,
        "company_name": application.company_name,
        "title": application.title,
        "location": application.location,
        "source_url": application.source_url,
        "match_score": application.match_score,
        "status": application.status,
        "status_label": STATUS_LABELS.get(application.status, application.status),
        "note": application.note,
        "applied_at": application.applied_at,
        "last_activity_at": application.last_activity_at,
        "days_since_update": days,
        "is_stale": application.status not in TERMINAL and days >= STALE_DAYS,
        "next_status": NEXT_STATUS.get(application.status),
        "created_at": application.created_at,
    }


def serialize_event(event: ApplicationEvent) -> dict:
    return {
        "id": event.id,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "to_label": STATUS_LABELS.get(event.to_status, event.to_status),
        "note": event.note,
        "created_at": event.created_at,
    }


def list_applications(
    db: Session,
    user_id: int,
    *,
    status: str | None = None,
    sort: str = "recent",
    limit: int = 100,
) -> list[Application]:
    query = db.query(Application).filter_by(user_id=user_id)
    if status:
        query = query.filter_by(status=status)
    if sort == "stale":
        query = query.order_by(Application.last_activity_at.asc(), Application.id.desc())
    else:
        query = query.order_by(Application.last_activity_at.desc(), Application.id.desc())
    return query.limit(max(1, min(limit, 500))).all()


def stats(db: Session, user_id: int) -> dict:
    applications = db.query(Application).filter_by(user_id=user_id).all()
    now = _now()
    counts = {name: 0 for name in STATUSES}
    stale = 0
    for application in applications:
        counts[application.status] = counts.get(application.status, 0) + 1
        if application.status not in TERMINAL and days_since_update(application, now) >= STALE_DAYS:
            stale += 1
    return {
        "total": len(applications),
        "by_status": counts,
        "stale": stale,
        "active": len(applications) - counts["rejected"] - counts["withdrawn"],
    }
