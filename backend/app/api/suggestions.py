"""简历修改建议 API（Phase 2）：按匹配结果手动生成、读取列表与详情。"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from .. import suggestions
from ..db import get_db
from ..models import BackgroundTask, Suggestion, User
from ..task_runner import enqueue, run_with_status
from .deps import get_current_user

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


class GenerateIn(BaseModel):
    match_id: int
    force: bool = False


# ---------------------------------------------------------------- 后台任务


def run_suggestion_generate(task_id: str, SessionLocal_: sessionmaker) -> None:
    def work(db: Session) -> None:
        task = db.get(BackgroundTask, task_id)
        if task is None or task.user_id is None:
            raise RuntimeError("任务引用缺失")
        user = db.get(User, task.user_id)
        params = dict(task.params or {})
        match = suggestions.load_match(db, user.id, int(params["match_id"]))
        row = suggestions.generate(db, user, match, force=bool(params.get("force")))
        payload = row.payload_json or {}
        params["result"] = {
            "suggestion_id": row.id,
            "match_id": row.match_result_id,
            "count": len(payload.get("suggestions") or []),
            "missing_keywords": len(payload.get("missing_keywords") or []),
            "honesty_warnings": len(payload.get("honesty_warnings") or []),
        }
        task.params = params
        db.commit()

    run_with_status(task_id, SessionLocal_, work)


# ---------------------------------------------------------------- 生成与读取


@router.post("", status_code=202)
def create_suggestion(
    body: GenerateIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """针对一条匹配结果生成简历修改建议（后台任务，前端轮询）。"""
    try:
        match = suggestions.load_match(db, user.id, body.match_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not match.payload_json:
        raise HTTPException(400, "该匹配结果没有可用的打分结论，请重新打分")

    task_id = enqueue(
        background_tasks,
        db,
        "suggestion_generate",
        user.id,
        run_suggestion_generate,
        "match_result",
        match.id,
        {"match_id": match.id, "force": body.force},
    )
    return {"task_id": task_id, "match_id": match.id, "force": body.force}


@router.get("")
def list_suggestions(
    match_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    query = db.query(Suggestion).filter_by(user_id=user.id)
    if match_id is not None:
        query = query.filter(Suggestion.match_result_id == match_id)
    rows = query.order_by(Suggestion.id.desc()).limit(max(1, min(limit, 200))).all()
    return [suggestions.suggestion_dict(row) for row in rows]


@router.get("/{suggestion_id}")
def get_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """建议详情：逐条建议、缺失关键词、防编造警告。他人的建议一律 404。"""
    row = db.query(Suggestion).filter_by(id=suggestion_id, user_id=user.id).one_or_none()
    if row is None:
        raise HTTPException(404, "建议不存在")
    return suggestions.suggestion_dict(row)
