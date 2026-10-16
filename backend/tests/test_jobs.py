import json

import app.llm_gateway as gw
from app.models import JobPosting, UserManualJob

JD_TEXT = (
    "岗位名称：高级后端开发工程师（电商方向）\n部门：电商技术部\n工作地点：上海\n"
    "薪资：25-45K·16薪\n经验：3-5年\n学历：本科及以上\n"
    "职责：负责订单系统开发；优化高并发链路。\n"
    "要求：精通 Go；熟悉 MySQL、Redis、Kafka；有电商经验优先。"
)

PARSED_JD = {
    "title": "高级后端开发工程师（电商方向）",
    "department": "电商技术部",
    "location": "上海",
    "employment_type": "全职",
    "salary_range": "25-45K·16薪",
    "experience_required": "3-5年",
    "education_required": "本科及以上",
    "skills": ["Go", "MySQL", "Redis", "Kafka"],
    "responsibilities": ["负责订单系统开发", "优化高并发链路"],
    "requirements": ["精通 Go", "熟悉 MySQL、Redis、Kafka"],
    "nice_to_have": ["有电商经验优先"],
}


def mock_llm_ok(monkeypatch):
    def fake_invoke(provider, model, messages):
        return {"content": json.dumps(PARSED_JD), "input_tokens": 100, "output_tokens": 200}

    monkeypatch.setattr(gw, "_invoke", fake_invoke)


def test_admin_manual_job_goes_shared(client, admin_headers, db, monkeypatch):
    mock_llm_ok(monkeypatch)
    company = client.post("/api/companies", headers=admin_headers, json={"name": "米哈游"}).json()

    resp = client.post(
        "/api/jobs/manual",
        headers=admin_headers,
        json={"jd_text": JD_TEXT, "company_id": company["id"]},
    )
    assert resp.status_code == 202
    assert resp.json()["job_ref_type"] == "job_posting"

    job = db.query(JobPosting).one()
    assert job.title == PARSED_JD["title"]
    assert job.source_type == "manual"
    assert job.skills == PARSED_JD["skills"]
    assert len(job.content_hash) == 64  # sha256 hex

    listing = client.get("/api/jobs/shared", headers=admin_headers).json()
    assert listing[0]["company"] == "米哈游"
    assert listing[0]["title"] == PARSED_JD["title"]


def test_user_manual_job_is_private(client, user_headers, db, monkeypatch):
    mock_llm_ok(monkeypatch)
    resp = client.post(
        "/api/jobs/manual",
        headers=user_headers,
        json={"jd_text": JD_TEXT, "company_name": "某创业公司"},
    )
    assert resp.status_code == 202
    assert resp.json()["job_ref_type"] == "user_manual_job"

    job = db.query(UserManualJob).one()
    assert job.user_id is not None and job.title == PARSED_JD["title"]

    # 私有岗在本人列表可见
    mine = client.get("/api/jobs/mine", headers=user_headers).json()
    assert mine[0]["company"] == "某创业公司"


def test_failed_parse_can_retry(client, user_headers, db, monkeypatch):
    # 第一轮：LLM 始终失败
    def always_bad(provider, model, messages):
        return {"content": "I refuse to output JSON", "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(gw, "_invoke", always_bad)
    resp = client.post("/api/jobs/manual", headers=user_headers, json={"jd_text": JD_TEXT})
    task_id = resp.json()["task_id"]

    task = client.get(f"/api/tasks/{task_id}", headers=user_headers).json()
    assert task["status"] == "failed"
    assert task["error"]  # 可读错误信息

    # 第二轮：LLM 恢复，重试成功
    mock_llm_ok(monkeypatch)
    retry = client.post(f"/api/tasks/{task_id}/retry", headers=user_headers)
    assert retry.status_code == 202

    job = db.query(UserManualJob).one()
    assert job.title == PARSED_JD["title"]
    assert client.get(f"/api/tasks/{task_id}", headers=user_headers).json()["status"] == "done"


def test_company_requires_admin(client, user_headers):
    assert (
        client.post("/api/companies", headers=user_headers, json={"name": "X"}).status_code == 403
    )
