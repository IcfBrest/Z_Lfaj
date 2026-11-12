"""岗位采集测试：HTTP 客户端重试/限速、两站点归一化、同步幂等与下架、管理员 API。

全部离线：HttpClient 的 opener 与站点响应都在测试内打桩，不访问外网。
"""

import urllib.error

import pytest

from app.models import Company, JobPosting
from app.scrapers import base, bilibili, browser, bytedance, meituan, sync
from app.scrapers import sources as sources_mod
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
    resp = client.post("/api/admin/scrape", headers=admin_headers, json={"source": "zhipin"})
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


# ---------------------------------------------------------------- Phase 4：分页契约


class PagedSource(FakeSource):
    """只有 pages() 的适配器：模拟浏览器驱动站点（无法按页码随机取页）。"""

    def __init__(self, batches) -> None:
        super().__init__([], page_size=10)
        self.batches = batches
        self.calls: list[int | None] = []
        self.pages = self._pages  # 覆盖成可调用，iter_pages 会走自定义分支

    def _pages(self, limit=None):
        self.calls.append(limit)
        processed = 0
        for index, batch in enumerate(self.batches, start=1):
            yield index, batch, 0
            processed += len(batch)
            if limit is not None and processed >= limit:
                return

    def list_page(self, page_no):  # pragma: no cover - 自定义分页时不应被调用
        raise AssertionError("PagedSource 不应调用 list_page")


def test_iter_pages_falls_back_to_list_page():
    source = FakeSource(two_items(), page_size=2)
    pages = list(base.iter_pages(source))
    assert [page_no for page_no, _, _ in pages] == [1]
    assert pages[0][1] == two_items()


def test_iter_pages_uses_custom_generator():
    batches = [[{"id": str(index)} for index in range(3)] for _ in range(2)]
    source = PagedSource(batches)
    pages = list(base.iter_pages(source, limit=4))
    assert [page_no for page_no, _, _ in pages] == [1, 2]
    assert source.calls == [4]


def test_sync_limit_truncates_browser_pages(db):
    batches = [
        [{"id": f"{page}-{index}", "title": f"岗位{page}{index}", "body": "职责"} for index in range(3)]
        for page in range(3)
    ]
    source = PagedSource(batches)
    stats = sync.sync_jobs(db, source, limit=5, fetch_detail=False)
    assert stats["processed"] == 5 and stats["created"] == 5
    assert stats["deactivated"] == 0


# ---------------------------------------------------------------- Phase 4：字节跳动

BYTEDANCE_ITEM = {
    "id": "7700857347537586437",
    "title": "后端开发工程师（广告系统）",
    "description": "1、负责广告投放系统的服务端研发；\n2、参与系统性能优化。",
    "requirement": "1、本科及以上学历，计算机相关专业；\n2、熟悉 Go 或 C++。",
    "city_info": {"name": "上海"},
    "job_category": {"name": "研发"},
    "recruit_type": 1,
    "publish_time": 1792995763546,
}


def test_bytedance_extract_reads_list_and_total():
    data = {"data": {"job_post_list": [BYTEDANCE_ITEM], "count": 10000}}
    items, total = bytedance.extract(data)
    assert len(items) == 1 and total == 10000
    assert bytedance.extract({}) == ([], 0)


def test_bytedance_normalize_maps_fields():
    source = bytedance.BytedanceSource()
    record = source.normalize(BYTEDANCE_ITEM)
    assert record.external_id == "7700857347537586437"
    assert record.source_type == "bytedance"
    assert record.location == "上海"
    assert record.department == "研发"
    assert record.employment_type == "全职"
    assert record.responsibilities[0] == "负责广告投放系统的服务端研发；"
    assert record.requirements[0].startswith("本科及以上学历")
    assert record.source_url.endswith("/7700857347537586437/detail")
    assert "负责广告投放系统" in record.description_raw


def test_bytedance_normalize_falls_back_to_city_list():
    item = {**BYTEDANCE_ITEM, "city_info": {}, "city_list": [{"name": "北京"}, {"name": "深圳"}]}
    record = bytedance.BytedanceSource().normalize(item)
    assert record.location == "北京、深圳"


def test_bytedance_pages_delegates_to_collector():
    calls = []

    def fake_collector(config, list_url, max_pages, limit):
        calls.append((config, list_url, max_pages, limit))
        yield 1, [BYTEDANCE_ITEM], 1

    source = bytedance.BytedanceSource(
        collector=fake_collector, career_url="https://example.test/list", max_pages=5
    )
    pages = list(source.pages(limit=3))
    assert pages[0][0] == 1
    assert calls == [(source.config, "https://example.test/list", 5, 3)]


def test_bytedance_reports_browser_unavailable(monkeypatch):
    def boom(config):
        raise browser.BrowserUnavailable("未安装 playwright")

    monkeypatch.setattr(bytedance, "open_page", boom)
    with pytest.raises(browser.BrowserUnavailable):
        list(bytedance.collect_pages(browser.BrowserConfig()))


# ---------------------------------------------------------------- Phase 4：哔哩哔哩

BILIBILI_ITEM = {
    "id": 30953,
    "positionName": "海外业务风控算法工程师",
    "positionDescription": "工作职责:\n1.负责账号安全与营销风控算法建设；\n2.构建实时风控链路。\n任职要求:\n1.计算机相关专业硕士及以上；\n2.熟悉 LightGBM/PyTorch。",
    "workLocation": "上海",
    "postCodeName": "技术类",
    "positionTypeName": "全职",
    "recruitType": 0,
    "pushTime": "2026-11-11 17:42:21",
}


