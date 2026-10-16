import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import InvitationCode, User, utcnow
from ..security import hash_password
from .deps import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@router.get("/users")
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> list[dict]:
    users = db.query(User).order_by(User.id).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_admin": u.is_admin,
            "is_disabled": u.is_disabled,
            "invited_by_code": u.invited_by_code,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.post("/users/{user_id}/disable", status_code=204)
def disable_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id:
        raise HTTPException(400, "不能禁用自己")
    user.is_disabled = True
    db.commit()


@router.post("/users/{user_id}/enable", status_code=204)
def enable_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    user.is_disabled = False
    db.commit()


@router.post("/users/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: int,
    body: ResetPasswordIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    user.password_hash = hash_password(body.new_password)
    db.commit()


@router.post("/invitations", status_code=201)
def create_invitation(db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    code = secrets.token_urlsafe(12)
    db.add(InvitationCode(code=code, created_by=admin.id))
    db.commit()
    return {"code": code}


@router.get("/invitations")
def list_invitations(db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> list[dict]:
    items = db.query(InvitationCode).order_by(InvitationCode.id.desc()).all()
    return [
        {
            "code": i.code,
            "is_revoked": i.is_revoked,
            "used_by": i.used_by,
            "used_at": i.used_at.isoformat() if i.used_at else None,
            "created_at": i.created_at.isoformat(),
        }
        for i in items
    ]


@router.post("/invitations/{code}/revoke", status_code=204)
def revoke_invitation(code: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> None:
    item = db.query(InvitationCode).filter_by(code=code).one_or_none()
    if item is None:
        raise HTTPException(404, "邀请码不存在")
    if item.used_by is not None:
        raise HTTPException(400, "邀请码已被使用，不能作废")
    item.is_revoked = True
    item.updated_at = utcnow() if hasattr(item, "updated_at") else None
    db.commit()
