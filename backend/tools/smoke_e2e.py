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

# Windows 上 urllib 会读取注册表里的系统代理，本机回环请求必须绕过，否则会拿到 502
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

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
        with _OPENER.open(request, timeout=60) as resp:
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

    # ---- Phase 2：按岗位生成修改建议（同一桩服务，靠提示词区分任务） ----
    target = matches[0]
    status, gen = call("POST", "/api/suggestions", {"match_id": target["id"]}, token=token)
    print(f"[{'ok' if status == 202 else 'fail'}] suggestion run {status} {gen}")
    assert status == 202, gen
    task = wait_task(gen["task_id"], token)
    result = task.get("result") or {}
    print(f"[info] suggestion task {task['status']} result={json.dumps(result, ensure_ascii=False)}")
    assert task["status"] == "done", task
    assert result.get("count") == 3, result

    status, items = call("GET", f"/api/suggestions?match_id={target['id']}", token=token)
    assert status == 200 and len(items) == 1, items
    item = items[0]
    assert item["suggestions"][0]["section_label"] == "工作经历", item["suggestions"][0]
    assert item["missing_keywords"] == ["Kafka", "Kubernetes"], item["missing_keywords"]
    joined = " ".join(item["honesty_warnings"])
    print(f"[{'ok' if '原文未能在简历中定位' in joined else 'fail'}] honesty_warnings={json.dumps(item['honesty_warnings'], ensure_ascii=False)}")
    assert "原文未能在简历中定位" in joined, item["honesty_warnings"]

    status, again = call("POST", "/api/suggestions", {"match_id": target["id"]}, token=token)
    task2 = wait_task(again["task_id"], token)
    assert task2["result"]["suggestion_id"] == result["suggestion_id"], (task2, result)
    status, costs = call("GET", "/api/costs/summary", token=token)
    suggest_calls = [c for c in costs if c["task_type"] == "suggest"]
    print(f"[{'ok' if suggest_calls and suggest_calls[0]['calls'] == 1 else 'fail'}] suggest calls={json.dumps(suggest_calls, ensure_ascii=False)}")
    assert suggest_calls and suggest_calls[0]["calls"] == 1, costs

    # ---- Phase 3：站点采集（本地桩站点，真实走 urllib + 限速 + 去重 + 下架） ----
    status, sources = call("GET", "/api/admin/scrape/sources", token=token)
    names = {s["source"] for s in sources or []}
    expected = {"mihoyo", "tencent", "bytedance", "bilibili", "meituan"}
    print(f"[{'ok' if names == expected else 'fail'}] scrape sources {names}")
    assert status == 200 and names == expected, sources
    modes = {s["source"]: s["mode"] for s in sources}
    assert modes["bytedance"] == "browser" and modes["meituan"] == "http", modes

    status, run = call("POST", "/api/admin/scrape", {"source": "mihoyo"}, token=token)
    print(f"[{'ok' if status == 202 else 'fail'}] mihoyo scrape run {status} {run}")
    assert status == 202, run
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    print(f"[info] mihoyo first run {json.dumps(res, ensure_ascii=False)}")
    assert task["status"] == "done", task
    assert (res["created"], res["updated"], res["unchanged"], res["failed"]) == (3, 0, 0, 0), res

    status, jobs = call("GET", "/api/jobs/shared", token=token)
    scraped = [j for j in jobs if j["source_type"] == "mihoyo"]
    print(f"[{'ok' if len(scraped) == 3 else 'fail'}] shared jobs after scrape={len(scraped)}")
    assert len(scraped) == 3, scraped
    target_job = next(j for j in scraped if "服务端" in j["title"])
    status, full = call("GET", f"/api/jobs/shared/{target_job['id']}", token=token)
    ok_detail = "【职责】" in (full.get("description_raw") or "") and bool(full.get("requirements"))
    print(f"[{'ok' if ok_detail else 'fail'}] job detail has 职责/要求, url={full.get('source_url')}")
    assert ok_detail, full
    assert full["source_url"].startswith("https://jobs.mihoyo.com/#/position/"), full["source_url"]

    status, run = call("POST", "/api/admin/scrape", {"source": "mihoyo"}, token=token)
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    print(f"[{'ok' if res.get('created') == 0 and res.get('unchanged') == 3 else 'fail'}] mihoyo second run {json.dumps(res, ensure_ascii=False)}")
    assert (res["created"], res["unchanged"], res["deactivated"]) == (0, 3, 0), res

    # 腾讯：先 limit=1 截断跑（不下架），再全量跑（补齐第二条）
    status, run = call("POST", "/api/admin/scrape", {"source": "tencent", "limit": 1}, token=token)
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    assert task["status"] == "done" and res["created"] == 1, res
    assert res["deactivated"] == 0, res
    status, run = call("POST", "/api/admin/scrape", {"source": "tencent"}, token=token)
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    print(f"[{'ok' if res.get('created') == 1 and res.get('unchanged') == 1 else 'fail'}] tencent full run {json.dumps(res, ensure_ascii=False)}")
    assert (res["created"], res["unchanged"], res["deactivated"]) == (1, 1, 0), res

    jobs = call("GET", "/api/jobs/shared", token=token)[1]
    tencent = [j for j in jobs if j["source_type"] == "tencent"]
    years = {j["title"]: j["experience_required"] for j in tencent}
    ok_tencent = len(tencent) == 2 and years.get("后台开发工程师（腾讯云）") == "3年以上工作经验"
    print(f"[{'ok' if ok_tencent else 'fail'}] tencent jobs={len(tencent)} years={json.dumps(years, ensure_ascii=False)}")
    assert ok_tencent, tencent

    status, sources = call("GET", "/api/admin/scrape/sources", token=token)
    by_name = {s["source"]: s for s in sources}
    print(f"[info] sources {json.dumps(sources, ensure_ascii=False)}")
    assert by_name["mihoyo"]["active_jobs"] == 3 and by_name["mihoyo"]["total_jobs"] == 3, by_name["mihoyo"]
    assert by_name["tencent"]["active_jobs"] == 2 and by_name["tencent"]["last_scraped_at"], by_name["tencent"]

    # 采集结果直接进共享库并可被匹配
    status, run = call("POST", "/api/matches/run", {}, token=token)
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    print(f"[{'ok' if res.get('scored', 0) >= 5 else 'fail'}] match after scrape scored={res.get('scored')} cached={res.get('cached')}")
    assert task["status"] == "done" and res.get("scored", 0) >= 5, res
    titles = {m["title"] for m in call("GET", "/api/matches", token=token)[1]}
    assert "服务端开发工程师（原神）" in titles, titles

    # ---- Phase 4：B站（csrf + 明文 JSON）与美团（明文 JSON），字节需浏览器故冒烟跳过 ----
    status, run = call("POST", "/api/admin/scrape", {"source": "bilibili"}, token=token)
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    print(f"[{'ok' if res.get('created') == 2 else 'fail'}] bilibili run {json.dumps(res, ensure_ascii=False)}")
    assert task["status"] == "done" and (res["created"], res["failed"]) == (2, 0), res

    jobs = call("GET", "/api/jobs/shared", token=token)[1]
    bili = [j for j in jobs if j["source_type"] == "bilibili"]
    first_bili = next(j for j in bili if "直播" in j["title"])
    status, full = call("GET", f"/api/jobs/shared/{first_bili['id']}", token=token)
    ok_bili = (
        len(bili) == 2
        and full.get("requirements")
        and full.get("nice_to_have")
        and full["source_url"].startswith("https://jobs.bilibili.com/social/positions/")
    )
    print(f"[{'ok' if ok_bili else 'fail'}] bilibili job resp={len(full.get('responsibilities') or [])} req={len(full.get('requirements') or [])} url={full.get('source_url')}")
    assert ok_bili, full

    status, run = call("POST", "/api/admin/scrape", {"source": "meituan"}, token=token)
    task = wait_task(run["task_id"], token)
    res = task.get("result") or {}
    print(f"[{'ok' if res.get('created') == 2 else 'fail'}] meituan run {json.dumps(res, ensure_ascii=False)}")
    assert task["status"] == "done" and res["created"] == 2, res

    jobs = call("GET", "/api/jobs/shared", token=token)[1]
    mt = [j for j in jobs if j["source_type"] == "meituan"]
    data_job = next(j for j in mt if "数据开发" in j["title"])
    ok_mt = (
        len(mt) == 2
        and data_job["location"] == "北京市、上海市"
        and data_job["experience_required"] == "3-5年"
        and data_job["department"] == "数据/算法"
    )
    print(f"[{'ok' if ok_mt else 'fail'}] meituan jobs={len(mt)} location={data_job['location']} years={data_job['experience_required']}")
    assert ok_mt, mt

    by_name = {s["source"]: s for s in call("GET", "/api/admin/scrape/sources", token=token)[1]}
    assert by_name["bilibili"]["active_jobs"] == 2 and by_name["meituan"]["active_jobs"] == 2, by_name
    assert by_name["bytedance"]["active_jobs"] == 0, by_name["bytedance"]

    # ---- Phase 5：投递记录（快照 + 状态机 + 时间线 + 统计 + 重复冲突） ----
    target = next(j for j in call("GET", "/api/jobs/shared", token=token)[1] if "服务端" in j["title"])
    status, created = call(
        "POST",
        "/api/applications",
        {"job_ref_type": "job_posting", "job_ref_id": target["id"], "note": "内推：老同事"},
        token=token,
    )
    print(f"[{'ok' if status == 201 else 'fail'}] apply {status} {created}")
    assert status == 201 and created["status"] == "applied", created
    assert created["company_name"] and created["title"] == target["title"], created
    assert created["days_since_update"] == 0 and created["is_stale"] is False, created

    status, dup = call(
        "POST",
        "/api/applications",
        {"job_ref_type": "job_posting", "job_ref_id": target["id"]},
        token=token,
    )
    print(f"[{'ok' if status == 409 else 'fail'}] duplicate apply {status}")
    assert status == 409 and dup["detail"]["application_id"] == created["id"], dup

    status, moved = call(
        "PATCH", f"/api/applications/{created['id']}", {"status": "interview", "note": "约了下周三"}, token=token
    )
    print(f"[{'ok' if status == 200 and moved['status'] == 'interview' else 'fail'}] transition {status} {moved}")
    assert status == 200 and moved["status"] == "interview", moved

    status, detail = call("GET", f"/api/applications/{created['id']}", token=token)
    tos = [e["to_status"] for e in detail.get("events") or []]
    print(f"[{'ok' if tos == ['applied', 'interview'] else 'fail'}] timeline {tos}")
    assert tos == ["applied", "interview"], detail

    status, blocked = call("PATCH", f"/api/applications/{created['id']}", {"status": "unknown"}, token=token)
    print(f"[{'ok' if status == 400 else 'fail'}] illegal status {status}")
    assert status == 400, blocked

    status, rows = call("GET", "/api/applications", token=token)
    assert status == 200 and len(rows) == 1 and rows[0]["id"] == created["id"], rows
    status, stats = call("GET", "/api/applications/stats", token=token)
    print(f"[info] application stats {json.dumps(stats, ensure_ascii=False)}")
    assert stats["total"] == 1 and stats["by_status"]["interview"] == 1 and stats["stale"] == 0, stats

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
