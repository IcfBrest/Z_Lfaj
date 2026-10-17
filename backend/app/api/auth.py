from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import InvitationCode, User, utcnow
from ..security import create_jwt, hash_password, verify_password
from .deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    email: str | None = None
    invitation_code: str | None = Field(default=None, min_length=4, max_length=32)


class LoginIn(BaseModel):
    username: str
    password: str


def _issue(user: User) -> dict:
    return {"token": create_jwt(user.id, user.is_admin), "is_admin": user.is_admin, "username": user.username}


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> dict:
    # 引导规则：平台尚无任何用户时，首个注册者免邀请码并成为管理员
    first_user = db.query(User.id).first() is None

    # 所有用户输入都经 SQLAlchemy filter_by 绑定参数查询，无字符串拼接
    code = None
    if not first_user:
        if not body.invitation_code:
            raise HTTPException(400, "注册需要邀请码，请向管理员索取")
        code = db.query(InvitationCode).filter_by(code=body.invitation_code).one_or_none()
        if code is None or code.is_revoked or code.used_by is not None:
            raise HTTPException(400, "邀请码无效、已使用或已作废")

    if db.query(User.id).filter_by(username=body.username).first() is not None:
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        is_admin=first_user,
        invited_by_code=code.code if code else None,
    )
    db.add(user)
    db.flush()
    if code is not None:
        code.used_by = user.id
        code.used_at = utcnow()
    db.commit()
    return _issue(user)


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter_by(username=body.username).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    if user.is_disabled:
        raise HTTPException(403, "账号已被禁用")
    return _issue(user)


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "username": user.username, "email": user.email, "is_admin": user.is_admin}
