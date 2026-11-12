"""站点注册表：按名字取适配器，基址与限速从 Settings 读（冒烟可指向本地假站点）。"""

from __future__ import annotations

from ..config import get_settings
from .base import HttpClient, SourceAdapter
from .bilibili import BilibiliSource
from .browser import BrowserConfig
from .bytedance import BytedanceSource
from .meituan import MeituanSource
from .mihoyo import MihoyoSource
from .tencent import TencentSource

SOURCE_NAMES: tuple[str, ...] = ("mihoyo", "tencent", "bytedance", "bilibili", "meituan")


def get_source(name: str) -> SourceAdapter:
    settings = get_settings()
    client = HttpClient(
        timeout=float(settings.scraper_timeout_seconds),
        retries=int(settings.scraper_retries),
        min_interval=float(settings.scraper_min_interval),
    )
    if name == "mihoyo":
        return MihoyoSource(client=client, base_url=settings.mihoyo_base_url)
    if name == "tencent":
        return TencentSource(client=client, base_url=settings.tencent_base_url)
    if name == "bytedance":
        return BytedanceSource(
            config=BrowserConfig(
                channel=settings.scraper_browser_channel,
                headless=bool(settings.scraper_headless),
                timeout_ms=int(settings.scraper_browser_timeout_ms),
            ),
            career_url=settings.bytedance_list_url,
            max_pages=int(settings.scraper_max_pages),
        )
    if name == "bilibili":
        return BilibiliSource(client=client, base_url=settings.bilibili_base_url)
    if name == "meituan":
        return MeituanSource(client=client, base_url=settings.meituan_base_url)
    raise KeyError(f"未知采集站点：{name}（可用：{', '.join(SOURCE_NAMES)}）")
