"""匹配打分 API 测试：全量打分、缓存、权重、硬过滤、隔离与失败路径。

LLM 一律打桩（monkeypatch app.llm_gateway._invoke），零网络零成本。
"""

import json

import app.llm_gateway as gw
from app.models import Company, JobPosting, MatchResult, Resume, UserManualJob

PROFILE = {
    "basic_info": {"name": "张三", "location": "上海", "years_of_experience": 3},
    "education": [{"school": "某大学", "degree": "本科", "major": "计算机"}],
    "work": [{"company": "某公司", "title": "后端开发工程师", "period": "2021-2024", "highlights": ["订单系统"]}],
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
        description_raw="负责订单系统开发。",
        source_url=None,
        source_type="manual",
        content_hash="a" * 64,
        is_active=kwargs.pop("is_active", True),
        **kwargs,
    )
    db.add(job)
    db.commit()
    return job


def mock_score(monkeypatch, payload=None, calls=None, content=None):
    """把模型调用换成固定 JSON；calls 传入列表可统计调用次数。"""

    def fake_invoke(provider, model, messages):
        if calls is not None:
            calls.append(messages)
        text = content if content is not None else json.dumps(payload or SCORE, ensure_ascii=False)
        return {"content": text, "input_tokens": 1200, "output_tokens": 200}

    monkeypatch.setattr(gw, "_invoke", fake_invoke)


def run_full(client, headers, **body) -> dict:
    resp = client.post("/api/matches/run", headers=headers, json=body)
    assert resp.status_code == 202, resp.text
    task = client.get(f"/api/tasks/{resp.json()['task_id']}", headers=headers).json()
    assert task["status"] == "done", task
    return task


# ---------------------------------------------------------------- 全量打分


