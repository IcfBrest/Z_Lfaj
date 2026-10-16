import io
import json

import app.llm_gateway as gw
from app.models import Resume

RESUME_TEXT = """张三
手机：13800138000  邮箱：zhangsan@example.com
教育经历：某大学 计算机科学 本科 2016-2020
工作经历：
某公司 后端工程师 2020-2023
- 负责订单系统，日单量300万
- 用 Go 和 MySQL 优化核心链路
技能：Go, MySQL, Redis, Kafka
"""

IDENTITY = {"name": "张三", "phone": "13800138000", "email": "zhangsan@example.com", "id_number": None}

PROFILE = {
    "basic_info": {"name": "__NAME__", "phone": "__PHONE__", "email": "__EMAIL__", "location": None, "years_of_experience": 3},
    "education": [{"school": "某大学", "degree": "本科", "major": "计算机科学", "period": "2016-2020"}],
    "work": [{"company": "某公司", "title": "后端工程师", "period": "2020-2023", "highlights": ["负责订单系统，日单量300万", "用 Go 和 MySQL 优化核心链路"]}],
    "projects": [],
    "skills": ["Go", "MySQL", "Redis", "Kafka"],
    "certificates": [],
    "self_summary": None,
}


def make_resume_llm(monkeypatch, captured):
    """两遍简历解析的 LLM 桩：先身份抽取，后 Master Profile；记录每次出站消息。"""

    def fake_invoke(provider, model, messages):
        prompt = messages[-1]["content"]
        captured.append(prompt)
        if "姓名、手机号、邮箱、身份证号" in messages[0]["content"]:
            return {"content": json.dumps(IDENTITY), "input_tokens": 50, "output_tokens": 20}
        return {"content": json.dumps(PROFILE), "input_tokens": 500, "output_tokens": 300}

    monkeypatch.setattr(gw, "_invoke", fake_invoke)


def _pdf_file(text: str):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return ("resume.pdf", data, "application/pdf")


def _docx_file(text: str):
    from docx import Document

    doc = Document()
    for line in text.splitlines():
        if line.strip():
            doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return ("resume.docx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _md_file(text: str):
    return ("resume.md", text.encode(), "text/markdown")


def upload(client, headers, file_tuple):
    name, data, mime = file_tuple
    return client.post(
        "/api/resumes", headers=headers, files={"file": (name, data, mime)}
    )


def test_upload_md_parse_and_masking(client, user_headers, db, monkeypatch, normal_user):
    captured: list[str] = []
    make_resume_llm(monkeypatch, captured)

    resp = upload(client, user_headers, _md_file(RESUME_TEXT))
    assert resp.status_code == 202
    resume_id = resp.json()["resume_id"]

    resume = db.get(Resume, resume_id)
    assert resume.parse_status == "done"
    profile = resume.parsed_profile_json
    assert profile["skills"] == ["Go", "MySQL", "Redis", "Kafka"]
    assert profile["work"][0]["highlights"][0] == "负责订单系统，日单量300万"

    # 脱敏断言：两次出站调用（身份抽取那遍收到原文，结构化那遍必须是脱敏文）
    identity_prompt, profile_prompt = captured
    assert "13800138000" in identity_prompt  # 第一遍（本地识别）收到原文
    masked = profile_prompt
    assert "13800138000" not in masked
    assert "zhangsan@example.com" not in masked
    assert "张三" not in masked
    assert "__PHONE__" in masked and "__NAME__" in masked and "__EMAIL__" in masked

    # 原文加密落库
    assert resume.original_encrypted != RESUME_TEXT


def test_upload_pdf_and_docx(client, user_headers, db, monkeypatch):
    captured: list[str] = []
    make_resume_llm(monkeypatch, captured)

    for maker in (_pdf_file, _docx_file):
        resp = upload(client, user_headers, maker(RESUME_TEXT))
        assert resp.status_code == 202, (maker, resp.text)
        resume = db.get(Resume, resp.json()["resume_id"])
        assert resume.parse_status == "done", (maker, resume.parse_error)
        assert resume.parsed_profile_json["skills"]


def test_resume_isolation_between_users(client, user_headers, other_headers, monkeypatch):
    captured: list[str] = []
    make_resume_llm(monkeypatch, captured)
    resp = upload(client, user_headers, _md_file(RESUME_TEXT))
    resume_id = resp.json()["resume_id"]

    assert client.get(f"/api/resumes/{resume_id}", headers=other_headers).status_code == 404
    assert client.get("/api/resumes", headers=other_headers).json() == []


def test_master_uniqueness_and_switch(client, user_headers, monkeypatch):
    captured: list[str] = []
    make_resume_llm(monkeypatch, captured)
    first = upload(client, user_headers, _md_file(RESUME_TEXT)).json()
    assert first["is_master"] is True  # 首份自动 master

    second = upload(client, user_headers, _md_file(RESUME_TEXT + "\n补充：熟悉 K8s")).json()
    assert second["is_master"] is False
    assert second["version"] == 2  # 同名文件 → 版本递增
    assert second["resume_id"] != first["resume_id"]

    resp = client.post(f"/api/resumes/{second['resume_id']}/set-master", headers=user_headers)
    assert resp.status_code == 204
    listing = client.get("/api/resumes", headers=user_headers).json()
    masters = [r for r in listing if r["is_master"]]
    assert len(masters) == 1 and masters[0]["id"] == second["resume_id"]


def test_unsupported_and_empty_files_rejected(client, user_headers):
    assert (
        client.post(
            "/api/resumes",
            headers=user_headers,
            files={"file": ("x.txt", b"hello", "text/plain")},
        ).status_code
        == 400
    )
    # 空文本 PDF（扫描件等价物）
    import fitz

    doc = fitz.open()
    doc.new_page()
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    resp = client.post("/api/resumes", headers=user_headers, files={"file": ("empty.pdf", buf.getvalue(), "application/pdf")})
    assert resp.status_code == 400
    assert "未抽取到任何文本" in resp.json()["detail"]


def test_delete_resume(client, user_headers, monkeypatch):
    captured: list[str] = []
    make_resume_llm(monkeypatch, captured)
    rid = upload(client, user_headers, _md_file(RESUME_TEXT)).json()["resume_id"]
    assert client.delete(f"/api/resumes/{rid}", headers=user_headers).status_code == 204
    assert client.get(f"/api/resumes/{rid}", headers=user_headers).status_code == 404
