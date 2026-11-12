"""腾讯招聘站点适配器（公开接口，无签名、无登录态）。

实测（2026-11-12）：
- 列表：GET https://careers.tencent.com/tencentcareer/api/post/Query
  ?keyword=&pageIndex=1&pageSize=50&language=zh-cn&area=cn
  返回 Data.Count（2168）与 Data.Posts[]（PostId/RecruitPostName/LocationName/CategoryName/
  BGName/Responsibility/RequireWorkYearsName/PostURL/LastUpdateTime）。
- 详情：GET .../post/ByPostId?postId=<id>&language=zh-cn
  返回 Data.Requirement（要求全文）、Data.Responsibility、Data.PostURL。
- 工作年限是中文（"三年以上工作经验"），而筛选器按阿拉伯数字解析，这里统一转成 "3年以上工作经验"。
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .base import HttpClient, HttpError, JobRecord, clean_text, split_lines

_CN_DIGITS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 抓"三年/十年/二十五年"这类紧跟在"年"前面的中文数字
_CN_YEARS = re.compile(r"([一二两三四五六七八九十]+)\s*年")


def _cn_number(text: str) -> int | None:
    """把"三"、"十二"、"二十"、"二十五"这类中文数字转成整数；无法识别返回 None。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" not in text:
        return _CN_DIGITS.get(text)
    head, _, tail = text.partition("十")
    tens = _CN_DIGITS.get(head, 1) if head else 1
    ones = _CN_DIGITS.get(tail, 0) if tail else 0
    return tens * 10 + ones


def normalize_years(text: Any) -> str | None:
    """把"三年以上工作经验"归一成"3年以上工作经验"（筛选器只认阿拉伯数字）。"""
    raw = clean_text(text)
    if not raw:
        return None
    match = _CN_YEARS.search(raw)
    if match is None:
        return raw
    number = _cn_number(match.group(1))
    if number is None:
        return raw
    return f"{raw[:match.start(1)]}{number}{raw[match.end(1):]}"


class TencentSource:
    name = "tencent"
    company_name = "腾讯"
    career_url = "https://careers.tencent.com/"

    def __init__(
        self,
        client: HttpClient | None = None,
        base_url: str | None = None,
        page_size: int = 50,
        language: str = "zh-cn",
        area: str = "cn",
    ) -> None:
        self.client = client or HttpClient()
        self.base_url = (base_url or "https://careers.tencent.com/tencentcareer/api").rstrip("/")
        self.page_size = page_size
        self.language = language
        self.area = area

    # -- 抓取 ---------------------------------------------------------------
    def list_page(self, page_no: int) -> tuple[list[dict[str, Any]], int]:
        query = urllib.parse.urlencode(
            {
                "keyword": "",
                "pageIndex": page_no,
                "pageSize": self.page_size,
                "language": self.language,
                "area": self.area,
            }
        )
        data = self.client.fetch_json("GET", f"{self.base_url}/post/Query?{query}")
        if int(data.get("Code") or 0) != 200:
            raise HttpError(f"腾讯列表接口返回失败：{data.get('Code')} {data.get('Message') or ''}".strip())
        payload = data.get("Data") or {}
        return list(payload.get("Posts") or []), int(payload.get("Count") or 0)

    def detail(self, external_id: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"postId": str(external_id), "language": self.language})
        data = self.client.fetch_json("GET", f"{self.base_url}/post/ByPostId?{query}")
        if int(data.get("Code") or 0) != 200:
            raise HttpError(f"腾讯详情接口返回失败：{data.get('Code')}")
        return data.get("Data") or {}

    # -- 归一化 -------------------------------------------------------------
    def normalize(self, item: dict[str, Any], detail: dict[str, Any] | None = None) -> JobRecord:
        merged: dict[str, Any] = {**item, **(detail or {})}
        external_id = str(merged.get("PostId") or "")
        responsibilities = split_lines(merged.get("Responsibility"))
        requirements = split_lines(merged.get("Requirement"))
        raw_parts = [
            f"【职责】\n{chr(10).join(responsibilities)}" if responsibilities else "",
            f"【要求】\n{chr(10).join(requirements)}" if requirements else "",
        ]
        url = clean_text(merged.get("PostURL")) or None
        if url and url.startswith("http://"):
            url = "https://" + url[len("http://") :]
        return JobRecord.build(
            external_id=external_id,
            title=merged.get("RecruitPostName"),
            location=merged.get("LocationName"),
            department=merged.get("BGName") or merged.get("CategoryName"),
            employment_type=None,
            experience_required=normalize_years(merged.get("RequireWorkYearsName")),
            education_required=None,
            skills=[],
            responsibilities=responsibilities,
            requirements=requirements,
            nice_to_have=[],
            description_raw="\n\n".join(part for part in raw_parts if part),
            source_url=url,
            source_type=self.name,
        )