def test_full_run_scores_visible_jobs(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    make_job(db)
    calls: list = []
    mock_score(monkeypatch, calls=calls)

    task = run_full(client, user_headers)
    assert task["result"]["scored"] == 1
    assert task["result"]["failed"] == 0
    assert len(calls) == 1

    items = client.get("/api/matches", headers=user_headers).json()
    assert len(items) == 1
    item = items[0]
    assert item["score"] == 65  # (80+70+60+50)/4
    assert item["title"] == "后端开发工程师"
    assert item["company"] == "米哈游"
    assert item["dimension_scores"]["技能匹配"] == 80
    assert item["missing_dimensions"] == []

    detail = client.get(f"/api/matches/{item['id']}", headers=user_headers).json()
    assert detail["verdict"] == "匹配良好"
    assert detail["matching_points"] == ["Python 与 MySQL 均命中"]
    assert detail["gaps"] == ["缺少 Kafka 经验"]
    assert detail["job_snapshot"]["title"] == "后端开发工程师"
    assert detail["weights"]["技能匹配"] == 25.0
    assert "订单系统" in detail["description_excerpt"]


def test_cache_prevents_repeat_calls_and_force_overwrites(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    make_job(db)
    calls: list = []
    mock_score(monkeypatch, calls=calls)

    run_full(client, user_headers)
    assert len(calls) == 1

    second = run_full(client, user_headers)
    assert second["result"]["cached"] == 1 and second["result"]["scored"] == 0
    assert len(calls) == 1  # 缓存命中，未再调用模型
    assert db.query(MatchResult).count() == 1

    better = {**SCORE, "dimension_scores": {name: 90 for name in SCORE["dimension_scores"]}}
    mock_score(monkeypatch, payload=better, calls=calls)
    third = run_full(client, user_headers, force=True)
    assert third["result"]["scored"] == 1
    assert len(calls) == 2
    assert db.query(MatchResult).count() == 1  # 覆盖而非新增
    assert client.get("/api/matches", headers=user_headers).json()[0]["score"] == 90


# ---------------------------------------------------------------- 权重


def test_weights_change_total_and_are_validated(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    make_job(db)
    mock_score(monkeypatch)

    current = client.get("/api/matches/weights/current", headers=user_headers).json()
    assert current["weights"] == {name: 25.0 for name in current["dimensions"]}
    assert len(current["dimensions"]) == 4

    payload = {"技能匹配": 100, "经验相关度": 0, "职级与薪资匹配": 0, "行业/业务匹配": 0}
    assert client.put("/api/matches/weights", headers=user_headers, json=payload).status_code == 200

    run_full(client, user_headers)
    items = client.get("/api/matches", headers=user_headers).json()
    assert items[0]["score"] == 80  # 只看得分权重最高的一维
    assert client.get("/api/matches/weights/current", headers=user_headers).json()["weights"]["技能匹配"] == 100.0

    # 校验：缺维度、越界、全 0
    assert client.put("/api/matches/weights", headers=user_headers, json={"技能匹配": 1}).status_code == 400
    assert (
        client.put(
            "/api/matches/weights",
            headers=user_headers,
            json={"技能匹配": 101, "经验相关度": 0, "职级与薪资匹配": 0, "行业/业务匹配": 0},
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/matches/weights",
            headers=user_headers,
            json={"技能匹配": 0, "经验相关度": 0, "职级与薪资匹配": 0, "行业/业务匹配": 0},
        ).status_code
        == 400
    )


# ---------------------------------------------------------------- 硬规则


def test_hard_filter_excludes_too_senior_job_without_llm_call(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    make_job(db, company_name="A 公司", title="后端开发工程师")
    make_job(db, company_name="B 公司", title="首席架构师", experience_required="10年以上")
    calls: list = []
    mock_score(monkeypatch, calls=calls)

    task = run_full(client, user_headers)
    assert task["result"]["candidates"] == 1
    assert task["result"]["scored"] == 1
    assert len(task["result"]["excluded"]) == 1
    assert task["result"]["excluded"][0]["title"] == "首席架构师"
    assert "10" in task["result"]["excluded"][0]["reason"]
    assert len(calls) == 1
    assert db.query(MatchResult).count() == 1


def test_limit_caps_llm_calls(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    for index in range(3):
        make_job(db, company_name=f"公司{index}", title=f"后端开发工程师{index}")
    calls: list = []
    mock_score(monkeypatch, calls=calls)

    task = run_full(client, user_headers, limit=2)
    assert task["result"]["candidates"] == 2
    assert len(calls) == 2


# ---------------------------------------------------------------- 单岗触发


def test_single_job_endpoint_and_ownership(client, user_headers, other_headers, db, normal_user, other_user, monkeypatch):
    make_resume(db, normal_user)
    shared = make_job(db)
    private = UserManualJob(
        user_id=normal_user.id,
        company_name="某创业公司",
        title="Python 工程师",
        location="上海",
        experience_required="1-3年",
        education_required="不限",
        skills=["Python"],
        responsibilities=[],
        requirements=[],
        nice_to_have=[],
        description_raw="写后端。",
        content_hash="b" * 64,
    )
    db.add(private)
    db.commit()
    mock_score(monkeypatch)

    resp = client.post(f"/api/matches/jobs/job_posting/{shared.id}", headers=user_headers, json={})
    assert resp.status_code == 202, resp.text
    assert client.get(f"/api/tasks/{resp.json()['task_id']}", headers=user_headers).json()["status"] == "done"

    resp = client.post(f"/api/matches/jobs/user_manual_job/{private.id}", headers=user_headers, json={})
    assert resp.status_code == 202
    assert client.get(f"/api/tasks/{resp.json()['task_id']}", headers=user_headers).json()["status"] == "done"
    assert db.query(MatchResult).count() == 2

    # 非法类型 / 不存在的岗位
    assert (
        client.post(f"/api/matches/jobs/whatever/{shared.id}", headers=user_headers, json={}).status_code == 400
    )
    assert client.post("/api/matches/jobs/job_posting/99999", headers=user_headers, json={}).status_code == 404
    # 他人的私有岗位不参与，且不可打分
    assert (
        client.post(f"/api/matches/jobs/user_manual_job/{private.id}", headers=other_headers, json={}).status_code
        == 404
    )


def test_match_results_are_isolated_between_users(client, user_headers, other_headers, db, normal_user, other_user, monkeypatch):
    make_resume(db, normal_user)
    make_job(db)
    mock_score(monkeypatch)
    run_full(client, user_headers)

    match_id = client.get("/api/matches", headers=user_headers).json()[0]["id"]
    assert client.get("/api/matches", headers=other_headers).json() == []
    assert client.get(f"/api/matches/{match_id}", headers=other_headers).status_code == 404
    assert client.get("/api/matches/99999", headers=user_headers).status_code == 404


# ---------------------------------------------------------------- 岗位列表带分


def test_job_list_exposes_match_score_and_supports_sort(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    scored = make_job(db, company_name="A 公司", title="后端开发工程师")
    make_job(db, company_name="B 公司", title="数据平台工程师")
    mock_score(monkeypatch)

    unscored = client.get("/api/jobs/shared", headers=user_headers).json()
    assert all(item["match_id"] is None and item["match_score"] is None for item in unscored)

    client.post(f"/api/matches/jobs/job_posting/{scored.id}", headers=user_headers, json={})
    listed = client.get("/api/jobs/shared", headers=user_headers).json()
    by_title = {item["title"]: item for item in listed}
    assert by_title["后端开发工程师"]["match_score"] == 65
    assert by_title["数据平台工程师"]["match_score"] is None

    sorted_items = client.get("/api/jobs/shared?sort=score", headers=user_headers).json()
    assert sorted_items[0]["title"] == "后端开发工程师"
    assert sorted_items[-1]["match_score"] is None


# ---------------------------------------------------------------- 失败与前置条件


def test_unparsed_or_missing_resume_is_rejected(client, user_headers, other_headers, db, normal_user, monkeypatch):
    mock_score(monkeypatch)
    assert client.post("/api/matches/run", headers=other_headers, json={}).status_code == 404  # 没有简历

    make_resume(db, normal_user, profile=None, parse_status="pending")
    resp = client.post("/api/matches/run", headers=user_headers, json={})
    assert resp.status_code == 400 and "解析" in resp.json()["detail"]


def test_llm_failure_is_recorded_without_breaking_task(client, user_headers, db, normal_user, monkeypatch):
    make_resume(db, normal_user)
    make_job(db)
    mock_score(monkeypatch, content="抱歉，我无法输出 JSON。")

    task = run_full(client, user_headers)
    assert task["result"]["failed"] == 1
    assert task["result"]["scored"] == 0
    assert task["result"]["failures"][0]["error"]
    assert db.query(MatchResult).count() == 0
