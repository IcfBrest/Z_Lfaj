"""哔哩哔哩岗位采集：纯 HTTP + 一次性 csrf token。

站点要求 `x-csrf` + `lunar-id` + `x-appkey` 三个头；`x-csrf` 由
`GET /api/auth/v1/csrf/token` 下发（换 token 时要带 appkey 与 lunar-id）。
列表响应 `data.list[]` 已含完整正文（positionDescription），无需详情接口。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .base import HttpClient, HttpError, JobRecord, clean_text, split_lines, split_sections

LIST_API = "/api/srs/position/positionList"
CSRF_API = "/api/auth/v1/csrf/token"
DEFAULT_BASE_URL = "https://jobs.bilibili.com"
PAGE_SIZE = 50
APP_KEY = "ops.ehr-api.auth"

SECTION_MARKERS = ("工作职责", "岗位职责", "工作要求", "任职要求", "岗位要求", "加分项")
_BAD_CODES = (-101, -3, 401, 403)


def new_lunar_id() -> str:
    """lunar-id 是页面运行时生成的追踪 id，形状 lunar-<毫秒时间戳>-<随机数>。"""
    return f"lunar-{int(time.time() * 1000)}-{uuid.uuid4().int % 10**13}"


@dataclass
class BilibiliSource:
    name: str = "bilibili"
    company_name: str = "哔哩哔哩"
    career_url: str = f"{DEFAULT_BASE_URL}/social/positions"
    page_size: int = PAGE_SIZE
    base_url: str = DEFAULT_BASE_URL
    site_url: str = DEFAULT_BASE_URL
    client: HttpClient = field(default_factory=HttpClient)
    lunar_id: str = field(default_factory=new_lunar_id)
    _csrf: str | None = field(default=None, init=False, repr=False)

    # ---- 请求 ----

    def _headers(self, with_csrf: bool = True) -> dict[str, str]:
        headers = {
            "x-appkey": APP_KEY,
            "x-usertype": "2",
            "lunar-id": self.lunar_id,
            "x-channel": "social",
            "Referer": self.career_url,
            "Accept": "application/json, text/plain, */*",
        }
        if with_csrf and self._csrf:
            headers["x-csrf"] = self._csrf
        return headers

    def csrf_token(self) -> str:
        """取（并缓存）csrf token；token 失效时由调用方重新取。"""
        if self._csrf:
            return self._csrf
        data = self.client.fetch_json(
            "GET", f"{self.base_url}{CSRF_API}", headers=self._headers(with_csrf=False)
        )
        token = (data or {}).get("data")
        if not token:
            raise HttpError(f"哔哩哔哩 csrf token 获取失败：{data}")
        self._csrf = str(token)
        return self._csrf

    def refresh_csrf(self) -> str:
        self._csrf = None
        return self.csrf_token()

    def list_page(self, page_no: int) -> tuple[list[dict[str, Any]], int]:
        body = {
            "pageSize": self.page_size,
            "pageNum": page_no,
            "positionName": "",
            "postCode": [],
            "postCodeList": [],
            "workLocationList": [],
            "workTypeList": ["3"],
            "positionTypeList": ["3"],
            "deptCodeList": [],
            "recruitType": 0,
            "practiceTypes": [],
            "onlyHotRecruit": 0,
        }
        self.csrf_token()
        payload = self.client.fetch_json(
            "POST", f"{self.base_url}{LIST_API}", payload=body, headers=self._headers()
        )
        code = payload.get("code")
        if code in _BAD_CODES:
            # 常见于 token 过期：换一次 token 重试，仍失败就把错误抛给同步内核
            self.refresh_csrf()
            payload = self.client.fetch_json(
                "POST", f"{self.base_url}{LIST_API}", payload=body, headers=self._headers()
            )
            code = payload.get("code")
        if code != 0:
            raise HttpError(f"哔哩哔哩列表接口返回 code={code}：{payload.get('message')}")
        data = payload.get("data") or {}
        items = data.get("list") or []
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        return items, total

    def detail(self, external_id: str) -> dict[str, Any] | None:
        return None  # 列表已含正文

    # ---- 归一化 ----

    def normalize(self, item: dict[str, Any], detail: dict[str, Any] | None = None) -> JobRecord:
        text = str(item.get("positionDescription") or "")
        sections = split_sections(text, SECTION_MARKERS)
        responsibilities: list[str] = []
        requirements: list[str] = []
        nice_to_have: list[str] = []
        for marker, lines in sections.items():
            if marker in ("工作职责", "岗位职责"):
                responsibilities.extend(lines)
            elif marker in ("工作要求", "任职要求", "岗位要求"):
                requirements.extend(lines)
            elif marker == "加分项":
                nice_to_have.extend(lines)
            else:
                responsibilities.extend(lines)
        if not responsibilities and not requirements and text:
            responsibilities = split_lines(text)

        external_id = str(item.get("id") or "").strip()
        return JobRecord.build(
            external_id=external_id,
            title=item.get("positionName") or "",
            source_type=self.name,
            location=clean_text(item.get("workLocation")) or None,
            department=clean_text(item.get("postCodeName")) or None,
            employment_type=clean_text(item.get("positionTypeName")) or None,
            responsibilities=responsibilities,
            requirements=requirements,
            nice_to_have=nice_to_have,
            description_raw=text.strip(),
            source_url=f"{self.site_url}/social/positions/{external_id}" if external_id else None,
        )
