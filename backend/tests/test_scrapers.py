"""岗位采集测试：HTTP 客户端重试/限速、两站点归一化、同步幂等与下架、管理员 API。

全部离线：HttpClient 的 opener 与站点响应都在测试内打桩，不访问外网。
"""

import urllib.error

import pytest

from app.models import Company, JobPosting
from app.scrapers import base, sync
from app.scrapers.mihoyo import MihoyoSource
from app.scrapers.tencent import TencentSource, normalize_years

MIHOYO_ITEM = {
    "id": "6658",
    "title": "服务端开发工程师（开放世界）",
    "addressDetailList": [{"addressDetail": "上海"}, {"addressDetail": "新加坡"}],
    "competencyType": "程序技术",
    "jobNature": "全职",
    "tagList": ["Python", "C++"],
    "jobSummary": "负责服务端逻辑开发。",
}

MIHOYO_DETAIL = {
    "id": "6658",
    "title": "服务端开发工程师（开放世界）",
    "description": "1、负责游戏服务端模块设计与开发；\n2、优化服务器性能。",
    "jobRequire": "1、本科及以上学历；\n2、三年以上 C++ 开发经验。",
    "addition": "有大型 MMO 经验者优先。",
}

TENCENT_ITEM = {
    "PostId": "123456",
    "RecruitPostName": "后台开发工程师",
    "LocationName": "深圳",
    "BGName": "CSIG",
    "CategoryName": "技术",
    "Responsibility": "负责后台服务开发；",
    "RequireWorkYearsName": "三年以上工作经验",
    "PostURL": "http://careers.tencent.com/jobdesc.html?postId=123456",
    "LastUpdateTime": "2026-11-01 10:00:00",
}

TENCENT_DETAIL = {
    "PostId": "123456",
    "Requirement": "1、熟悉 C++ 或 Go；\n2、有高并发经验。",
    "Responsibility": "负责后台服务开发；",
    "PostURL": "http://careers.tencent.com/jobdesc.html?postId=123456",
}


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info) -> None:
        return None


class FakeOpener:
    """按顺序返回预设结果的 opener：元素是 bytes 或异常实例。"""

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests = []

    def open(self, request, timeout=None):  # noqa: ANN001 - 与 urllib 签名对齐
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else b"{}"
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://example.test", code, "boom", {}, None)


def make_client(outcomes, **kwargs) -> tuple[base.HttpClient, FakeOpener, list[float]]:
    sleeps: list[float] = []
    client = base.HttpClient(min_interval=0, sleep=sleeps.append, **kwargs)
    opener = FakeOpener(outcomes)
    client._opener = opener
    return client, opener, sleeps


class FakeClient:
    """站点适配器测试用：返回固定 JSON 并记录请求。"""

    def __init__(self, response, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple] = []

    def fetch_json(self, method, url, *, payload=None, headers=None):  # noqa: ANN001
        self.calls.append((method, url, payload, headers))
        if self.error is not None:
            raise self.error
        return self.response


# ---------------------------------------------------------------- 客户端


def test_http_client_retries_on_500_then_succeeds():
    client, opener, sleeps = make_client([http_error(500), b'{"ok":true}'], retries=1)
    assert client.fetch_json("GET", "http://example.test/x") == {"ok": True}
    assert len(opener.requests) == 2
    assert client.calls == 2
    assert sleeps == [1]  # 第一次退避 2**0


def test_http_client_does_not_retry_4xx():
    client, opener, _ = make_client([http_error(404), b"{}"], retries=2)
    with pytest.raises(base.HttpError):
        client.fetch_json("GET", "http://example.test/x")
    assert len(opener.requests) == 1


def test_http_client_gives_up_after_retries():
    client, opener, sleeps = make_client([http_error(503), http_error(503)], retries=1)
    with pytest.raises(base.HttpError):
        client.fetch_json("GET", "http://example.test/x")
    assert len(opener.requests) == 2
    assert sleeps == [1]


def test_http_client_throttles_between_requests():
    client = base.HttpClient(min_interval=1.0, sleep=lambda _s: None)
    client._opener = FakeOpener([b"{}", b"{}"])
    slept: list[float] = []
    client.sleep = slept.append
    client.fetch_json("GET", "http://example.test/a")
    assert slept == []  # 首次不受限
    client.fetch_json("GET", "http://example.test/b")
    assert len(slept) == 1 and 0 < slept[0] <= 1.0


def test_split_lines_strips_numbering_and_bullets():
    assert base.split_lines("1、甲；\n2、乙。") == ["甲；", "乙。"]
    assert base.split_lines("- 丙\n• 丁") == ["丙", "丁"]
    assert base.split_lines("") == []
    assert base.split_lines(None) == []


def test_record_hash_ignores_source_url_and_scraped_fields():
    first = base.JobRecord.build(external_id="1", title="岗位", source_type="mihoyo", source_url="http://a")
    second = base.JobRecord.build(external_id="1", title="岗位", source_type="mihoyo", source_url="http://b")
    changed = base.JobRecord.build(external_id="1", title="岗位改", source_type="mihoyo", source_url="http://a")
    assert sync.record_hash(first) == sync.record_hash(second)
    assert sync.record_hash(first) != sync.record_hash(changed)