class SeqClient:
    """按顺序返回预设 JSON 的客户端（用于 csrf → list 这种两次请求的流程）。"""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[tuple] = []

    def fetch_json(self, method, url, *, payload=None, headers=None):  # noqa: ANN001
        self.calls.append((method, url, payload, headers))
        return self.responses.pop(0)


def bilibili_source(responses) -> tuple[bilibili.BilibiliSource, SeqClient]:
    client = SeqClient(responses)
    return bilibili.BilibiliSource(
        client=client, base_url="https://example.test", lunar_id="lunar-test"
    ), client


def test_bilibili_fetches_csrf_then_lists():
    source, client = bilibili_source(
        [
            {"code": 0, "data": "csrf-1"},
            {"code": 0, "data": {"list": [BILIBILI_ITEM], "pages": 1, "size": 50, "total": 1}},
        ]
    )
    items, total = source.list_page(1)

    assert (len(items), total) == (1, 1)
    method, url, payload, headers = client.calls[0]
    assert method == "GET" and url.endswith("/api/auth/v1/csrf/token")
    assert headers["x-appkey"] == "ops.ehr-api.auth" and "x-csrf" not in headers
    method, url, payload, headers = client.calls[1]
    assert method == "POST" and url.endswith("/api/srs/position/positionList")
    assert headers["x-csrf"] == "csrf-1" and headers["x-channel"] == "social"
    assert headers["lunar-id"] == "lunar-test"
    assert payload["pageSize"] == 50 and payload["pageNum"] == 1


def test_bilibili_refreshes_token_once_then_raises():
    source, client = bilibili_source(
        [
            {"code": 0, "data": "csrf-1"},
            {"code": -101, "message": "cj无效"},
            {"code": 0, "data": "csrf-2"},
            {"code": 0, "data": {"list": [BILIBILI_ITEM], "total": 1}},
        ]
    )
    items, _ = source.list_page(1)
    assert len(items) == 1
    assert [call[0] for call in client.calls] == ["GET", "POST", "GET", "POST"]
    assert client.calls[-1][3]["x-csrf"] == "csrf-2"

    source2, _ = bilibili_source(
        [{"code": 0, "data": "csrf-1"}, {"code": 500, "message": "服务异常"}]
    )
    with pytest.raises(base.HttpError):
        source2.list_page(1)


def test_bilibili_normalize_splits_sections():
    record = bilibili.BilibiliSource().normalize(BILIBILI_ITEM)
    assert record.external_id == "30953"
    assert record.source_type == "bilibili"
    assert record.location == "上海" and record.department == "技术类"
    assert record.employment_type == "全职"
    assert record.responsibilities[0] == "负责账号安全与营销风控算法建设；"
    assert record.requirements[0].startswith("计算机相关专业硕士及以上")
    assert record.source_url.endswith("/social/positions/30953")


# ---------------------------------------------------------------- Phase 4：美团

MEITUAN_ITEM = {
    "jobUnionId": "4697320043",
    "name": "AI全栈工程师",
    "jobFamily": "技术类",
    "jobFamilyGroup": "软件",
    "cityList": [{"name": "北京市"}, {"name": "上海市"}],
    "jobDuty": "岗位职责\n1. 参与 AI 应用的全栈开发；\n2. 参与大模型能力工程化。",
    "jobRequirement": "岗位要求\n1. 本科及以上学历；\n2. 熟悉 Python 或 Java。",
    "workYear": "3年以上",
}


def test_meituan_requests_body_and_normalizes():
    client = FakeClient({"data": {"list": [MEITUAN_ITEM], "page": {"totalCount": 3379}}})
    source = meituan.MeituanSource(client=client, base_url="https://example.test")
    items, total = source.list_page(2)

    assert (len(items), total) == (1, 3379)
    method, url, payload, headers = client.calls[0]
    assert method == "POST" and url.endswith("/api/official/job/getJobList")
    assert payload["page"] == {"pageNo": 2, "pageSize": 50}
    assert payload["jobShareType"] == "1" and payload["u_query_id"]
    assert headers["Origin"] == "https://example.test"

    record = source.normalize(MEITUAN_ITEM)
    assert record.external_id == "4697320043"
    assert record.location == "北京市、上海市"
    assert record.department == "软件"
    assert record.experience_required == "3年以上"
    assert record.responsibilities[0].startswith("参与 AI 应用的全栈开发")
    assert record.requirements[0].startswith("本科及以上学历")
    assert record.source_url == "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4697320043"


def test_meituan_rejects_unexpected_payload():
    source = meituan.MeituanSource(client=FakeClient({"message": "boom"}))
    with pytest.raises(base.HttpError):
        source.list_page(1)


# ---------------------------------------------------------------- Phase 4：注册表


def test_sources_registry_exposes_five_sites(client, admin_headers):
    sources = client.get("/api/admin/scrape/sources", headers=admin_headers).json()
    by_name = {item["source"]: item for item in sources}
    assert set(by_name) == set(sources_mod.SOURCE_NAMES) == {
        "mihoyo",
        "tencent",
        "bytedance",
        "bilibili",
        "meituan",
    }
    assert by_name["bytedance"]["mode"] == "browser"
    assert by_name["meituan"]["mode"] == "http"
    assert by_name["meituan"]["company"] == "美团"
