import pytest
from pydantic import BaseModel

import app.llm_gateway as gw
from app.models import LlmCall


class _Out(BaseModel):
    title: str


SYSTEM = "sys"
USER = "请输出 JSON"


def _seed_provider(db, user):
    from app.security import encrypt_text

    from app.models import UserProvider

    p = UserProvider(
        user_id=user.id,
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        api_key_encrypted=encrypt_text("sk-any"),
        default_model="deepseek-chat",
    )
    db.add(p)
    db.commit()
    return p


def test_good_response_first_attempt(client, db, normal_user, monkeypatch):
    _seed_provider(db, normal_user)
    calls = []

    def fake_invoke(provider, model, messages):
        calls.append((provider.name if provider else None, model, len(messages)))
        return {"content": '{"title": "后端工程师"}', "input_tokens": 10, "output_tokens": 5}

    monkeypatch.setattr(gw, "_invoke", fake_invoke)
    result = gw.chat_structured(db, normal_user.id, "parse", SYSTEM, USER, _Out)
    assert result.data["title"] == "后端工程师"
    assert result.attempts == 1
    assert calls[0][0] == "deepseek"  # 用户 provider 被解析使用

    records = db.query(LlmCall).all()
    assert len(records) == 1 and records[0].status == "ok"


def test_bad_json_then_recovered(client, db, normal_user, monkeypatch):
    outputs = iter(
        [
            {"content": "这不是JSON", "input_tokens": 10, "output_tokens": 5},
            {"content": "```json\n{\"title\": \"AI工程师\"}\n```", "input_tokens": 20, "output_tokens": 6},
        ]
    )
    captured_messages = []

    def fake_invoke(provider, model, messages):
        captured_messages.append(list(messages))
        return next(outputs)

    monkeypatch.setattr(gw, "_invoke", fake_invoke)
    result = gw.chat_structured(db, normal_user.id, "parse", SYSTEM, USER, _Out)
    assert result.attempts == 2
    assert result.data["title"] == "AI工程师"
    # 重试时把校验错误拼回去了
    assert len(captured_messages[1]) == 4  # system+user+assistant+纠错提示
    assert "无法通过校验" in captured_messages[1][-1]["content"]

    records = db.query(LlmCall).all()
    assert {r.status for r in records} == {"error", "ok"}  # 失败也留痕


def test_all_attempts_fail_records_and_raises(client, db, normal_user, monkeypatch):
    def always_bad(provider, model, messages):
        return {"content": "still not json", "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(gw, "_invoke", always_bad)
    with pytest.raises(gw.LlmGatewayError, match="3 次尝试"):
        gw.chat_structured(db, normal_user.id, "parse", SYSTEM, USER, _Out)
    records = db.query(LlmCall).all()
    assert len(records) == 3 and all(r.status == "error" for r in records)


def test_provider_exception_recorded(client, db, normal_user, monkeypatch):
    def network_error(provider, model, messages):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(gw, "_invoke", network_error)
    with pytest.raises(gw.LlmGatewayError, match="connection refused"):
        gw.chat_structured(db, normal_user.id, "parse", SYSTEM, USER, _Out)
    records = db.query(LlmCall).all()
    assert records[0].status == "error" and "connection refused" in records[0].error


def test_fallback_model_without_provider(client, db, monkeypatch):
    seen = []

    def fake_invoke(provider, model, messages):
        seen.append((provider, model))
        return {"content": '{"title": "x"}', "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(gw, "_invoke", fake_invoke)
    gw.chat_structured(db, None, "score", SYSTEM, USER, _Out)
    assert seen[0][0] is None  # 无 provider（未配置）
