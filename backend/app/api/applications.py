"""Phase 5：投递记录与面试跟踪接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import applications as core
from ..db import get_db
from ..models import User
from .deps import get_current_user

router = APIRouter(prefix="/api/applications", tags=["applications"])


class CreateIn(BaseModel):
    job_ref_type: str = Field(description="job_posting 或 user_manual_job")
    job_ref_id: int
    resume_id: int | None = None
    note: str | None = None


class PatchIn(BaseModel):
    status: str | None = None
    note: str | None = None


@router.post("", status_code=201)
def create_application(
    payload: CreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        application = core.create_application(
            db,
            user,
            job_ref_type=payload.job_ref_type,
            job_ref_id=payload.job_ref_id,
            resume_id=payload.resume_id,
            note=payload.note,
        )
    except core.DuplicateApplication as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "application_id": exc.application_id},
        ) from exc
    except core.ApplicationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return core.serialize(application)


@router.get("")
def list_applications(
    status: str | None = Query(default=None),
    sort: str = Query(default="recent", pattern="^(recent|stale)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if status is not None and status not in core.STATUSES:
        raise HTTPException(status_code=400, detail=f"未知状态：{status}")
    rows = core.list_applications(db, user.id, status=status, sort=sort, limit=limit)
    return [core.serialize(row) for row in rows]


@router.get("/stats")
def application_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return core.stats(db, user.id)


@router.get("/{application_id}")
def get_application(
    application_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        application = core.get_owned(db, user.id, application_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = core.serialize(application)
    payload["events"] = [core.serialize_event(event) for event in application.events]
    payload["status_options"] = list(core.STATUSES)
    return payload


@router.patch("/{application_id}")
def patch_application(
    application_id: int,
    payload: PatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        application = core.get_owned(db, user.id, application_id)
        if payload.status is not None:
            application = core.transition(db, application, payload.status, payload.note)
        elif payload.note is not None:
            application = core.update_note(db, application, payload.note)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except core.ApplicationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return core.serialize(application)
