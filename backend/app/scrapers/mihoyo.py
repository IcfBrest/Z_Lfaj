"""米哈游招聘站点适配器（公开 ATS 接口，无签名、无登录态）。

实测（2026-11-12）：
- 列表：POST https://ats.openout.mihoyo.com/ats-portal/v1/job/list
  body {"pageNo":1,"pageSize":50,"channelDetailIds":[1],"hireType":0}
  返回 data.list[]（id/title/addressDetailList/competencyType/jobNature/tagList）与 data.total（670）。
- 详情：POST https://ats.openout.mihoyo.com/ats-portal/v1/job/info
  body 必须是 {"id":"<jobId>","channelDetailIds":[1,2]}；用 jobId/channelDetailId 字段会报
  "职位id不可为空" / "职位渠道不可以为空"。返回 description（职责）、jobRequire（要求）、addition（加分项）。
- 岗位页路由：#/position/<id>（前端 bundle 里 J_POSITION_ID: uid="/position/:id"）。
"""

from __future__ import annotations

from typing import Any

from .base import HttpClient, HttpError, JobRecord, clean_text, split_lines


class MihoyoSource:
    name = "mihoyo"
    company_name = "米哈游"
    career_url = "https://jobs.mihoyo.com/"

    def __init__(
        self,
        client: HttpClient | None = None,
        base_url: str | None = None,
        page_size: int = 50,
        channel_ids: tuple[int, ...] = (1,),
    ) -> None:
        self.client = client or HttpClient()
        self.base_url = (base_url or "https://ats.openout.mihoyo.com").rstrip("/")
        self.page_size = page_size
        self.channel_ids = tuple(channel_ids)
        self._headers = {
            "Origin": "https://jobs.mihoyo.com",
            "Referer": "https://jobs.mihoyo.com/",
        }

    # -- 抓取 ---------------------------------------------------------------
    def list_page(self, page_no: int) -> tuple[list[dict[str, Any]], int]:
        body = {
            "pageNo": page_no,
            "pageSize": self.page_size,
            "channelDetailIds": list(self.channel_ids),
            "hireType": 0,
        }
        data = self.client.fetch_json(
            "POST", f"{self.base_url}/ats-portal/v1/job/list", payload=body, headers=self._headers
        )
        if not data.get("success", True):
            raise HttpError(f"米哈游列表接口返回失败：{data.get('message') or data.get('code')}")
        payload = data.get("data") or {}
        return list(payload.get("list") or []), int(payload.get("total") or 0)

    def detail(self, external_id: str) -> dict[str, Any]:
        # 渠道 id 是必填项：只带 id 会被判"职位渠道不可以为空"
        body = {"id": str(external_id), "channelDetailIds": [1, 2]}
        data = self.client.fetch_json(
            "POST", f"{self.base_url}/ats-portal/v1/job/info", payload=body, headers=self._headers
        )
        if not data.get("success", True):
            raise HttpError(f"米哈游详情接口返回失败：{data.get('message') or data.get('code')}")
        return data.get("data") or {}

    # -- 归一化 -------------------------------------------------------------
    def normalize(self, item: dict[str, Any], detail: dict[str, Any] | None = None) -> JobRecord:
        merged: dict[str, Any] = {**item, **(detail or {})}
        external_id = str(merged.get("id") or "")
        locations = "、".join(
            clean_text(addr.get("addressDetail"))
            for addr in (merged.get("addressDetailList") or [])
            if clean_text(addr.get("addressDetail"))
        )
        tags = [clean_text(tag) for tag in (merged.get("tagList") or []) if clean_text(tag)]
        responsibilities = split_lines(merged.get("description"))
        requirements = split_lines(merged.get("jobRequire"))
        nice_to_have = split_lines(merged.get("addition"))
        raw_parts = [
            f"【职责】\n{chr(10).join(responsibilities)}" if responsibilities else "",
            f"【要求】\n{chr(10).join(requirements)}" if requirements else "",
            f"【加分项】\n{chr(10).join(nice_to_have)}" if nice_to_have else "",
        ]
        return JobRecord.build(
            external_id=external_id,
            title=merged.get("title"),
            location=locations or None,
            department=merged.get("competencyType"),
            employment_type=merged.get("jobNature"),
            # 米哈游公开接口不提供工作年限与学历门槛
            experience_required=None,
            education_required=None,
            skills=tags,
            responsibilities=responsibilities,
            requirements=requirements,
            nice_to_have=nice_to_have,
            description_raw="\n\n".join(part for part in raw_parts if part),
            source_url=f"{self.career_url}#/position/{external_id}" if external_id else None,
            source_type=self.name,
        )
