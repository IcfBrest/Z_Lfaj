"""站点注册表：按名字取适配器，基址与限速从 Settings 读（冒烟可指向本地假站点）。"""

from __future__ import annotations

from ..config import get_settings
from .base import HttpClient, SourceAdapter
from .mihoyo import MihoyoSource
from .tencent import TencentSource

SOURCE_NAMES: tuple[str, ...] = ("mihoyo", "tencent")


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
    raise KeyError(f"未知采集站点：{name}（可用：{', '.join(SOURCE_NAMES)}）")
