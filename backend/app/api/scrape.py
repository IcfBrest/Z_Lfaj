"""岗位采集 API（管理员）：触发站点同步、查看各站点规模与最近同步时间。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Company, JobPosting, User
from ..scrapers.runner import run_company_scrape
from ..scrapers.sources import SOURCE_NAMES, get_source
from ..task_runner import enqueue
from .deps import require_admin

router = APIRouter(prefix="/api/admin/scrape", tags=["scrape"])

MAX_LIMIT = 5000


class ScrapeIn(BaseModel):
    source: str = Field(min_length=1, max_length=32)
    limit: int | None = Field(default=None, ge=1, le=MAX_LIMIT)
    fetch_detail: bool = True


@router.post("", status_code=202)
def start_scrape(
    body: ScrapeIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    if body.source not in SOURCE_NAMES:
        raise HTTPException(status_code=400, detail=f"未知采集站点：{body.source}（可用：{'、'.join(SOURCE_NAMES)}）")
    task_id = enqueue(
        background_tasks,
        db,
        "company_scrape",
        user.id,
        run_company_scrape,
        "company",
        None,
        {"source": body.source, "limit": body.limit, "fetch_detail": body.fetch_detail},
    )
    return {"task_id": task_id, "source": body.source, "limit": body.limit, "fetch_detail": body.fetch_detail}


@router.get("/sources")
def list_sources(
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
) -> list[dict]:
    result: list[dict] = []
    for name in SOURCE_NAMES:
        source = get_source(name)
        company = db.query(Company).filter_by(name=source.company_name).one_or_none()
        total = active = 0
        last_scraped_at = None
        if company is not None:
            base = db.query(JobPosting).filter(
                JobPosting.company_id == company.id, JobPosting.source_type == name
            )
            total = base.count()
            active = base.filter(JobPosting.is_active.is_(True)).count()
            last_scraped_at = base.with_entities(func.max(JobPosting.scraped_at)).scalar()
        result.append(
            {
                "source": name,
                "company": source.company_name,
                "career_url": source.career_url,
                "active_jobs": active,
                "total_jobs": total,
                "last_scraped_at": last_scraped_at,
            }
        )
    return result
