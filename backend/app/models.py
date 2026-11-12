from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    invited_by_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 四维打分权重：{"技能匹配": 25, ...}；空表示均等
    score_weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    providers: Mapped[list["UserProvider"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class InvitationCode(Base):
    __tablename__ = "invitation_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserProvider(Base):
    __tablename__ = "user_providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))  # 展示名，如 deepseek / openai
    base_url: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 按任务类型覆盖默认模型：{"parse": "...", "score": "...", "suggest": "..."}
    task_models: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="providers")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    career_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobPosting(Base):
    """平台共享岗位（管理员导入/采集）。user_manual_jobs 与其字段同构。"""

    __tablename__ = "job_postings"
    __table_args__ = (
        # 采集去重键：同一站点同一外部 id 只应有一行（手动导入的岗位 external_id 为 NULL）
        Index("uq_job_postings_source_external", "company_id", "source_type", "external_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(128), nullable=True)
    experience_required: Mapped[str | None] = mapped_column(String(128), nullable=True)
    education_required: Mapped[str | None] = mapped_column(String(128), nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    responsibilities: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    nice_to_have: Mapped[list] = mapped_column(JSON, default=list)
    description_raw: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    # 采集来源的站点内部 id（手动导入的岗位为 NULL）
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserManualJob(Base):
    """用户手动粘贴的私有岗位，字段与 JobPosting 同构。"""

    __tablename__ = "user_manual_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    company_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    salary_range: Mapped[str | None] = mapped_column(String(128), nullable=True)
    experience_required: Mapped[str | None] = mapped_column(String(128), nullable=True)
    education_required: Mapped[str | None] = mapped_column(String(128), nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    responsibilities: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    nice_to_have: Mapped[list] = mapped_column(JSON, default=list)
    description_raw: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="manual")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    file_path: Mapped[str] = mapped_column(String(512))
    file_format: Mapped[str] = mapped_column(String(16))  # pdf | docx | md
    original_encrypted: Mapped[str] = mapped_column(Text)  # 原文（含真实身份）Fernet 密文
    parsed_profile_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_master: Mapped[bool] = mapped_column(Boolean, default=False)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="resumes")


class BackgroundTask(Base):
    """应用内后台任务（解析类）状态登记。"""

    __tablename__ = "background_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # job_parse | resume_parse
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|failed
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # job_posting|user_manual_job|resume
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 任务参数（如打分任务的 limit/force），重试时原样复用
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(32))  # parse|score|suggest|connectivity
    provider_name: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_estimate: Mapped[float] = mapped_column(default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16))  # ok|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Suggestion(Base):
    """Phase 2：针对某次匹配结果生成的简历修改建议（一条 match 一条建议，可 force 覆盖）。"""

    __tablename__ = "suggestions"
    __table_args__ = (UniqueConstraint("user_id", "match_result_id", "resume_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"))
    match_result_id: Mapped[int | None] = mapped_column(ForeignKey("match_results.id"), nullable=True, index=True)
    resume_version: Mapped[int] = mapped_column(Integer, default=1)
    job_ref_type: Mapped[str] = mapped_column(String(32))
    job_ref_id: Mapped[int] = mapped_column(Integer)
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MatchResult(Base):
    """预留：Phase 1 匹配打分。Phase 0 仅建表。"""

    __tablename__ = "match_results"
    __table_args__ = (UniqueConstraint("user_id", "resume_id", "job_ref_type", "job_ref_id", "resume_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"))
    resume_version: Mapped[int] = mapped_column(Integer, default=1)
    job_ref_type: Mapped[str] = mapped_column(String(32))
    job_ref_id: Mapped[int] = mapped_column(Integer)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
