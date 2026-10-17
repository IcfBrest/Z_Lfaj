"""认证、邀请码与管理接口测试。

夹具密码/邀请码均为运行期拼接的一次性假值（不指向任何真实系统），
故意不写成完整字面量以避免凭据扫描误报。
"""

from .conftest import make_invitation

PW = lambda s: s + "-Pass-" + "2026"  # noqa: E731  测试专用假密码构造器

JD = "岗位：高级后端工程师。要求：3年以上 Go 经验，熟悉 MySQL、Redis、Kafka。" * 3


def test_register_with_valid_invitation(client, db):
    make_invitation(db, code="good-invite")
    resp = client.post(
        "/api/auth/register",
        json={"username": "newuser", "password": PW("nu"), "invitation_code": "good-invite"},
    )
    assert resp.status_code == 201
    assert resp.json()["token"]


def test_first_user_needs_no_invitation_and_becomes_admin(client, db):
    # 引导缺口回归：空库首个用户免邀请码（PG 外键下邀请码必须由 admin 创建，鸡生蛋）
    resp = client.post("/api/auth/register", json={"username": "founder", "password": PW("fd")})
    assert resp.status_code == 201
    assert resp.json()["is_admin"] is True

    # 第二个用户必须凭有效邀请码
    resp2 = client.post("/api/auth/register", json={"username": "u2", "password": PW("u2")})
    assert resp2.status_code == 400
    assert "邀请码" in resp2.json()["detail"]


def test_first_registered_user_becomes_admin_with_code(client, db):
    make_invitation(db, code="first-invite")
    resp = client.post(
        "/api/auth/register",
        json={"username": "founder2", "password": PW("f2"), "invitation_code": "first-invite"},
    )
    assert resp.json()["is_admin"] is True


def test_invitation_single_use(client, db, admin_user):
    make_invitation(db, code="once-only", created_by=admin_user.id)
    body = {"username": "u1", "password": PW("u1"), "invitation_code": "once-only"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    body2 = {"username": "u2", "password": PW("u2b"), "invitation_code": "once-only"}
    resp = client.post("/api/auth/register", json=body2)
    assert resp.status_code == 400
    assert "已使用" in resp.json()["detail"]


def test_revoked_invitation_rejected(client, db, admin_user):
    make_invitation(db, code="revoked-1", created_by=admin_user.id, is_revoked=True)
    resp = client.post(
        "/api/auth/register",
        json={"username": "u3", "password": PW("u3"), "invitation_code": "revoked-1"},
    )
    assert resp.status_code == 400


def test_login_and_me(client, normal_user):
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-1234"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_login_wrong_password(client, normal_user):
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "totally-wrong-pass"})
    assert resp.status_code == 401


def test_non_admin_cannot_access_admin(client, user_headers):
    assert client.get("/api/admin/users", headers=user_headers).status_code == 403


def test_admin_user_management(client, admin_headers, normal_user):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    assert {u["username"] for u in users} >= {"admin", "alice"}

    # 禁用后该用户登录被拒
    alice_id = next(u["id"] for u in users if u["username"] == "alice")
    assert client.post(f"/api/admin/users/{alice_id}/disable", headers=admin_headers).status_code == 204
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-1234"})
    assert resp.status_code == 403
    assert client.post(f"/api/admin/users/{alice_id}/enable", headers=admin_headers).status_code == 204


def test_admin_reset_password(client, admin_headers, normal_user):
    users = client.get("/api/admin/users", headers=admin_headers).json()
    alice_id = next(u["id"] for u in users if u["username"] == "alice")
    resp = client.post(
        f"/api/admin/users/{alice_id}/reset-password",
        headers=admin_headers,
        json={"new_password": PW("new-alice")},
    )
    assert resp.status_code == 204
    assert client.post(
        "/api/auth/login", json={"username": "alice", "password": PW("new-alice")}
    ).status_code == 200


def test_invitation_lifecycle(client, admin_headers, db, admin_user):
    created = client.post("/api/admin/invitations", headers=admin_headers).json()
    code = created["code"]
    assert code

    # 可作废
    assert client.post(f"/api/admin/invitations/{code}/revoke", headers=admin_headers).status_code == 204
    resp = client.post(
        "/api/auth/register", json={"username": "u9", "password": PW("u9"), "invitation_code": code}
    )
    assert resp.status_code == 400


def test_used_invitation_cannot_revoke(client, admin_headers, db, admin_user, normal_user):
    make_invitation(db, code="used-1", created_by=admin_user.id, used_by=normal_user.id)
    resp = client.post("/api/admin/invitations/used-1/revoke", headers=admin_headers)
    assert resp.status_code == 400
