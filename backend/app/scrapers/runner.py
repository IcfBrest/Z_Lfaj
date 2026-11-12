"""采集后台任务入口：由 API 入队，`app/api/tasks.py` 的重试也复用这里。"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from ..models import BackgroundTask
from ..task_runner import run_with_status
from .sources import get_source
from .sync import sync_jobs


def run_company_scrape(task_id: str, SessionLocal_: sessionmaker) -> None:
    def work(db: Session) -> None:
        task = db.get(BackgroundTask, task_id)
        if task is None:
            raise RuntimeError("任务引用缺失")
        params = dict(task.params or {})
        source = get_source(str(params.get("source") or ""))
        stats = sync_jobs(
            db,
            source,
            limit=params.get("limit"),
            fetch_detail=bool(params.get("fetch_detail", True)),
        )
        params["result"] = stats
        task.params = params
        db.commit()

    run_with_status(task_id, SessionLocal_, work)
