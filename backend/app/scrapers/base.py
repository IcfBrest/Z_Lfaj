"""岗位采集的最小 HTTP 客户端：标准库 urllib + 显式绕过系统代理 + 限速 + 重试。

为什么不用 requests/httpx：项目其余部分只依赖标准库出站（LLM 走 litellm），
采集是低频后台任务，没必要为此新增依赖；同时 urllib 的 ProxyHandler({}) 能稳定
绕过 Windows 注册表里的系统代理（本机 127.0.0.1:29290 关闭后会直接连接失败）。
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 采集记录里参与内容哈希与落库的字段（顺序无关，哈希按 key 排序）
RECORD_FIELDS = (
    "title",
    "location",
    "department",
    "employment_type",
    "experience_required",
    "education_required",
    "skills",
    "responsibilities",
    "requirements",
    "nice_to_have",
    "description_raw",
    "source_url",
    "source_type",
)

# 详情页项目符号：用于把"- xxx"拆成纯文本条目（strip 的参数必须是字符串，不是元组）
_BULLETS = "-•·*"


class HttpError(RuntimeError):
    """采集请求在重试之后仍然失败。"""


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def split_lines(text: Any) -> list[str]:
    """把"1、xxx\\n2、yyy"这类职责/要求正文拆成条目；无换行时整体作为一条。"""
    if text is None:
        return []
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
    items: list[str] = []
    for line in raw.split("\n"):
        line = line.strip().strip(_BULLETS).strip()
        if not line:
            continue
        # 去掉行首的 "1、" "1." "（1）" "(1)" "1)" 之类序号
        digits = 0
        while digits < len(line) and line[digits].isdigit():
            digits += 1
        if digits:
            rest = line[digits:].lstrip("、.．)）:： 　")
            if rest:
                line = rest
        items.append(line)
    return items


def split_sections(text: Any, markers: Iterable[str]) -> dict[str, list[str]]:
    """把「工作职责：…\\n任职要求：…」这类整段正文按小标题切成多段条目。

    返回 {小标题: 条目列表}，未命中任何小标题时返回 {"": split_lines(text)}，
    调用方据此决定把整段当职责还是要求。
    """
    if text is None:
        return {}
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
    hits = sorted(
        ((raw.find(marker), marker) for marker in markers if raw.find(marker) >= 0),
        key=lambda pair: pair[0],
    )
    if not hits:
        return {"": split_lines(raw)}
    sections: dict[str, list[str]] = {}
    for index, (position, marker) in enumerate(hits):
        end = hits[index + 1][0] if index + 1 < len(hits) else len(raw)
        body = raw[position + len(marker) : end]
        sections[marker] = split_lines(body.lstrip(":： \n"))
    return sections


@dataclass
class JobRecord:
    external_id: str
    title: str
    source_type: str
    location: str | None = None
    department: str | None = None
    employment_type: str | None = None
    experience_required: str | None = None
    education_required: str | None = None
    skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    description_raw: str = ""
    source_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in ("external_id", *RECORD_FIELDS)}

    @classmethod
    def build(cls, **kwargs: Any) -> "JobRecord":
        """只保留已知字段，列表字段去 None/空串，避免脏数据进 JSON 列。"""
        known = {f for f in RECORD_FIELDS} | {"external_id"}
        payload = {k: v for k, v in kwargs.items() if k in known}
        for key in ("skills", "responsibilities", "requirements", "nice_to_have"):
            value = payload.get(key) or []
            payload[key] = [clean_text(item) for item in value if clean_text(item)]
        for key in ("location", "department", "employment_type", "experience_required", "education_required", "source_url"):
            if key in payload:
                payload[key] = clean_text(payload[key]) or None
        payload["title"] = clean_text(payload.get("title")) or "未命名岗位"
        payload["description_raw"] = str(payload.get("description_raw") or "").strip()
        payload["external_id"] = str(payload.get("external_id") or "").strip()
        return cls(**payload)


@dataclass
class HttpClient:
    """带最小间隔限速与退避重试的 JSON 客户端；实例可复用以在整轮采集中保持限速状态。"""

    timeout: float = 20.0
    retries: int = 2
    min_interval: float = 1.0
    sleep: Callable[[float], None] = time.sleep
    user_agent: str = DEFAULT_USER_AGENT
    _last_call: float = 0.0
    calls: int = 0

    def __post_init__(self) -> None:
        # 带上 cookie jar：部分站点（如哔哩哔哩）会在换取 csrf 时下发 buvid 类 cookie，
        # 后续请求带上更接近真实浏览器行为。
        self._cookies = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self._cookies),
        )

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        waited = time.monotonic() - self._last_call
        if waited < self.min_interval:
            self.sleep(self.min_interval - waited)

    def fetch_json(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = None
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle()
            request = urllib.request.Request(url, data=body, headers=request_headers, method=method.upper())
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    self._last_call = time.monotonic()
                    self.calls += 1
                    raw = response.read()
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:  # 4xx 不重试，5xx/429 重试
                self._last_call = time.monotonic()
                self.calls += 1
                last_error = exc
                if exc.code < 500 and exc.code != 429:
                    raise HttpError(f"HTTP {exc.code}: {url}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self._last_call = time.monotonic()
                self.calls += 1
                last_error = exc
            except json.JSONDecodeError as exc:
                self._last_call = time.monotonic()
                self.calls += 1
                last_error = exc
            if attempt < self.retries:
                self.sleep(min(2 ** attempt, 4))
        raise HttpError(f"请求失败（重试 {self.retries} 次后）：{url}：{last_error}")


class SourceAdapter(Protocol):
    """采集站点适配器：翻列表、抓详情、把原始响应归一化成 JobRecord。"""

    name: str
    company_name: str
    career_url: str
    page_size: int

    def list_page(self, page_no: int) -> tuple[list[dict[str, Any]], int]:
        """返回（本条页原始条目列表，站点声明的总条数）。"""

    def detail(self, external_id: str) -> dict[str, Any]:
        """返回详情原始 JSON（归一化在 normalize 里做）。"""

    def normalize(self, item: dict[str, Any], detail: dict[str, Any] | None = None) -> JobRecord:
        """把列表条目（可合并详情）转成统一记录。"""


def iter_pages(
    source: SourceAdapter,
    limit: int | None = None,
    *,
    max_pages: int = 200,
) -> Iterator[tuple[int, list[dict[str, Any]], int]]:
    """统一的分页迭代器，产出（页码、本页条目、站点声明的总条数）。

    适配器可以自定义 `pages(limit)`（例如浏览器驱动站点必须在同一个会话里连续翻页），
    否则按 `list_page(page_no)` 逐页取，行为与 Phase 3 的内联循环完全一致。
    """
    custom = getattr(source, "pages", None)
    if callable(custom):
        yield from custom(limit)
        return

    page_no = 1
    while page_no <= max_pages:
        items, total = source.list_page(page_no)
        if not items:
            return
        yield page_no, items, total
        if len(items) < source.page_size:
            return
        if total and page_no * len(items) >= total:
            return
        page_no += 1
