"""Provider 配置测试：掩码、隔离、连通性两分支。

夹具 API Key 为运行期拼接的假值（sk-fake- 前缀 + 拼接段），不指向任何真实服务。
"""

from app.models import UserProvider
from app.security import decrypt_text

FAKE_KEY = "sk-fake-" + "0123456789" + "abcdef"

PROVIDER_BODY = {
    "name": "deepseek",
    "base_url": "https://api.deepseek.example/v1",
    "api_key": FAKE_KEY,
    "default_model": "deepseek-chat",
    "task_models": {"parse": "deepseek-chat", "score": "deepseek-reasoner"},
}


def test_create_masks_key_everywhere(client, user_headers, db, normal_user):
    resp = client.post("/api/providers", headers=user_headers, json=PROVIDER_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["api_key_masked"].endswith("***")
    assert FAKE_KEY not in resp.text

    listing = client.get("/api/providers", headers=user_headers)
    assert FAKE_KEY not in listing.text

    row = db.query(UserProvider).filter_by(user_id=normal_user.id).one()
    assert row.api_key_encrypted != FAKE_KEY
    assert decrypt_text(row.api_key_encrypted) == FAKE_KEY


def test_provider_isolation_between_users(client, user_headers, other_headers):
    created = client.post("/api/providers", headers=user_headers, json=PROVIDER_BODY).json()
    pid = created["id"]

    assert client.get("/api/providers", headers=other_headers).json() == []
    assert client.put(f"/api/providers/{pid}", headers=other_headers, json=PROVIDER_BODY).status_code == 404
    assert client.delete(f"/api/providers/{pid}", headers=other_headers).status_code == 404


def test_update_keeps_old_key_when_masked(client, user_headers):
    created = client.post("/api/providers", headers=user_headers, json=PROVIDER_BODY).json()
    pid = created["id"]
    body = dict(PROVIDER_BODY, api_key=created["api_key_masked"])  # 前端回传掩码
    resp = client.put(f"/api/providers/{pid}", headers=user_headers, json=body)
    assert resp.status_code == 200
    assert resp.json()["api_key_masked"] == created["api_key_masked"]


def test_connectivity_test_both_branches(client, user_headers, monkeypatch, db, normal_user):
    created = client.post("/api/providers", headers=user_headers, json=PROVIDER_BODY).json()
    pid = created["id"]

    import app.llm_gateway as gw
    from app.models import LlmCall

    monkeypatch.setattr(
        gw, "_invoke", lambda p, m, msgs: {"content": "好", "input_tokens": 1, "output_tokens": 1}
    )
    ok = client.post(f"/api/providers/{pid}/test", headers=user_headers).json()
    assert ok["ok"] is True
    # 连通性调用也记账
    record = db.query(LlmCall).filter_by(user_id=normal_user.id, task_type="connectivity").one()
    assert record.status == "ok"

    def boom(p, m, msgs):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr(gw, "_invoke", boom)
    bad = client.post(f"/api/providers/{pid}/test", headers=user_headers).json()
    assert bad["ok"] is False
    assert "401" in bad["error"]
    failed = (
        db.query(LlmCall)
        .filter_by(user_id=normal_user.id, task_type="connectivity", status="error")
        .count()
    )
    assert failed == 1
