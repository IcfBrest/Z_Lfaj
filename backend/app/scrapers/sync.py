"""采集同步内核：分页抓列表 → 逐条详情（可选）→ 按外部 id upsert → 整轮后下架。

约定：
- 去重键 `(company_id, source_type, external_id)`；手动导入的岗位 external_id 为 NULL，不参与。
- 内容哈希只覆盖会展示的字段（不含 source_url / scraped_at），避免路由或时间戳变化导致全量"更新"。
- 每 BATCH_COMMIT 条提交一次；单条详情失败只记 failed，不中断整轮。
- 只有未截断（limit is None）的完整一轮才会下架；下架范围严格限定该站点。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..models import Company, JobPosting, utcnow
from .base import HttpError, JobRecord, SourceAdapter

BATCH_COMMIT = 50
MAX_PAGES = 200
MAX_ERRORS = 5

# 参与内容哈希的字段：只含用户可见内容
HASH_FIELDS = (
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
)

Progress = Callable[[int, int, int], None]

# 落库字段 = 哈希字段 + 链接（source_url 参与落库但不参与哈希：路由变化不该算内容更新）
PERSIST_FIELDS = (*HASH_FIELDS, "source_url")


def record_hash(record: JobRecord) -> str:
    payload = {field: getattr(record, field) for field in HASH_FIELDS}
    dumped = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def get_or_create_company(db: Session, name: str, career_url: str | None) -> Company:
    company = db.query(Company).filter_by(name=name).one_or_none()
    if company is None:
        company = Company(name=name, career_url=career_url)
        db.add(company)
        db.flush()
    elif career_url and not company.career_url:
        company.career_url = career_url
    return company


def _remember(stats: dict[str, Any], message: str) -> None:
    errors: list[str] = stats["errors"]
    if len(errors) < MAX_ERRORS:
        errors.append(message)


def _upsert(db: Session, company: Company, record: JobRecord) -> tuple[str, JobPosting]:
    new_hash = record_hash(record)
    now = utcnow()
    job = (
        db.query(JobPosting)
        .filter_by(company_id=company.id, source_type=record.source_type, external_id=record.external_id)
        .one_or_none()
    )
    values = {field: getattr(record, field) for field in PERSIST_FIELDS}
    if job is None:
        job = JobPosting(
            company_id=company.id,
            source_type=record.source_type,
            external_id=record.external_id,
            content_hash=new_hash,
            is_active=True,
            scraped_at=now,
            created_at=now,
            **values,
        )
        db.add(job)
        db.flush()
        return "created", job

    job.scraped_at = now
    job.is_active = True
    if job.content_hash == new_hash:
        # 内容没变，但链接可能变（比如站点改了路由），顺手刷新
        job.source_url = values["source_url"]
        return "unchanged", job
    for field, value in values.items():
        setattr(job, field, value)
    job.content_hash = new_hash
    return "updated", job


def _deactivate_missing(db: Session, company: Company, source_type: str, seen_ids: set[int]) -> int:
    rows = (
        db.query(JobPosting)
        .filter(
            JobPosting.company_id == company.id,
            JobPosting.source_type == source_type,
            JobPosting.is_active.is_(True),
        )
        .all()
    )
    count = 0
    for row in rows:
        if row.id not in seen_ids:
            row.is_active = False
            count += 1
    return count


def sync_jobs(
    db: Session,
    source: SourceAdapter,
    *,
    limit: int | None = None,
    fetch_detail: bool = True,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """跑一轮同步；返回计数与失败样例（可直接放进 BackgroundTask.params["result"]）。"""
    stats: dict[str, Any] = {
        "source": source.name,
        "company": source.company_name,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "deactivated": 0,
        "failed": 0,
        "processed": 0,
        "total": 0,
        "errors": [],
    }
    company = get_or_create_company(db, source.company_name, source.career_url)
    db.commit()

    seen_ids: set[int] = set()
    processed = 0
    total = 0
    page_no = 1
    while page_no <= MAX_PAGES:
        items, total = source.list_page(page_no)
        if not items:
            break
        for item in items:
            if limit is not None and processed >= limit:
                break
            processed += 1
            external_id = str(item.get("id") or item.get("PostId") or "")
            try:
                detail = source.detail(external_id) if fetch_detail else None
                record = source.normalize(item, detail)
            except HttpError as exc:
                stats["failed"] += 1
                _remember(stats, f"{external_id}: {exc}")
                try:
                    # 详情失败时退回列表级数据：至少把岗位标题/城市存进去，下一轮再补正文
                    record = source.normalize(item, None)
                except Exception:  # noqa: BLE001 - 归一化失败就当这条跳过
                    continue
            if not record.external_id:
                stats["failed"] += 1
                _remember(stats, f"缺少外部 id 的条目：{record.title}")
                continue

            action, job = _upsert(db, company, record)
            stats[action] += 1
            seen_ids.add(job.id)
            if processed % BATCH_COMMIT == 0:
                db.commit()
                if progress is not None:
                    progress(processed, total or processed, page_no)
        if limit is not None and processed >= limit:
            break
        if len(items) < source.page_size:
            break
        if total and processed >= total:
            break
        page_no += 1

    db.commit()
    if limit is None and seen_ids:
        stats["deactivated"] = _deactivate_missing(db, company, source.name, seen_ids)
        db.commit()
    stats["processed"] = processed
    stats["total"] = total
    if progress is not None:
        progress(processed, total or processed, page_no)
    return stats
