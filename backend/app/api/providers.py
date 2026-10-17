import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import llm_gateway
from ..db import get_db
from ..models import User, UserProvider
from ..security import decrypt_text, encrypt_text, mask_secret
from .deps import get_current_user

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str = Field(min_length=8, max_length=512)
    default_model: str | None = None
    task_models: dict[str, str] = {}
    enabled: bool = True


class ProviderUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    api_key: str | None = None  # None 或含掩码标记 → 保留旧 key
    default_model: str | None = None
    task_models: dict[str, str] = {}
    enabled: bool = True


class ProviderOut(BaseModel):
    id: int
    name: str
    base_url: str
    api_key_masked: str
    default_model: str | None
    task_models: dict
    enabled: bool


def _out(p: UserProvider) -> dict:
    try:
        masked = mask_secret(decrypt_text(p.api_key_encrypted))
    except RuntimeError:
        masked = "***"
    return {
        "id": p.id,
        "name": p.name,
        "base_url": p.base_url,
        "api_key_masked": masked,
        "default_model": p.default_model,
        "task_models": p.task_models or {},
        "enabled": p.enabled,
    }


def _own(db: Session, user: User, provider_id: int) -> UserProvider:
    p = db.query(UserProvider).filter_by(id=provider_id, user_id=user.id).one_or_none()
    if p is None:
        raise HTTPException(404, "provider 不存在")
    return p


@router.get("")
def list_providers(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    return [_out(p) for p in db.query(UserProvider).filter_by(user_id=user.id).all()]


@router.post("", status_code=201)
def create_provider(body: ProviderIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    p = UserProvider(
        user_id=user.id,
        name=body.name,
        base_url=body.base_url,
        api_key_encrypted=encrypt_text(body.api_key),
        default_model=body.default_model,
        task_models=body.task_models,
        enabled=body.enabled,
    )
    db.add(p)
    db.commit()
    return _out(p)


@router.put("/{provider_id}")
def update_provider(
    provider_id: int,
    body: ProviderUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    p = _own(db, user, provider_id)
    p.name = body.name
    p.base_url = body.base_url
    p.default_model = body.default_model
    p.task_models = body.task_models
    p.enabled = body.enabled
    if body.api_key and "***" not in body.api_key:
        p.api_key_encrypted = encrypt_text(body.api_key)
    db.commit()
    return _out(p)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    p = _own(db, user, provider_id)
    db.delete(p)
    db.commit()


@router.post("/{provider_id}/test")
def test_provider(provider_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    p = _own(db, user, provider_id)
    model = (p.task_models or {}).get("parse") or p.default_model or "deepseek-chat"
    started = time.monotonic()
    try:
        raw = llm_gateway._invoke(p, model, [{"role": "user", "content": "回复一个字：好"}])
        llm_gateway._record(
            db, user.id, "connectivity", p, model, raw,
            int((time.monotonic() - started) * 1000), "ok", None,
        )
        return {
            "ok": True,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model_reply": raw["content"][:50],
        }
    except Exception as exc:
        llm_gateway._record(
            db, user.id, "connectivity", p, model, {},
            int((time.monotonic() - started) * 1000), "error", str(exc)[:500],
        )
        return {"ok": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": str(exc)[:300]}
