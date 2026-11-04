"""LLM 结构化输出的 pydantic 模型（统一岗位 Schema 与 Master Profile）。"""

from pydantic import BaseModel, Field


class JobParsed(BaseModel):
    """统一岗位 Schema（调研方案 4.2）。company 由入库侧携带，不要求模型输出。"""

    title: str = Field(min_length=1)
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None
    salary_range: str | None = None
    experience_required: str | None = None
    education_required: str | None = None
    skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class IdentityParsed(BaseModel):
    """简历身份信息抽取（第一遍，用于出站脱敏）。"""

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    id_number: str | None = None


class BasicInfo(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    location: str | None = None
    years_of_experience: float | None = None


class EducationItem(BaseModel):
    school: str | None = None
    degree: str | None = None
    major: str | None = None
    period: str | None = None


class WorkItem(BaseModel):
    company: str | None = None
    title: str | None = None
    period: str | None = None
    highlights: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str | None = None
    role: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class ResumeProfile(BaseModel):
    """Master Profile（调研方案 4.3）。身份字段保留占位符，原文在本地加密存储。"""

    basic_info: BasicInfo = Field(default_factory=BasicInfo)
    education: list[EducationItem] = Field(default_factory=list)
    work: list[WorkItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certificates: list[str] = Field(default_factory=list)
    self_summary: str | None = None


class MatchScore(BaseModel):
    """人岗精排输出（调研方案 4.4）。总分由代码加权，模型只给维度分。"""

    dimension_scores: dict[str, int] = Field(default_factory=dict)
    verdict: str = ""
    reasons: str = ""
    matching_points: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    score_basis: str = ""


class SuggestionItem(BaseModel):
    """单条简历修改建议（调研方案 4.5）。`original` 必须是简历原文片段，否则会被校验追加警告。"""

    section: str = ""
    action: str = ""
    original: str = ""
    proposed: str = ""
    why: str = ""
    priority: str = "medium"


class SuggestionPayload(BaseModel):
    """建议整体输出：逐条建议 + 缺失关键词 + 防编造警告。"""

    suggestions: list[SuggestionItem] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    honesty_warnings: list[str] = Field(default_factory=list)