# ---------------------------------------------------------------- 站点归一化


def test_mihoyo_normalize_merges_detail():
    source = MihoyoSource(client=FakeClient({}))
    record = source.normalize(MIHOYO_ITEM, MIHOYO_DETAIL)

    assert record.external_id == "6658"
    assert record.source_type == "mihoyo"
    assert record.location == "上海、新加坡"
    assert record.department == "程序技术"
    assert record.employment_type == "全职"
    assert record.skills == ["Python", "C++"]
    assert record.responsibilities[0] == "负责游戏服务端模块设计与开发；"
    assert record.requirements[0] == "本科及以上学历；"
    assert record.nice_to_have == ["有大型 MMO 经验者优先。"]
    assert "【职责】" in record.description_raw and "【要求】" in record.description_raw
    assert record.source_url == "https://jobs.mihoyo.com/#/position/6658"


def test_mihoyo_requests_use_required_body_fields():
    client = FakeClient({"success": True, "data": {"list": [MIHOYO_ITEM], "total": 670}})
    source = MihoyoSource(client=client, base_url="http://stub.local/")
    items, total = source.list_page(2)

    assert (len(items), total) == (1, 670)
    method, url, payload, headers = client.calls[0]
    assert method == "POST" and url == "http://stub.local/ats-portal/v1/job/list"
    assert payload == {"pageNo": 2, "pageSize": 50, "channelDetailIds": [1], "hireType": 0}
    assert headers["Origin"] == "https://jobs.mihoyo.com"

    client.response = {"success": True, "data": MIHOYO_DETAIL}
    source.detail("6658")
    assert client.calls[1][2] == {"id": "6658", "channelDetailIds": [1, 2]}


def test_mihoyo_failed_envelope_raises():
    source = MihoyoSource(client=FakeClient({"success": False, "message": "限流"}))
    with pytest.raises(base.HttpError):
        source.list_page(1)


def test_tencent_normalize_and_year_conversion():
    source = TencentSource(client=FakeClient({}))
    record = source.normalize(TENCENT_ITEM, TENCENT_DETAIL)

    assert record.external_id == "123456"
    assert record.title == "后台开发工程师"
    assert record.location == "深圳"
    assert record.department == "CSIG"
    assert record.experience_required == "3年以上工作经验"
    assert record.requirements == ["熟悉 C++ 或 Go；", "有高并发经验。"]
    assert record.source_url.startswith("https://")
    assert "【要求】" in record.description_raw


def test_normalize_years_handles_chinese_numbers():
    assert normalize_years("三年以上工作经验") == "3年以上工作经验"
    assert normalize_years("十年以上工作经验") == "10年以上工作经验"
    assert normalize_years("二十五年工作经验") == "25年工作经验"
    assert normalize_years("不限") == "不限"
    assert normalize_years(None) is None


def test_tencent_list_uses_query_parameters():
    client = FakeClient({"Code": 200, "Data": {"Posts": [TENCENT_ITEM], "Count": 2168}})
    source = TencentSource(client=client, base_url="http://stub.local/api/")
    items, total = source.list_page(3)

    assert (len(items), total) == (1, 2168)
    method, url, payload, _ = client.calls[0]
    assert method == "GET" and url.startswith("http://stub.local/api/post/Query?")
    assert "pageIndex=3" in url and "pageSize=50" in url

    client.response = {"Code": 500, "Message": "bad"}
    with pytest.raises(base.HttpError):
        source.detail("123456")


# ---------------------------------------------------------------- 同步内核


class FakeSource:
    name = "mihoyo"
    company_name = "米哈游"
    career_url = "https://jobs.mihoyo.com/"

    def __init__(self, items, *, page_size=2, details=None, fail_detail=()) -> None:
        self.pages = [items]
        self.page_size = page_size
        self.details = details or {}
        self.fail_detail = set(fail_detail)
        self.detail_calls: list[str] = []

    def list_page(self, page_no):
        index = page_no - 1
        items = self.pages[index] if index < len(self.pages) else []
        return items, sum(len(page) for page in self.pages)

    def detail(self, external_id):
        self.detail_calls.append(external_id)
        if external_id in self.fail_detail:
            raise base.HttpError("详情超时")
        return self.details.get(external_id, {})

    def normalize(self, item, detail=None):
        merged = {**item, **(detail or {})}
        return base.JobRecord.build(
            external_id=str(merged["id"]),
            title=merged["title"],
            source_type=self.name,
            location=merged.get("city"),
            description_raw=merged.get("body", ""),
            source_url=merged.get("url"),
        )


def two_items():
    return [
        {"id": "1", "title": "后端工程师", "city": "上海", "body": "负责服务端"},
        {"id": "2", "title": "客户端工程师", "city": "北京", "body": "负责客户端"},
    ]


