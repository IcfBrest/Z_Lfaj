"""人岗匹配打分：硬规则过滤 → 粗排 → LLM 精排 → 代码加权总分。

对应设计 `changes/phase1-match-scoring/design.md`：
- 硬规则与粗排零 token；精排经 `chat_structured`（temperature=0 + JSON 校验重试）。
- 总分 = Σ(维度分 × 权重) / Σ权重，clamp 到 0~100；模型不给总分。
- 缓存键 = (user_id, resume_id, job_ref_type, job_ref_id, resume_version)。
- 只做手动触发（用户 2026-11-03 决定），本模块不挂任何自动队列。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .llm_gateway import chat_structured
from .models import JobPosting, MatchResult, Resume, User, UserManualJob
from .schemas_llm import MatchScore

DIMENSIONS = ("技能匹配", "经验相关度", "职级与薪资匹配", "行业/业务匹配")
DEFAULT_WEIGHTS: dict[str, float] = {name: 25.0 for name in DIMENSIONS}
DEFAULT_LIMIT = 20
EXPERIENCE_GAP_YEARS = 2.0
JOB_REF_TYPES = ("job_posting", "user_manual_job")

DEGREE_RANK = {
    "大专": 1,
    "专科": 1,
    "associate": 1,
    "本科": 2,
    "学士": 2,
    "bachelor": 2,
    "硕士": 3,
    "研究生": 3,
    "master": 3,
    "博士": 4,
    "phd": 4,
    "doctor": 4,
}

SCORE_SYSTEM_PROMPT = (
    "你是资深技术招聘官，负责评估候选人与岗位的匹配度。"
    "只依据给定的简历画像与岗位信息判断，禁止编造候选人不具备的经历。"
    "必须按四个维度分别给出 0-100 的整数分：技能匹配、经验相关度、职级与薪资匹配、行业/业务匹配。"
    "评分锚点：90+ 高度匹配，可直接进入面试；75-89 匹配良好；60-74 基本可用；60 以下不匹配。"
    "只输出一个 JSON 对象，不要包含任何解释性文字或代码块标记。JSON 字段："
    '{"dimension_scores": {"技能匹配": 0, "经验相关度": 0, "职级与薪资匹配": 0, "行业/业务匹配": 0}, '
    '"verdict": "不超过 12 字的结论", "reasons": "不超过 200 字的总体判断", '
    '"matching_points": ["候选人与岗位吻合的具体点"], '
    '"gaps": ["候选人相对岗位的缺口"], '
    '"score_basis": "一句话说明打分依据"}'
)


@dataclass
class JobView:
    """与 `JobPosting`/`UserManualJob` 字段同构的只读视图（便于单元测试）。"""

    ref_type: str
    ref_id: int
    title: str = ""
    company: str | None = None
    location: str | None = None
    experience_required: str | None = None
    education_required: str | None = None
    salary_range: str | None = None
    skills: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    description_raw: str = ""

    @property
    def key(self) -> str:
        return f"{self.ref_type}:{self.ref_id}"

    def as_snapshot(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "salary_range": self.salary_range,
            "experience_required": self.experience_required,
            "education_required": self.education_required,
        }


# ---------------------------------------------------------------- 读取岗位


def _view_from(job, ref_type: str, company: str | None) -> JobView:
    return JobView(
        ref_type=ref_type,
        ref_id=job.id,
        title=job.title or "",
        company=company,
        location=job.location,
        experience_required=job.experience_required,
        education_required=job.education_required,
        salary_range=job.salary_range,
        skills=list(job.skills or []),
        responsibilities=list(job.responsibilities or []),
        requirements=list(job.requirements or []),
        description_raw=job.description_raw or "",
    )


def load_job(db: Session, ref_type: str, ref_id: int, user_id: int | None = None) -> JobView | None:
    """按引用取岗位；私有岗位必须属于 `user_id`，共享岗位必须活跃。"""
    if ref_type not in JOB_REF_TYPES:
        return None
    if ref_type == "job_posting":
        row = db.query(JobPosting).filter_by(id=ref_id).one_or_none()
        if row is None or not row.is_active:
            return None
        from .models import Company

        company = db.get(Company, row.company_id)
        return _view_from(row, ref_type, company.name if company else None)
    row = db.query(UserManualJob).filter_by(id=ref_id).one_or_none()
    if row is None or (user_id is not None and row.user_id != user_id):
        return None
    return _view_from(row, ref_type, row.company_name)


def list_jobs(db: Session, user: User) -> list[JobView]:
    """当前用户可见的全部岗位：活跃共享岗位 + 本人私有岗位。"""
    from .models import Company

    shared = (
        db.query(JobPosting, Company.name)
        .join(Company, JobPosting.company_id == Company.id)
        .filter(JobPosting.is_active.is_(True))
        .all()
    )
    mine = db.query(UserManualJob).filter_by(user_id=user.id).all()
    return [_view_from(job, "job_posting", name) for job, name in shared] + [
        _view_from(job, "user_manual_job", job.company_name) for job in mine
    ]


# ---------------------------------------------------------------- 硬规则过滤


def parse_min_years(text: str | None) -> float | None:
    """从"3-5年"/"经验不限"这类自由文本里取最低年限；取不到返回 None（不过滤）。"""
    if not text:
        return None
    if "不限" in text or "无经验" in text or "应届" in text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:[-~至—]\s*(\d+(?:\.\d+)?))?\s*年", text)
    if match is None:
        return None
    return float(match.group(1))


def degree_rank(text: str | None) -> int | None:
    if not text:
        return None
    lowered = str(text).lower()
    rank = None
    for key, value in DEGREE_RANK.items():
        if key in lowered:
            rank = max(rank or 0, value)
    return rank


def profile_years(profile: dict | None) -> float | None:
    value = ((profile or {}).get("basic_info") or {}).get("years_of_experience")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def profile_degree(profile: dict | None) -> int | None:
    rank = None
    for item in (profile or {}).get("education") or []:
        current = degree_rank(str(item.get("degree") or ""))
        if current is not None:
            rank = max(rank or 0, current)
    return rank


def filter_jobs(profile: dict | None, jobs: list[JobView]) -> tuple[list[JobView], list[dict]]:
    """硬门槛过滤：经验差 > 2 年、学历低于要求。字段解析不出时一律放行。"""
    years = profile_years(profile)
    degree = profile_degree(profile)
    kept: list[JobView] = []
    excluded: list[dict] = []
    for job in jobs:
        reason = None
        need_years = parse_min_years(job.experience_required)
        if years is not None and need_years is not None and need_years - years > EXPERIENCE_GAP_YEARS:
            reason = f"要求 {need_years:g} 年经验，简历 {years:g} 年"
        need_degree = degree_rank(job.education_required)
        if reason is None and degree is not None and need_degree is not None and degree < need_degree:
            reason = f"要求学历「{job.education_required}」，简历学历不足"
        if reason is None:
            kept.append(job)
        else:
            excluded.append(
                {
                    "job_ref_type": job.ref_type,
                    "job_ref_id": job.ref_id,
                    "title": job.title,
                    "reason": reason,
                }
            )
    return kept, excluded


# ---------------------------------------------------------------- 粗排


def _profile_skills(profile: dict | None) -> list[str]:
    return [str(s).strip().lower() for s in (profile or {}).get("skills") or [] if str(s).strip()]


def _profile_titles(profile: dict | None) -> list[str]:
    data = profile or {}
    titles = [str(w.get("title") or "") for w in data.get("work") or []]
    titles += [str(p.get("name") or "") for p in data.get("projects") or []]
    titles += [str(p.get("role") or "") for p in data.get("projects") or []]
    return [t.strip().lower() for t in titles if t.strip()]


def relevance(profile: dict | None, job: JobView) -> float:
    """零成本相关性：技能重叠 60% + 标题命中 25% + 城市命中 15%。"""
    skills = _profile_skills(profile)
    job_skills = [str(s).strip().lower() for s in job.skills if str(s).strip()]
    hits = sum(1 for js in job_skills if any(js in s or s in js for s in skills))
    skill_score = hits / len(job_skills) if job_skills else 0.0

    title = (job.title or "").lower()
    titles = _profile_titles(profile)
    title_hit = 1.0 if any(t in title or (title and title in t) for t in titles) else 0.0

    location = str(((profile or {}).get("basic_info") or {}).get("location") or "").strip().lower()
    location_hit = 1.0 if location and job.location and location in job.location.lower() else 0.0
    return round(0.6 * skill_score + 0.25 * title_hit + 0.15 * location_hit, 4)


def rank_candidates(profile: dict | None, jobs: list[JobView], limit: int = DEFAULT_LIMIT) -> list[JobView]:
    ordered = sorted(jobs, key=lambda job: relevance(profile, job), reverse=True)
    if limit <= 0:
        return []
    return ordered[:limit]


# ---------------------------------------------------------------- 加权总分


def resolve_weights(user: User | None) -> dict[str, float]:
    raw = dict(getattr(user, "score_weights", None) or {})
    weights: dict[str, float] = {}
    for name in DIMENSIONS:
        try:
            value = float(raw.get(name, DEFAULT_WEIGHTS[name]))
        except (TypeError, ValueError):
            value = DEFAULT_WEIGHTS[name]
        weights[name] = max(0.0, value)
    if sum(weights.values()) <= 0:
        return dict(DEFAULT_WEIGHTS)
    return weights


def combine(
    dimension_scores: dict | None, weights: dict[str, float]
) -> tuple[int, list[str], dict[str, int]]:
    """返回 (加权总分, 缺失维度, clamp 后的维度分)。"""
    raw = dimension_scores or {}
    scores: dict[str, int] = {}
    missing: list[str] = []
    for name in DIMENSIONS:
        if name not in raw:
            missing.append(name)
            scores[name] = 0
            continue
        try:
            value = int(round(float(raw[name])))
        except (TypeError, ValueError):
            missing.append(name)
            scores[name] = 0
            continue
        scores[name] = max(0, min(100, value))
    total_weight = sum(weights.get(name, 0.0) for name in DIMENSIONS) or 1.0
    total = sum(scores[name] * weights.get(name, 0.0) for name in DIMENSIONS) / total_weight
    return max(0, min(100, int(round(total)))), missing, scores


# ---------------------------------------------------------------- 精排与缓存


def _profile_summary(profile: dict | None) -> dict:
    data = profile or {}
    basic = data.get("basic_info") or {}
    return {
        "yoe": basic.get("years_of_experience"),
        "location": basic.get("location"),
        "skills": (data.get("skills") or [])[:40],
        "education": [
            {"school": e.get("school"), "degree": e.get("degree"), "major": e.get("major")}
            for e in (data.get("education") or [])[:5]
        ],
        "work": [
            {"company": w.get("company"), "title": w.get("title"), "period": w.get("period"), "highlights": (w.get("highlights") or [])[:4]}
            for w in (data.get("work") or [])[:6]
        ],
        "projects": [
            {"name": p.get("name"), "role": p.get("role"), "tech_stack": (p.get("tech_stack") or [])[:10], "highlights": (p.get("highlights") or [])[:4]}
            for p in (data.get("projects") or [])[:6]
        ],
        "self_summary": (data.get("self_summary") or "")[:600],
    }


def _job_summary(job: JobView) -> dict:
    return {
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "salary_range": job.salary_range,
        "experience_required": job.experience_required,
        "education_required": job.education_required,
        "skills": job.skills[:40],
        "responsibilities": job.responsibilities[:10],
        "requirements": job.requirements[:10],
    }


def build_prompt(profile: dict | None, job: JobView) -> tuple[str, str]:
    user_prompt = (
        "【简历画像】\n"
        + json.dumps(_profile_summary(profile), ensure_ascii=False)
        + "\n\n【岗位信息】\n"
        + json.dumps(_job_summary(job), ensure_ascii=False)
        + "\n\n请按 system 中的 JSON 结构输出评分。"
    )
    return SCORE_SYSTEM_PROMPT, user_prompt


def _cached(db: Session, user_id: int, resume_id: int, resume_version: int, job: JobView) -> MatchResult | None:
    return (
        db.query(MatchResult)
        .filter_by(
            user_id=user_id,
            resume_id=resume_id,
            resume_version=resume_version,
            job_ref_type=job.ref_type,
            job_ref_id=job.ref_id,
        )
        .one_or_none()
    )


def score_one(
    db: Session,
    user: User,
    resume: Resume,
    job: JobView,
    force: bool = False,
) -> MatchResult:
    """精排单个岗位；命中缓存直接返回（force=True 时覆盖）。"""
    if not resume.parsed_profile_json:
        raise ValueError("简历尚未解析完成，无法打分")
    cached = _cached(db, user.id, resume.id, resume.version, job)
    if cached is not None and not force:
        return cached

    weights = resolve_weights(user)
    system_prompt, user_prompt = build_prompt(resume.parsed_profile_json, job)
    result = chat_structured(db, user.id, "score", system_prompt, user_prompt, MatchScore)
    total, missing, scores = combine(result.data.get("dimension_scores"), weights)

    payload = {
        "dimension_scores": scores,
        "weights": weights,
        "total": total,
        "verdict": result.data.get("verdict") or "",
        "reasons": result.data.get("reasons") or "",
        "matching_points": result.data.get("matching_points") or [],
        "gaps": result.data.get("gaps") or [],
        "score_basis": result.data.get("score_basis") or "",
        "missing_dimensions": missing,
        "attempts": result.attempts,
        "tokens": {"input": result.input_tokens, "output": result.output_tokens},
        "job_snapshot": job.as_snapshot(),
        "resume_version": resume.version,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }

    if cached is not None:  # force 覆盖
        cached.score = total
        cached.payload_json = payload
        db.commit()
        return cached

    row = MatchResult(
        user_id=user.id,
        resume_id=resume.id,
        resume_version=resume.version,
        job_ref_type=job.ref_type,
        job_ref_id=job.ref_id,
        score=total,
        payload_json=payload,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:  # 并发插入：回滚后改为覆盖既有行
        db.rollback()
        existing = _cached(db, user.id, resume.id, resume.version, job)
        if existing is None:
            raise
        existing.score = total
        existing.payload_json = payload
        db.commit()
        return existing
    db.refresh(row)
    return row


def master_resume(db: Session, user_id: int) -> Resume | None:
    return (
        db.query(Resume)
        .filter_by(user_id=user_id, is_master=True)
        .order_by(Resume.id.desc())
        .first()
    )


def resolve_resume(db: Session, user_id: int, resume_id: int | None) -> Resume:
    """显式 resume_id 优先，否则取 master；都没有时抛 ValueError。"""
    if resume_id is not None:
        resume = db.query(Resume).filter_by(id=resume_id, user_id=user_id).one_or_none()
        if resume is None:
            raise LookupError("简历不存在")
        return resume
    resume = master_resume(db, user_id)
    if resume is None:
        raise LookupError("还没有简历，请先上传并等待解析完成")
    return resume


def run_scoring(
    db: Session,
    user: User,
    resume: Resume,
    limit: int = DEFAULT_LIMIT,
    force: bool = False,
) -> dict:
    """一次全量打分：过滤 → 粗排 → 逐个精排（命中缓存不重复调用）。"""
    profile = resume.parsed_profile_json or {}
    jobs = list_jobs(db, user)
    kept, excluded = filter_jobs(profile, jobs)
    candidates = rank_candidates(profile, kept, limit)

    scored = 0
    cached = 0
    failures: list[dict] = []
    for job in candidates:
        try:
            before = _cached(db, user.id, resume.id, resume.version, job)
            row = score_one(db, user, resume, job, force=force)
            if before is not None and not force:
                cached += 1
            else:
                scored += 1
            assert row.score is not None
        except Exception as exc:  # 单岗失败不拖垮整轮
            db.rollback()
            failures.append({"job_ref_type": job.ref_type, "job_ref_id": job.ref_id, "error": str(exc)[:300]})
    return {
        "resume_id": resume.id,
        "resume_version": resume.version,
        "candidates": len(candidates),
        "scored": scored,
        "cached": cached,
        "failed": len(failures),
        "failures": failures,
        "excluded": excluded,
    }
