"""浏览器驱动采集的最小封装：延迟导入 playwright，复用系统浏览器通道。

只有必须靠页面 JS 现算签名的站点（如字节跳动）才会走到这里。其余站点继续用
`base.HttpClient` 纯 HTTP 采集，因此服务器/CI 不装浏览器也不影响它们。
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

DEFAULT_CHANNEL = "msedge"
DEFAULT_VIEWPORT = {"width": 1440, "height": 1000}


class BrowserUnavailable(RuntimeError):
    """没有可用的 playwright 或浏览器内核，无法做浏览器驱动采集。"""


@dataclass
class BrowserConfig:
    channel: str = DEFAULT_CHANNEL
    headless: bool = True
    timeout_ms: int = 90_000
    viewport: dict[str, int] | None = None

    def as_viewport(self) -> dict[str, int]:
        return dict(self.viewport or DEFAULT_VIEWPORT)


@contextmanager
def open_page(config: BrowserConfig | None = None) -> Iterator[Any]:
    """打开一个页面，退出时关闭浏览器；缺依赖时抛 BrowserUnavailable。"""
    config = config or BrowserConfig()
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 - 延迟导入，缺依赖不影响其他站点
    except ImportError as exc:  # pragma: no cover - 视环境而定
        raise BrowserUnavailable(
            "未安装 playwright：请执行 pip install playwright（本项目直接复用系统 Edge，无需再下载浏览器）"
        ) from exc

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel=config.channel, headless=config.headless)
            except Exception as exc:  # noqa: BLE001 - 浏览器启动失败的原因很多，统一转成可读错误
                raise BrowserUnavailable(
                    f"浏览器启动失败（channel={config.channel}）：{exc}"
                ) from exc
            page = browser.new_page(viewport=config.as_viewport())
            page.set_default_timeout(config.timeout_ms)
            try:
                yield page
            finally:
                browser.close()
    except BrowserUnavailable:
        raise


def dismiss_overlays(page: Any, selector: str) -> None:
    """移除拦截点击的引导遮罩（站点首访的 AI 助手蒙层等）。"""
    if not selector:
        return
    page.evaluate(
        """(selector) => {
            document.querySelectorAll(selector).forEach((el) => el.remove());
        }""",
        selector,
    )
