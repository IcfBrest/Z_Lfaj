"""解析服务：JD 解析（单遍）与简历解析（两遍：身份抽取→脱敏→结构化）。"""

import re

from .llm_gateway import chat_structured
from .schemas_llm import IdentityParsed, JobParsed, ResumeProfile

JD_SYSTEM_PROMPT = """你是招聘信息结构化助手。把用户给出的中文招聘 JD 文本解析为 JSON，字段如下：
title(岗位名), department(部门), location(城市), employment_type(全职/实习等),
salary_range(薪资，如 "25-45K·16薪"), experience_required(经验要求), education_required(学历要求),
skills(技能列表), responsibilities(岗位职责列表), requirements(任职要求列表), nice_to_have(加分项列表)。
规则：只输出一个 JSON 对象；JD 中没有的信息填 null（列表填 []）；不要编造；列表逐条拆分原文句子，保留原意。"""

IDENTITY_SYSTEM_PROMPT = """你是信息抽取助手。从简历文本中找出求职者的姓名、手机号、邮箱、身份证号。
只输出 JSON：{"name": ..., "phone": ..., "email": ..., "id_number": ...}，找不到的字段填 null。不要输出其他内容。"""

PROFILE_SYSTEM_PROMPT = """你是简历结构化助手。把脱敏后的简历文本解析为 JSON：
basic_info{name, phone, email, location, years_of_experience(数字，年)},
education[{school, degree, major, period}], work[{company, title, period, highlights[...]}],
projects[{name, role, tech_stack[...], highlights[...]}], skills[...], certificates[...], self_summary。
规则：只输出一个 JSON 对象；保持原文占位符（如 __PHONE__）原样保留；不要编造或推断未写明的经历；
highlights 逐条拆分，保留量化数据。"""

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_text(text: str, identity: IdentityParsed) -> str:
    """出站脱敏：手机号/身份证/邮箱按正则，姓名按精确替换。"""
    masked = _PHONE_RE.sub("__PHONE__", text)
    masked = _ID_RE.sub("__ID__", masked)
    masked = _EMAIL_RE.sub("__EMAIL__", masked)
    if identity.phone:
        masked = masked.replace(identity.phone, "__PHONE__")
    if identity.id_number:
        masked = masked.replace(identity.id_number, "__ID__")
    if identity.email:
        masked = masked.replace(identity.email, "__EMAIL__")
    if identity.name:
        masked = masked.replace(identity.name, "__NAME__")
    return masked


def parse_jd(db, user_id: int | None, jd_text: str) -> dict:
    result = chat_structured(db, user_id, "parse", JD_SYSTEM_PROMPT, jd_text, JobParsed)
    return result.data


def extract_identity(db, user_id: int | None, resume_text: str) -> IdentityParsed:
    result = chat_structured(db, user_id, "parse", IDENTITY_SYSTEM_PROMPT, resume_text, IdentityParsed)
    return IdentityParsed(**result.data)


def parse_resume_profile(db, user_id: int | None, masked_text: str) -> dict:
    result = chat_structured(db, user_id, "parse", PROFILE_SYSTEM_PROMPT, masked_text, ResumeProfile)
    return result.data