def test_sync_is_idempotent_and_detects_changes(db):
    source = FakeSource(two_items(), page_size=2)

    first = sync.sync_jobs(db, source, fetch_detail=False)
    assert (first["created"], first["updated"], first["unchanged"], first["failed"]) == (2, 0, 0, 0)
    assert db.query(Company).count() == 1
    assert db.query(JobPosting).count() == 2

    second = sync.sync_jobs(db, source, fetch_detail=False)
    assert (second["created"], second["updated"], second["unchanged"]) == (0, 0, 2)
    assert db.query(JobPosting).count() == 2

    source.pages = [[{"id": "1", "title": "高级后端工程师", "city": "上海", "body": "负责服务端"},
                     {"id": "2", "title": "客户端工程师", "city": "北京", "body": "负责客户端"}]]
    third = sync.sync_jobs(db, source, fetch_detail=False)
    assert (third["created"], third["updated"], third["unchanged"]) == (0, 1, 1)
    job = db.query(JobPosting).filter_by(external_id="1").one()
    assert job.title == "高级后端工程师"
    assert job.source_type == "mihoyo" and job.is_active is True


def test_sync_deactivates_missing_only_on_complete_run(db):
    source = FakeSource(two_items(), page_size=2)
    sync.sync_jobs(db, source, fetch_detail=False)

    source.pages = [[{"id": "1", "title": "后端工程师", "city": "上海", "body": "负责服务端"}]]
    result = sync.sync_jobs(db, source, fetch_detail=False)
    assert result["deactivated"] == 1
    gone = db.query(JobPosting).filter_by(external_id="2").one()
    assert gone.is_active is False

    # 重新出现后复活
    source.pages = [two_items()]
    sync.sync_jobs(db, source, fetch_detail=False)
    assert db.query(JobPosting).filter_by(external_id="2").one().is_active is True

    # 截断运行（limit）不下架
    source.pages = [[{"id": "1", "title": "后端工程师", "city": "上海", "body": "负责服务端"}]]
    limited = sync.sync_jobs(db, source, limit=1, fetch_detail=False)
    assert limited["deactivated"] == 0
    assert db.query(JobPosting).filter_by(external_id="2").one().is_active is True


def test_sync_persists_source_url_and_refreshes_it(db):
    source = FakeSource([{"id": "1", "title": "后端", "url": "https://a/1"}], page_size=2)
    sync.sync_jobs(db, source, fetch_detail=False)
    job = db.query(JobPosting).filter_by(external_id="1").one()
    assert job.source_url == "https://a/1"

    # 链接变了但内容没变：算 unchanged，同时刷新链接
    source.pages = [[{"id": "1", "title": "后端", "url": "https://b/1"}]]
    stats = sync.sync_jobs(db, source, fetch_detail=False)
    assert stats["unchanged"] == 1 and stats["updated"] == 0
    db.refresh(job)
    assert job.source_url == "https://b/1"


def test_sync_detail_failure_keeps_list_level_data(db):
    source = FakeSource(two_items(), page_size=2, fail_detail={"2"})
    stats = sync.sync_jobs(db, source, fetch_detail=True)

    assert stats["failed"] == 1
    assert stats["errors"] and "详情超时" in stats["errors"][0]
    assert stats["created"] == 2  # 详情失败退回列表级数据，岗位不丢
    assert db.query(JobPosting).filter_by(external_id="2").one().title == "客户端工程师"


# ---------------------------------------------------------------- 管理员 API


def test_scrape_api_requires_admin(client, user_headers):
    assert client.get("/api/admin/scrape/sources").status_code == 401  # 未登录
    assert client.get("/api/admin/scrape/sources", headers=user_headers).status_code == 403
    assert client.post("/api/admin/scrape", headers=user_headers, json={"source": "mihoyo"}).status_code == 403


def test_scrape_api_rejects_unknown_source(client, admin_headers):
    resp = client.post("/api/admin/scrape", headers=admin_headers, json={"source": "bytedance"})
    assert resp.status_code == 400
    assert "mihoyo" in resp.json()["detail"]


def test_scrape_api_runs_task_and_reports_counts(client, admin_headers, monkeypatch):
    import time

    import app.scrapers.runner as runner

    source = FakeSource(two_items(), page_size=2)
    monkeypatch.setattr(runner, "get_source", lambda name: source)

    resp = client.post("/api/admin/scrape", headers=admin_headers, json={"source": "mihoyo"})
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    deadline = time.time() + 5
    task = {}
    while time.time() < deadline:
        task = client.get(f"/api/tasks/{task_id}", headers=admin_headers).json()
        if task["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert task["status"] == "done", task.get("error")
    assert task["result"]["created"] == 2
    assert task["result"]["company"] == "米哈游"

    sources = client.get("/api/admin/scrape/sources", headers=admin_headers).json()
    mihoyo = next(item for item in sources if item["source"] == "mihoyo")
    assert mihoyo["active_jobs"] == 2 and mihoyo["total_jobs"] == 2
    assert mihoyo["last_scraped_at"] is not None
    tencent = next(item for item in sources if item["source"] == "tencent")
    assert tencent["active_jobs"] == 0
