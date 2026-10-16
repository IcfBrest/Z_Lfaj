from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import LlmCall, User
from .deps import get_current_user

router = APIRouter(prefix="/api/costs", tags=["costs"])


@router.get("/summary")
def my_costs(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = (
        db.query(
            LlmCall.task_type,
            LlmCall.model,
            func.count(LlmCall.id),
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.duration_ms), 0),
        )
        .filter(LlmCall.user_id == user.id)
        .group_by(LlmCall.task_type, LlmCall.model)
        .all()
    )
    return [
        {
            "task_type": r[0],
            "model": r[1],
            "calls": r[2],
            "input_tokens": r[3],
            "output_tokens": r[4],
            "duration_ms": r[5],
        }
        for r in rows
    ]
