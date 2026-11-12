"""岗位采集（Phase 3）：站点适配器 + 同步内核。

入口：
- `sources.get_source("mihoyo" | "tencent")` 取适配器
- `sync.sync_jobs(db, source, limit=None, fetch_detail=True)` 跑一轮同步
- `runner.run_company_scrape` 是后台任务入口（由 API 入队）
"""

from .base import HttpClient, HttpError, JobRecord
from .mihoyo import MihoyoSource
from .sources import SOURCE_NAMES, get_source
from .sync import sync_jobs
from .tencent import TencentSource

__all__ = [
    "SOURCE_NAMES",
    "HttpClient",
    "HttpError",
    "JobRecord",
    "MihoyoSource",
    "TencentSource",
    "get_source",
    "sync_jobs",
]
