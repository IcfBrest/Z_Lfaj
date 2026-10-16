"""应用内后台任务：登记 BackgroundTask 状态，用 FastAPI BackgroundTasks 执行。

Phase 1 引入 arq/Redis 后，此模块的 run_* 函数签名保持不变，只换执行载体。
"""

import uuid
from typing import Callable

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session, sessionmaker

from .db import SessionLocal
from .models import BackgroundTask, utcnow


def enqueue(
    background_tasks: BackgroundTasks,
    db: Session,
    kind: str,
    user_id: int | None,
    runner: Callable[[str, sessionmaker], None],
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> str:
    task_id = str(uuid.uuid4())
    db.add(
        BackgroundTask(
            id=task_id, kind=kind, status="pending", user_id=user_id, ref_type=ref_type, ref_id=ref_id
        )
    )
    db.commit()
    background_tasks.add_task(runner, task_id, SessionLocal)
    return task_id


def mark(task_id: str, SessionLocal_: sessionmaker, status: str, error: str | None = None) -> None:
    db = SessionLocal_()
    try:
        task = db.get(BackgroundTask, task_id)
        if task is None:
            return
        task.status = status
        task.error = error
        task.updated_at = utcnow()
        db.commit()
    finally:
        db.close()


def run_with_status(task_id: str, SessionLocal_: sessionmaker, work: Callable[[Session], None]) -> None:
    """包装器：running → work(db) → done；异常落 failed 并保留错误信息。"""
    mark(task_id, SessionLocal_, "running")
    db = SessionLocal_()
    try:
        work(db)
        mark(task_id, SessionLocal_, "done")
    except Exception as exc:  # 后台任务必须吞掉异常转为状态
        mark(task_id, SessionLocal_, "failed", str(exc)[:1000])
    finally:
        db.close()
