"""简历修改建议内核（Phase 2，调研方案 4.5）。

输入是一条已有的匹配结果（复用它的 gaps 与维度分），输出逐条建议：
`section` 定位简历字段、`action` 动作、`original`/`proposed` 原文与改写、`why` 理由、`priority` 优先级，
外加 `missing_keywords`（岗位要求里简历缺失的硬技能）与 `honesty_warnings`（防编造提醒）。

设计要点（changes/phase2-suggestions/design.md）：
- 缓存键 `(user_id, match_result_id, resume_version)`，重新打分后旧建议自动失效；
- 输出固定为 `SuggestionPayload`，action 走白名单、priority 归一、条数上限 8；
- `original` 必须能在简历画像里逐字定位，定位不到就追加警告而不是丢掉建议；
- 只读简历，绝不回写 parsed_profile_json。
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import scoring
from .llm_gateway import chat_structured
from .models import MatchResult, Resume, Suggestion, User
from .schemas_llm import SuggestionPayload

MAX_ITEMS = 8
ACTIONS = ("改写", "新增", "删除", "补充关键词")
PRIORITIES = ("high", "medium", "low")
PRIORITY_ALIASES = {
    "high": "high",
    "高": "high",
    "紧急": "high",
    "medium": "medium",
    "中": "medium",
    "一般": "medium",
    "low": "low",
    "低": "low",
    "可选": "low",
}

SUGGEST_SYSTEM_PROMPT = (
    "你是资深简历顾问，帮助候选人针对某一个具体岗位修改简历。"
    "只依据给定的简历画像、简历原文与岗位信息提建议，严禁编造候选人不具备的经历、公司、数据或技能。"
    "建议必须可定位：`original` 必须逐字摘自简历原文的片段；确实没有对应原文时把 `original` 留空，"
    "并在 `proposed` 里写成“如有……实际经验请补充说明”，同时把这条写进 `honesty_warnings`。"
    "`section` 指向简历字段路径，例如 basic_info / skills / work[0].highlights / projects[1].highlights / self_summary。"
    "`action` 只能取：改写、新增、删除、补充关键词。`priority` 只能取 high、medium、low。"
    f"输出 1~{MAX_ITEMS} 条最有价值的建议，不要面面俱到。"
    "只输出一个 JSON 对象，不要包含任何解释性文字或代码块标记。JSON 字段："
    '{"suggestions": [{"section": "work[0].highlights", "action": "改写", '
    '"original": "简历里的原句", "proposed": "改写后的句子", '
    '"why": "为什么这样改，对应岗位的哪条要求", "priority": "high"}], '
    '"missing_keywords": ["岗位要求但简历缺失的技能"], '
    '"honesty_warnings": ["哪些要求简历无法证实，提醒候选人不得虚构"]}'
)

_LOCATION_HINT = {
    "basic_info": "基本信息",
    "skills": "技能清单",
    "self_summary": "自我评价",
    "work": "工作经历",
    "projects": "项目经历",
    "education": "教育经历",
    "certificates": "证书",
}


# ---------------------------------------------------------------- 文本处理


def _flatten(value) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(_flatten(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            out.extend(_flatten(item))
    elif isinstance(value, (int, float)):
        out.append(str(value))
    return out


def profile_text(profile: dict | None) -> str:
    """把简历画像摊平成纯文本，用于 `original` 的确定性定位校验。"""
    return "\n".join(_flatten(profile or {}))


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def locate_original(resume_text: str, original: str) -> bool:
    """`original` 是否能在简历文本中定位（忽略空白差异）；空原文视为可定位。"""
    compact_original = _compact(original)
    if not compact_original:
        return True
    return compact_original in _compact(resume_text)


def _normalize_priority(value: str | None) -> str:
    key = (value or "").strip().lower()
    return PRIORITY_ALIASES.get(key) or PRIORITY_ALIASES.get((value or "").strip()) or "medium"


def _normalize_action(value: str | None, proposed: str) -> str:
    action = (value or "").strip()
    if action in ACTIONS:
        return action
    return "改写" if proposed else "补充关键词"


def normalize_item(section: str, action: str, original: str, proposed: str, why: str, priority: str) -> dict:
    """单条建议归一化：未知 action/priority 落到确定取值，section 缺失时标注。"""
    proposed_text = (proposed or "").strip()
    return {
        "section": (section or "").strip() or "未指明",
        "action": _normalize_action(action, proposed_text),
        "original": (original or "").strip(),
        "proposed": proposed_text,
        "why": (why or "").strip(),
        "priority": _normalize_priority(priority),
    }


def normalize_payload(payload: SuggestionPayload, resume_text: str) -> dict:
    """裁剪条数、归一字段、并对定位不到的 `original` 追加 honesty_warnings。"""
    items = [
        normalize_item(
            item.section, item.action, item.original, item.proposed, item.why, item.priority
        )
        for item in payload.suggestions
    ][:MAX_ITEMS]

    warnings = [w.strip() for w in payload.honesty_warnings if w and w.strip()]
    for index, item in enumerate(items, start=1):
        if item["original"] and not locate_original(resume_text, item["original"]):
            warnings.append(f"建议 {index} 的原文未能在简历中定位，请核对后再采纳。")
    if not items:
        warnings.append("模型没有给出可用的具体建议，请补充简历细节后重试。")

    keywords = [k.strip() for k in payload.missing_keywords if k and k.strip()]
    return {
        "suggestions": items,
        "missing_keywords": keywords[:30],
        "honesty_warnings": warnings[:20],
    }


def section_label(section: str) -> str:
    """把字段路径转成可读名称，供前端展示。"""
    head = (section or "").split("[")[0].split(".")[0]
    return _LOCATION_HINT.get(head, section or "未指明")


# ---------------------------------------------------------------- 提示词


def build_prompt(profile: dict | None, job: scoring.JobView, match_payload: dict | None) -> tuple[str, str]:
    payload = match_payload or {}
    resume_text = profile_text(profile)[:3000]
    user_prompt = (
        "【简历画像】\n"
        + json.dumps(scoring._profile_summary(profile), ensure_ascii=False)
        + "\n\n【简历原文（`original` 必须逐字取自这里）】\n"
        + resume_text
        + "\n\n【岗位信息】\n"
        + json.dumps(scoring._job_summary(job), ensure_ascii=False)
        + "\n\n【已有的匹配结论】\n"
        + json.dumps(
            {
                "score": payload.get("total"),
                "verdict": payload.get("verdict"),
                "dimension_scores": payload.get("dimension_scores") or {},
                "gaps": payload.get("gaps") or [],
                "reasons": payload.get("reasons"),
            },
            ensure_ascii=False,
        )
        + "\n\n请按 system 中的 JSON 结构输出针对该岗位的简历修改建议。"
    )
    return SUGGEST_SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------- 生成与读取


def load_match(db: Session, user_id: int, match_id: int) -> MatchResult:
    """读取本人的匹配结果，不存在或他人一律 LookupError（API 层转 404）。"""
    row = db.query(MatchResult).filter_by(id=match_id, user_id=user_id).one_or_none()
    if row is None:
        raise LookupError("匹配结果不存在，请先对该岗位打分")
    return row


def cached(db: Session, user_id: int, match_id: int, resume_version: int) -> Suggestion | None:
    return (
        db.query(Suggestion)
        .filter_by(user_id=user_id, match_result_id=match_id, resume_version=resume_version)
        .one_or_none()
    )


def generate(db: Session, user: User, match: MatchResult, force: bool = False) -> Suggestion:
    """按匹配结果生成建议：命中缓存直接返回，force 重算并覆盖同一行。"""
    existing = cached(db, user.id, match.id, match.resume_version)
    if existing is not None and not force:
        return existing

    resume = db.get(Resume, match.resume_id)
    if resume is None or not resume.parsed_profile_json:
        raise LookupError("简历不存在或尚未解析完成")
    job = scoring.load_job(db, match.job_ref_type, match.job_ref_id, user_id=user.id)
    if job is None:
        raise LookupError("岗位不存在或已下架")

    profile = resume.parsed_profile_json or {}
    match_payload = match.payload_json or {}
    system_prompt, user_prompt = build_prompt(profile, job, match_payload)
    result = chat_structured(
        db, user.id, "suggest", system_prompt, user_prompt, SuggestionPayload
    )
    raw = result.data if isinstance(result.data, SuggestionPayload) else SuggestionPayload(**result.data)
    data = normalize_payload(raw, profile_text(profile))
    payload = {
        **data,
        "job_ref_type": match.job_ref_type,
        "job_ref_id": match.job_ref_id,
        "job_title": job.title,
        "company": job.company,
        "match_score": match.score,
        "dimension_scores": match_payload.get("dimension_scores") or {},
        "gaps": match_payload.get("gaps") or [],
        "resume_version": match.resume_version,
        "attempts": result.attempts,
        "tokens": {"input": result.input_tokens, "output": result.output_tokens},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    row = existing
    if row is None:
        row = Suggestion(
            user_id=user.id,
            resume_id=resume.id,
            match_result_id=match.id,
            resume_version=match.resume_version,
            job_ref_type=match.job_ref_type,
            job_ref_id=match.job_ref_id,
            payload_json=payload,
        )
        db.add(row)
    else:
        row.resume_id = resume.id
        row.job_ref_type = match.job_ref_type
        row.job_ref_id = match.job_ref_id
        row.payload_json = payload

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = cached(db, user.id, match.id, match.resume_version)
        if row is None:
            raise
        row.payload_json = payload
        db.commit()
    db.refresh(row)
    return row


def suggestion_dict(row: Suggestion) -> dict:
    payload = row.payload_json or {}
    return {
        "id": row.id,
        "match_id": row.match_result_id,
        "resume_id": row.resume_id,
        "resume_version": row.resume_version,
        "job_ref_type": row.job_ref_type,
        "job_ref_id": row.job_ref_id,
        "job_title": payload.get("job_title"),
        "company": payload.get("company"),
        "match_score": payload.get("match_score"),
        "suggestions": [
            {**item, "section_label": section_label(item.get("section", ""))}
            for item in (payload.get("suggestions") or [])
        ],
        "missing_keywords": payload.get("missing_keywords") or [],
        "honesty_warnings": payload.get("honesty_warnings") or [],
        "dimension_scores": payload.get("dimension_scores") or {},
        "gaps": payload.get("gaps") or [],
        "tokens": payload.get("tokens") or {},
        "generated_at": payload.get("generated_at") or row.created_at.isoformat(),
    }
