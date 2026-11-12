"""岗位采集：站点适配器 + 同步内核。

入口：
- `sources.get_source("mihoyo" | "tencent" | "bytedance" | "bilibili" | "meituan")` 取适配器
- `sync.sync_jobs(db, source, limit=None, fetch_detail=True)` 跑一轮同步
- `runner.run_company_scrape` 是后台任务入口（由 API 入队）

Phase 3 的米哈游 / 腾讯走纯 HTTP（列表 + 详情）；Phase 4 的字节跳动走浏览器驱动，
哔哩哔哩与美团走纯 HTTP 且列表已含正文。
"""

from .base import HttpClient, HttpError, JobRecord, iter_pages
from .bilibili import BilibiliSource
from .browser import BrowserConfig, BrowserUnavailable, open_page
from .bytedance import BytedanceSource
from .meituan import MeituanSource
from .mihoyo import MihoyoSource
from .sources import SOURCE_NAMES, get_source
from .sync import sync_jobs
from .tencent import TencentSource

__all__ = [
    "SOURCE_NAMES",
    "BilibiliSource",
    "BrowserConfig",
    "BrowserUnavailable",
    "BytedanceSource",
    "HttpClient",
    "HttpError",
    "JobRecord",
    "MeituanSource",
    "MihoyoSource",
    "TencentSource",
    "get_source",
    "iter_pages",
    "open_page",
    "sync_jobs",
]
