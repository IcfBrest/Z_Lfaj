from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Company, User
from .deps import get_current_user, require_admin

router = APIRouter(prefix="/api/companies", tags=["companies"])


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    career_url: str | None = None


@router.get("")
def list_companies(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "career_url": c.career_url}
        for c in db.query(Company).order_by(Company.name).all()
    ]


@router.post("", status_code=201)
def create_company(body: CompanyIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    company = Company(name=body.name, career_url=body.career_url)
    db.add(company)
    db.commit()
    return {"id": company.id, "name": company.name, "career_url": company.career_url}
