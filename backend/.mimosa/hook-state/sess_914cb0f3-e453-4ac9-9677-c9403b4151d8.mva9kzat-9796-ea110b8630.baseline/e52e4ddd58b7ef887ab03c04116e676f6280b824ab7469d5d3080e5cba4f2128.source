"""测试基座：独立 SQLite、加密密钥、依赖覆盖、常用夹具。

所有 LLM 调用通过 monkeypatch app.llm_gateway._invoke 打桩，测试零网络零成本。
"""

import os

os.environ.setdefault("SECRET_KEY", "unit-test-secret")
os.environ.setdefault("ENCRYPTION_KEY", "unit-test-encryption-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/unit-test.db")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.task_runner as task_runner
from app.config import get_settings
from app.db import Base, get_db
from app.main import create_app
from app.models import InvitationCode, User
from app.security import hash_password

get_settings.cache_clear()

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # 内存库单连接共享，多 session 可见
)
TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    session = TestSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db, monkeypatch):
    # 后台任务运行器也指向测试库
    monkeypatch.setattr(task_runner, "SessionLocal", TestSessionLocal)

    app = create_app()

    def override_get_db():
        session = TestSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_user(db):
    user = User(username="admin", password_hash=hash_password("admin-pass-123"), is_admin=True)
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def normal_user(db):
    user = User(username="alice", password_hash=hash_password("alice-pass-1234"), is_admin=False)
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def other_user(db):
    user = User(username="bob", password_hash=hash_password("bob-pass-12345"), is_admin=False)
    db.add(user)
    db.commit()
    return user


def make_invitation(db, created_by=1, **kwargs) -> InvitationCode:
    code = InvitationCode(code=kwargs.pop("code", "invite-code-1"), created_by=created_by, **kwargs)
    db.add(code)
    db.commit()
    return code


def auth_header(client, username: str, password: str) -> dict:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return auth_header(client, "admin", "admin-pass-123")


@pytest.fixture()
def user_headers(client, normal_user):
    return auth_header(client, "alice", "alice-pass-1234")


@pytest.fixture()
def other_headers(client, other_user):
    return auth_header(client, "bob", "bob-pass-12345")
