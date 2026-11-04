"""简历修改建议测试：生成、定位校验、缓存、强制重算与用户隔离。

LLM 一律打桩（monkeypatch app.llm_gateway._invoke），零网络零成本。
"""

import json
import time

import app.llm_gateway as gw
from app import scoring, suggestions
from app.models import Company, JobPosting, LlmCall, MatchResult, Resume, Suggestion

PROFILE = {
    "basic_info": {"name": "张三", "location": "上海", "years_of_experience": 3},
    "education": [{"school": "某大学", "degree": "本科", "major": "计算机"}],
    "work": [
        {
            "company": "某公司",
            "title": "后端开发工程师",
            "period": "2021-2024",
            "highlights": ["订单系统"],
        }
    ],
    "projects": [],
    "skills": ["Python", "MySQL", "Redis"],
    "certificates": [],
    "self_summary": "三年后端开发经验。",
}

SCORE = {
    "dimension_scores": {"技能匹配": 80, "经验相关度": 70, "职级与薪资匹配": 60, "行业/业务匹配": 50},
    "verdict": "匹配良好",
    "reasons": "技能与岗位基本吻合。",
    "matching_points": ["Python 与 MySQL 均命中"],
    "gaps": ["缺少 Kafka 经验"],
    "score_basis": "四维均等加权",
}

SUGGESTION = {
    "suggestions": [
        {
            "section": "work[0].highlights",
            "action": "改写",
            "original": "订单系统",
            "proposed": "负责订单系统重构，峰值 QPS 提升 30%",
            "why": "岗位要求高并发交易系统经验",
            "priority": "高",
        },
        {
            "section": "skills",
            "action": "补充关键词",
            "original": "",
            "proposed": "如有 Kafka 实际经验请补充说明",
            "why": "岗位把 Kafka 列为硬性要求",
            "priority": "medium",
        },
        {
            "section": "projects[0].highlights",
            "action": "改写",
            "original": "不存在的经历",
            "proposed": "编造的经历",
            "why": "测试定位失败",
            "priority": "low",
        },
    ],
    "missing_keywords": ["Kafka", "Kubernetes"],
    "honesty_warnings": ["岗位要求 Kafka，简历无对应证据，不得虚构"],
}


def make_resume(db, user, **kwargs) -> Resume:
    resume = Resume(
        user_id=user.id,
        name=kwargs.pop("name", "resume.md"),
        file_path=kwargs.pop("file_path", f"data/uploads/{user.id}/resume.md"),
        file_format="md",
        original_encrypted=kwargs.pop("original_encrypted", ""),
        parsed_profile_json=kwargs.pop("profile", PROFILE),
        version=kwargs.pop("version", 1),
        is_master=kwargs.pop("is_master", True),
        parse_status=kwargs.pop("parse_status", "done"),
        **kwargs,
    )
    db.add(resume)
    db.commit()
    return resume


def make_job(db, company_name="米哈游", **kwargs) -> JobPosting:
    company = Company(name=company_name)
    db.add(company)
    db.commit()
    job = JobPosting(
        company_id=company.id,
        title=kwargs.pop("title", "后端开发工程师"),
        location=kwargs.pop("location", "上海"),
        employment_type="全职",
        salary_range="25-45K",
        experience_required=kwargs.pop("experience_required", "3-5年"),
        education_required=kwargs.pop("education_required", "本科及以上"),
        skills=kwargs.pop("skills", ["Python", "MySQL"]),
        responsibilities=[],
        requirements=[],
        nice_to_have=[],
        description_raw="负责订单系统开发，要求熟悉 Kafka。",
        source_url=None,
        source_type="manual",
        content_hash="b" * 64,
        is_active=kwargs.pop("is_active", True),
        **kwargs,
    )
    db.add(job)
    db.commit()
    return job


def mock_llm(monkeypatch, score=None, suggestion=None, calls=None):
    """按 system 提示词区分打分/建议两类调用，返回对应固定 JSON。"""
    calls = calls if calls is not None else []

    def fake_invoke(provider, model, messages):
        calls.append(messages)
        system_prompt = messages[0]["content"] if messages else ""
        if "简历顾问" in system_prompt:
            text = suggestion if suggestion is not None else json.dumps(SUGGESTION, ensure_ascii=False)
        else:
            text = score if score is not None else json.dumps(SCORE, ensure_ascii=False)
        return {"content": text, "input_tokens": 900, "output_tokens": 200}

    monkeypatch.setattr(gw, "_invoke", fake_invoke)
    return calls


def seed_match(db, user) -> MatchResult:
    resume = make_resume(db, user)
    job = make_job(db)
    view = scoring.load_job(db, "job_posting", job.id, user_id=user.id)
    return scoring.score_one(db, user, resume, view)


