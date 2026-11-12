"""字节跳动岗位采集：浏览器驱动。

为什么只能用浏览器：列表接口 `api/v1/search/job/posts` 带 `_signature`，签名由页面脚本
现算，直接 HTTP 请求会被拒。这里的做法是让真实页面自己发请求，我们只负责点翻页并
拦截 JSON 响应——不逆向对方的签名算法。

列表响应里已经包含职责（description）与要求（requirement）全文，所以不需要详情页。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .base import JobRecord, clean_text, split_lines
from .browser import BrowserConfig, dismiss_overlays, open_page

API_PATH = "api/v1/search/job/posts"
LIST_URL = "https://jobs.bytedance.com/experienced/position"
OVERLAY_SELECTOR = ".hire-ai-assistant-guide-cn-mask, .hire-ai-assistant-guide-cn-feature"
PAGER_SELECTOR = ".atsx-pagination-item"
DEFAULT_MAX_PAGES = 20
PAGE_SIZE = 10  # 站点固定每页 10 条，分页上限 1000 页

_EMPLOYMENT = {"1": "全职", "2": "实习"}

Pages = Iterator[tuple[int, list[dict[str, Any]], int]]


def extract(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """从列表接口响应里取出（岗位列表，站点声明的总数）。"""
    block = data.get("data") or {}
    items = block.get("job_post_list") or []
    try:
        total = int(block.get("count") or 0)
    except (TypeError, ValueError):
        total = 0
    return items, total


def _is_list_response(response: Any) -> bool:
    try:
        return API_PATH in response.url and response.status == 200
    except Exception:  # noqa: BLE001 - 关闭中的响应没有 url
        return False


def collect_pages(
    config: BrowserConfig,
    list_url: str = LIST_URL,
    max_pages: int = DEFAULT_MAX_PAGES,
    limit: int | None = None,
) -> Pages:
    """打开列表页，逐页点击分页并拦截接口响应，产出（页码、条目、总数）。"""
    with open_page(config) as page:
        with page.expect_response(_is_list_response) as first:
            page.goto(list_url, wait_until="domcontentloaded")
        payload = _load(first.value)
        items, total = extract(payload)
        if not items:
            return
        yield 1, items, total

        fetched = len(items)
        page_no = 2
        while page_no <= max_pages and (limit is None or fetched < limit):
            data = _click_page(page, page_no)
            if data is None:
                return
            items, total = extract(data)
            if not items:
                return
            yield page_no, items, total
            fetched += len(items)
            if total and fetched >= total:
                return
            page_no += 1


def _load(response: Any) -> dict[str, Any]:
    try:
        return response.json()
    except Exception:  # noqa: BLE001 - 响应体不是 JSON 时按空处理
        return {}


def _click_page(page: Any, page_no: int) -> dict[str, Any] | None:
    """点第 page_no 页；找不到分页项或请求失败时返回 None（本轮到此为止）。"""
    dismiss_overlays(page, OVERLAY_SELECTOR)
    label = re.compile(rf"^\s*{page_no}\s*$")
    candidate = page.locator(f"{PAGER_SELECTOR}[title='{page_no}']")
    if candidate.count() == 0:
        candidate = page.locator(PAGER_SELECTOR).filter(has_text=label)
    if candidate.count() == 0:
        return None
    try:
        with page.expect_response(_is_list_response) as info:
            candidate.first.evaluate("el => el.click()")
        return _load(info.value)
    except Exception:  # noqa: BLE001 - 超时/元素失效都视为翻页结束
        return None


@dataclass
class BytedanceSource:
    name: str = "bytedance"
    company_name: str = "字节跳动"
    career_url: str = LIST_URL
    page_size: int = PAGE_SIZE
    config: BrowserConfig = field(default_factory=BrowserConfig)
    max_pages: int = DEFAULT_MAX_PAGES
    # 采集实现可注入：单测用它替换掉真实浏览器
    collector: Callable[..., Pages] = collect_pages

    def pages(self, limit: int | None = None) -> Pages:
        return self.collector(self.config, self.career_url, self.max_pages, limit)

    def list_page(self, page_no: int) -> tuple[list[dict[str, Any]], int]:
        raise NotImplementedError("字节跳动站点只支持浏览器驱动分页，请走 pages()")

    def detail(self, external_id: str) -> dict[str, Any] | None:
        return None  # 列表已含正文

    def normalize(self, item: dict[str, Any], detail: dict[str, Any] | None = None) -> JobRecord:
        city_info = item.get("city_info") or {}
        location = clean_text(city_info.get("name"))
        if not location:
            names = [clean_text((city or {}).get("name")) for city in item.get("city_list") or []]
            location = "、".join([name for name in names if name])
        category = item.get("job_category") or {}
        description = item.get("description") or ""
        requirement = item.get("requirement") or ""
        employment = _EMPLOYMENT.get(str(item.get("recruit_type") or "").strip())
        external_id = str(item.get("id") or "").strip()
        return JobRecord.build(
            external_id=external_id,
            title=item.get("title") or "",
            source_type=self.name,
            location=location or None,
            department=clean_text(category.get("name")) or None,
            employment_type=employment,
            responsibilities=split_lines(description),
            requirements=split_lines(requirement),
            description_raw="\n\n".join(
                part for part in (clean_text(description), clean_text(requirement)) if part
            ),
            source_url=(
                f"https://jobs.bytedance.com/experienced/position/{external_id}/detail"
                if external_id
                else None
            ),
        )
