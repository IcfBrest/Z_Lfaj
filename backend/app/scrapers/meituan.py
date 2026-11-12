"""美团岗位采集：明文 POST 接口，无需浏览器、无需签名。

`POST /api/official/job/getJobList` 的 body 结构固定，只改分页；响应里 `data.list[]`
已含 `jobDuty` / `jobRequirement` 全文，无需详情页。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .base import HttpClient, HttpError, JobRecord, clean_text, split_lines, split_sections

DEFAULT_BASE_URL = "https://zhaopin.meituan.com"
LIST_API = "/api/official/job/getJobList"
PAGE_SIZE = 50
DETAIL_URL = "https://zhaopin.meituan.com/web/position/detail?jobUnionId="
SECTION_MARKERS = ("岗位职责", "工作职责", "岗位要求", "任职要求", "任职资格", "职位描述", "加分项")


def new_query_id() -> str:
    return uuid.uuid4().hex


@dataclass
class MeituanSource:
    name: str = "meituan"
    company_name: str = "美团"
    career_url: str = f"{DEFAULT_BASE_URL}/web/position"
    page_size: int = PAGE_SIZE
    base_url: str = DEFAULT_BASE_URL
    client: HttpClient = field(default_factory=HttpClient)

    def list_page(self, page_no: int) -> tuple[list[dict[str, Any]], int]:
        body = {
            "page": {"pageNo": page_no, "pageSize": self.page_size},
            "jobShareType": "1",
            "keywords": "",
            "cityList": [],
            "department": [],
            "jfJgList": [],
            "jobType": [],
            "typeCode": [],
            "specialCode": [],
            "u_query_id": new_query_id(),
        }
        payload = self.client.fetch_json(
            "POST",
            f"{self.base_url}{LIST_API}",
            payload=body,
            headers={"Referer": self.career_url, "Origin": self.base_url},
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise HttpError(f"美团列表接口返回异常：{str(payload)[:200]}")
        items = data.get("list") or []
        page = data.get("page") or {}
        try:
            total = int(page.get("totalCount") or 0)
        except (TypeError, ValueError):
            total = 0
        return items, total

    def detail(self, external_id: str) -> dict[str, Any] | None:
        return None  # 列表已含正文

    def normalize(self, item: dict[str, Any], detail: dict[str, Any] | None = None) -> JobRecord:
        duty = str(item.get("jobDuty") or "")
        requirement = str(item.get("jobRequirement") or "")
        sections = split_sections("\n".join([duty, requirement]), SECTION_MARKERS)
        responsibilities: list[str] = []
        requirements: list[str] = []
        nice_to_have: list[str] = []
        unknown: list[str] = []
        for marker, lines in sections.items():
            if marker in ("岗位职责", "工作职责", "职位描述"):
                responsibilities.extend(lines)
            elif marker in ("岗位要求", "任职要求", "任职资格"):
                requirements.extend(lines)
            elif marker == "加分项":
                nice_to_have.extend(lines)
            else:
                unknown.extend(lines)
        if unknown:
            # 没有小标题（或标题写法变了）时，整段兜底当职责，至少有正文可看
            responsibilities = responsibilities or unknown

        cities = [clean_text((city or {}).get("name")) for city in item.get("cityList") or []]
        external_id = str(item.get("jobUnionId") or "").strip()
        return JobRecord.build(
            external_id=external_id,
            title=item.get("name") or "",
            source_type=self.name,
            location="、".join([city for city in cities if city]) or None,
            department=clean_text(item.get("jobFamilyGroup")) or clean_text(item.get("jobFamily")) or None,
            experience_required=clean_text(item.get("workYear")) or None,
            responsibilities=responsibilities,
            requirements=requirements,
            description_raw="\n\n".join(part for part in (duty.strip(), requirement.strip()) if part),
            source_url=f"{DETAIL_URL}{external_id}" if external_id else None,
        )