def wait_task(client, headers, task_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/tasks/{task_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError("任务超时未完成")


def run_generate(client, headers, match_id: int, force: bool = False) -> dict:
    resp = client.post("/api/suggestions", headers=headers, json={"match_id": match_id, "force": force})
    assert resp.status_code == 202, resp.text
    task = wait_task(client, headers, resp.json()["task_id"])
    assert task["status"] == "done", task.get("error")
    return task


# ---------------------------------------------------------------- 纯逻辑


def test_locate_original_ignores_whitespace():
    text = suggestions.profile_text(PROFILE)
    assert suggestions.locate_original(text, "订单系统")
    assert suggestions.locate_original(text, " 订单 系统 ")  # 空白差异不影响定位
    assert suggestions.locate_original(text, "订单\n系统")
    assert suggestions.locate_original(text, "") is True
    assert suggestions.locate_original(text, "不存在的经历") is False


def test_normalize_payload_flags_unlocatable_and_clamps():
    raw = {
        "suggestions": [
            {
                "section": "",
                "action": "未知动作",
                "original": "不存在的经历",
                "proposed": "编造",
                "why": "",
                "priority": "紧急",
            }
        ]
        + [
            {"section": "skills", "action": "改写", "original": "", "proposed": "x", "why": "y", "priority": "low"}
            for _ in range(12)
        ],
        "missing_keywords": ["Kafka"],
        "honesty_warnings": ["  "],
    }
    payload = suggestions.SuggestionPayload(**raw)
    data = suggestions.normalize_payload(payload, suggestions.profile_text(PROFILE))

    assert len(data["suggestions"]) == suggestions.MAX_ITEMS
    first = data["suggestions"][0]
    assert first["section"] == "未指明"
    assert first["action"] == "改写"
    assert first["priority"] == "high"
    assert any("原文未能在简历中定位" in w for w in data["honesty_warnings"])
    assert data["missing_keywords"] == ["Kafka"]


def test_section_label_maps_field_path():
    assert suggestions.section_label("work[0].highlights") == "工作经历"
    assert suggestions.section_label("basic_info") == "基本信息"
    assert suggestions.section_label("weird_path") == "weird_path"


# ---------------------------------------------------------------- API 流程


def test_generate_suggestion_flow(client, user_headers, db, normal_user, monkeypatch):
    calls: list = []
    mock_llm(monkeypatch, calls=calls)
    match = seed_match(db, normal_user)
    calls.clear()

    task = run_generate(client, user_headers, match.id)
    assert task["result"]["count"] == 3
    assert task["result"]["missing_keywords"] == 2
    assert len(calls) == 1
    assert "缺少 Kafka 经验" in calls[0][-1]["content"]

    items = client.get("/api/suggestions", headers=user_headers, params={"match_id": match.id}).json()
    assert len(items) == 1
    item = items[0]
    assert item["match_id"] == match.id
    assert item["job_title"] == "后端开发工程师"
    assert item["match_score"] == 65
    assert len(item["suggestions"]) == 3
    assert item["missing_keywords"] == ["Kafka", "Kubernetes"]
    assert item["suggestions"][0]["section_label"] == "工作经历"
    assert item["suggestions"][2]["original"] == "不存在的经历"
    joined = " ".join(item["honesty_warnings"])
    assert "岗位要求 Kafka" in joined
    assert "原文未能在简历中定位" in joined

    detail = client.get(f"/api/suggestions/{item['id']}", headers=user_headers).json()
    assert detail["id"] == item["id"]
    assert detail["gaps"] == ["缺少 Kafka 经验"]
    assert detail["tokens"] == {"input": 900, "output": 200}

    recorded = db.query(LlmCall).filter_by(task_type="suggest").all()
    assert len(recorded) == 1


def test_generate_is_cached_and_force_regenerates(client, user_headers, db, normal_user, monkeypatch):
    calls: list = []
    mock_llm(monkeypatch, calls=calls)
    match = seed_match(db, normal_user)
    calls.clear()

    first = run_generate(client, user_headers, match.id)
    assert first["result"]["count"] == 3
    assert len(calls) == 1

    second = run_generate(client, user_headers, match.id)
    assert second["result"]["suggestion_id"] == first["result"]["suggestion_id"]
    assert len(calls) == 1  # 命中缓存，不再调用模型
    assert db.query(Suggestion).count() == 1

    third = run_generate(client, user_headers, match.id, force=True)
    assert third["result"]["suggestion_id"] == first["result"]["suggestion_id"]
    assert len(calls) == 2
    assert db.query(Suggestion).count() == 1
    assert db.query(LlmCall).filter_by(task_type="suggest").count() == 2


def test_generate_requires_own_and_scored_match(client, user_headers, other_headers, db, normal_user, monkeypatch):
    mock_llm(monkeypatch)
    match = seed_match(db, normal_user)

    resp = client.post("/api/suggestions", headers=user_headers, json={"match_id": 999})
    assert resp.status_code == 404
    resp = client.post("/api/suggestions", headers=other_headers, json={"match_id": match.id})
    assert resp.status_code == 404

    other_list = client.get("/api/suggestions", headers=other_headers).json()
    assert other_list == []

    generated = client.post("/api/suggestions", headers=user_headers, json={"match_id": match.id}).json()
    wait_task(client, user_headers, generated["task_id"])
    suggestion_id = server_suggestion_id(client, user_headers, match.id)

    assert client.get(f"/api/suggestions/{suggestion_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/suggestions/{suggestion_id}", headers=user_headers).status_code == 200


def server_suggestion_id(client, headers, match_id: int) -> int:
    items = client.get("/api/suggestions", headers=headers, params={"match_id": match_id}).json()
    assert items, "建议列表为空"
    return items[0]["id"]


def test_generate_failure_marks_task_failed(client, user_headers, db, normal_user, monkeypatch):
    mock_llm(monkeypatch, suggestion='{"suggestions": "不是数组"}')
    match = seed_match(db, normal_user)

    resp = client.post("/api/suggestions", headers=user_headers, json={"match_id": match.id})
    assert resp.status_code == 202
    task = wait_task(client, user_headers, resp.json()["task_id"])
    assert task["status"] == "failed"
    assert "校验" in (task["error"] or "")
    assert db.query(Suggestion).count() == 0
