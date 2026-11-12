from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BackgroundTask, User, utcnow
from ..scrapers.runner import run_company_scrape
from .deps import get_current_user
from .jobs import run_job_parse
from .matches import run_match_job, run_match_run
from .resumes import run_resume_parse
from .suggestions import run_suggestion_generate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    task = db.get(BackgroundTask, task_id)
    if task is None or (task.user_id != user.id and not user.is_admin):
        raise HTTPException(404, "任务不存在")
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "ref_type": task.ref_type,
        "ref_id": task.ref_id,
        "error": task.error,
        "result": (task.params or {}).get("result"),
        "created_at": task.created_at.isoformat(),
    }


@router.post("/{task_id}/retry", status_code=202)
def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    task = db.get(BackgroundTask, task_id)
    if task is None or (task.user_id != user.id and not user.is_admin):
        raise HTTPException(404, "任务不存在")
    if task.status not in ("failed",):
        raise HTTPException(400, "只有失败的任务可以重试")

    runner = {
        "job_parse": run_job_parse,
        "resume_parse": run_resume_parse,
        "match_run": run_match_run,
        "match_job": run_match_job,
        "suggestion_generate": run_suggestion_generate,
        "company_scrape": run_company_scrape,
    }.get(task.kind)
    if runner is None:
        raise HTTPException(400, f"不支持重试的任务类型：{task.kind}")

    task.status = "pending"
    task.error = None
    task.updated_at = utcnow()
    db.commit()

    from .. import task_runner

    background_tasks.add_task(runner, task.id, task_runner.SessionLocal)
    return {"task_id": task.id, "status": "pending"}
