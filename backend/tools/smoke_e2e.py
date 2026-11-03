"""端到端冒烟：真实 uvicorn + sqlite + litellm → 本地 OpenAI 兼容桩。

覆盖：注册登录 → 配 provider → 打分（LLM 真实经过 litellm）→ 结果/成本/岗位列表带分。
"""

import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:8098"
DB = "data/smoke-e2e.db"
EXPECTED_SCORE = 65  # (80+70+60+50)/4

PROFILE = {
    "basic_info": {"name": "张三", "location": "上海", "years_of_experience": 3},
    "education": [{"school": "某大学", "degree": "本科", "major": "计算机"}],
    "work": [{"company": "某公司", "title": "后端开发工程师", "period": "2021-2024", "highlights": ["订单系统"]}],
    "projects": [],
    "skills": ["Python", "MySQL", "Redis"],
    "certificates": [],
    "self_summary": "三年后端开发经验。",
}


def call(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def seed_rows(username: str) -> None:
    conn = sqlite3.connect(DB)
    now = datetime.now(timezone.utc).isoformat(sep=" ")
    user_id = conn.execute("select id from users where username=?", (username,)).fetchone()[0]
    conn.execute(
        "insert into resumes (user_id, name, file_path, file_format, original_encrypted,"
        " parsed_profile_json, version, is_master, parse_status, parse_error, created_at)"
        " values (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, "resume.md", f"data/uploads/{user_id}/resume.md", "md", "",
         json.dumps(PROFILE, ensure_ascii=False), 1, 1, "done", None, now),
    )
    company_id = conn.execute("insert into companies (name, created_at) values (?,?)", ("米哈游", now)).lastrowid
    for index, title in enumerate(["后端开发工程师", "资深后端工程师（10年+）"]):
        conn.execute(
            "insert into job_postings (company_id, title, location, employment_type, salary_range,"
            " experience_required, education_required, skills, responsibilities, requirements,"
            " nice_to_have, description_raw, source_url, source_type, content_hash, is_active,"
            " scraped_at, created_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (company_id, title, "上海", "全职", "25-45K",
             "3-5年" if index == 0 else "10年以上", "本科及以上",
             json.dumps(["Python", "MySQL"], ensure_ascii=False),
             json.dumps([], ensure_ascii=False), json.dumps([], ensure_ascii=False),
             json.dumps([], ensure_ascii=False), "负责订单系统开发。", None, "manual",
             "c" * 64, 1, now, now),
        )
    conn.commit()
    conn.close()


def wait_task(task_id: str, token: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, task = call("GET", f"/api/tasks/{task_id}", token=token)
        if task["status"] in ("done", "failed"):
            return task
        time.sleep(1.5)
    raise TimeoutError(f"任务 {task_id} 超时未完成")


def main() -> int:
    status, health = call("GET", "/healthz")
    print(f"[ok] healthz {status} {health}")

    status, body = call("POST", "/api/auth/register", {"username": "smoke", "password": "smoke-pass-123"})
    print(f"[{'ok' if status in (200, 201) else 'fail'}] register {status} {body if status >= 400 else ''}")
    status, login = call("POST", "/api/auth/login", {"username": "smoke", "password": "smoke-pass-123"})
    assert status == 200, login
    token = login["token"]
    print(f"[ok] login, admin={login.get('is_admin')}")

    status, provider = call(
        "POST",
        "/api/providers",
        {
            "name": "stub",
            "base_url": "http://127.0.0.1:8099/v1",
            "api_key": "sk-stub-key",
            "default_model": "openai/stub-model",
            "task_models": {},
        },
        token=token,
    )
    print(f"[{'ok' if status in (200, 201) else 'fail'}] provider {status}")
    assert status in (200, 201), provider

    seed_rows("smoke")

    status, run = call("POST", "/api/matches/run", {}, token=token)
    print(f"[{'ok' if status == 202 else 'fail'}] run {status} {run}")
    task = wait_task(run["task_id"], token)
    result = task.get("result") or {}
    print(f"[info] task {task['status']} result={json.dumps(result, ensure_ascii=False)}")
    assert task["status"] == "done", task
    assert result.get("scored") == 1, result
    assert len(result.get("excluded") or []) == 1, result

    status, matches = call("GET", "/api/matches", token=token)
    print(f"[{'ok' if status == 200 else 'fail'}] matches {status} {json.dumps(matches, ensure_ascii=False)[:300]}")
    assert status == 200 and len(matches) == 1, matches
    match = matches[0]
    assert match["score"] == EXPECTED_SCORE, match
    assert match["title"] == "后端开发工程师", match

    status, detail = call("GET", f"/api/matches/{match['id']}", token=token)
    print(f"[{'ok' if status == 200 else 'fail'}] detail verdict={detail.get('verdict')} gaps={detail.get('gaps')}")
    assert detail["verdict"] == "匹配良好"

    status, jobs = call("GET", "/api/jobs/shared?sort=score", token=token)
    scored_first = jobs[0]["match_score"] if jobs else None
    print(f"[{'ok' if scored_first == EXPECTED_SCORE else 'fail'}] jobs?sort=score first={scored_first}")
    assert scored_first == EXPECTED_SCORE, jobs[:1]

    status, costs = call("GET", "/api/costs/summary", token=token)
    score_calls = [c for c in costs if c["task_type"] == "score"]
    print(f"[{'ok' if score_calls else 'fail'}] costs {json.dumps(score_calls, ensure_ascii=False)}")
    assert score_calls and score_calls[0]["calls"] >= 1, costs

    status, weights = call("PUT", "/api/matches/weights",
                           {"技能匹配": 100, "经验相关度": 0, "职级与薪资匹配": 0, "行业/业务匹配": 0}, token=token)
    print(f"[{'ok' if status == 200 else 'fail'}] weights {status}")

    status, rerun = call("POST", "/api/matches/run", {"force": True}, token=token)
    task = wait_task(rerun["task_id"], token)
    status, matches = call("GET", "/api/matches", token=token)
    print(f"[{'ok' if matches[0]['score'] == 80 else 'fail'}] force rescore with new weights score={matches[0]['score']}")
    assert matches[0]["score"] == 80, matches[0]

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
