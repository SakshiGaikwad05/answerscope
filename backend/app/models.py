"""SQLAlchemy ORM models.

Status values are kept as short strings with CHECK constraints so they stay
readable in the database and easy to migrate.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

JOB_STATUSES = ("pending", "running", "completed", "failed")
_status_check = "status IN ('pending', 'running', 'completed', 'failed')"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")


class UserSession(Base):
    """A login session. Only a SHA-256 hash of the session token is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsageEvent(Base):
    """One billable AI action (visibility run, question generation, fix draft), for quotas."""

    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('visibility_run', 'question_generation', 'fix_generation', 'backlink_discovery')", name="ck_usage_kind"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # Paid with the user's own API key: doesn't count toward the server-wide cap
    own_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


USER_KEY_PROVIDERS = ("openai", "anthropic", "gemini", "perplexity", "nvidia", "brave")


class UserApiKey(Base):
    """A user's own provider API key, encrypted at rest (Fernet). Only the last 4 characters are ever shown."""

    __tablename__ = "user_api_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_api_key_provider"),
        CheckConstraint(f"provider IN ({', '.join(repr(p) for p in USER_KEY_PROVIDERS)})", name="ck_user_api_key_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    verified: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable only for projects created before accounts existed; they are claimed by the first account.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str | None] = mapped_column(String(200))  # business category, e.g. "dental clinic"
    # Local business profile (owner-provided; verified against the website by the audit)
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    service_area: Mapped[str | None] = mapped_column(String(300))
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(40))
    opening_hours: Mapped[str | None] = mapped_column(String(300))
    services: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # Official profiles: Google Business Profile, Facebook, Instagram, directories, ...
    profile_urls: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    owner: Mapped[User | None] = relationship(back_populates="projects")
    backlinks: Mapped[list["BacklinkItem"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    competitors: Mapped[list["Competitor"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Competitor.id"
    )
    audits: Mapped[list["WebsiteAudit"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    questions: Mapped[list["Question"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    runs: Mapped[list["VisibilityRun"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_competitor_project_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048))

    project: Mapped[Project] = relationship(back_populates="competitors")


class WebsiteAudit(Base):
    __tablename__ = "website_audits"
    __table_args__ = (
        CheckConstraint(_status_check, name="ck_audit_status"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="ck_audit_score_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    progress_message: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float | None] = mapped_column(Float)
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Site-level facts (robots.txt, sitemap, AI crawler access, ...)
    site_info: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    # List of scored checks: {id, label, category, weight, score, passed, detail, evidence}
    checks: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # Topics customers ask about that no crawled page appears to cover
    content_gaps: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="audits")
    pages: Mapped[list["AuditPage"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", order_by="AuditPage.id"
    )


class AuditPage(Base):
    __tablename__ = "audit_pages"
    __table_args__ = (UniqueConstraint("audit_id", "url", name="uq_audit_page_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(
        ForeignKey("website_audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    meta_description: Mapped[str | None] = mapped_column(Text)
    canonical: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(50))
    h1: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    headings: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    internal_links: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    external_links: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_types: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    has_faq: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    faq_questions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    issues: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    text_excerpt: Mapped[str | None] = mapped_column(Text)

    audit: Mapped[WebsiteAudit] = relationship(back_populates="pages")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (CheckConstraint("source IN ('llm', 'template')", name="ck_question_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'llm' = generated by a configured model, 'template' = deterministic fallback
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    project: Mapped[Project] = relationship(back_populates="questions")


class VisibilityRun(Base):
    __tablename__ = "visibility_runs"
    __table_args__ = (CheckConstraint(_status_check, name="ck_run_status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    total_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_questions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Snapshot of the conditions the run was executed under (brand, domain,
    # competitors, provider settings) so later comparisons stay honest.
    conditions: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="runs")
    answers: Mapped[list["ProviderAnswer"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="ProviderAnswer.id"
    )


class ProviderAnswer(Base):
    __tablename__ = "provider_answers"
    __table_args__ = (UniqueConstraint("run_id", "question_id", name="uq_answer_run_question"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("visibility_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_category: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    # Sources the provider attached to the answer (web search citations): [{url, title}]
    sources: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    website_cited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Optional AI-extracted analysis of the answer (businesses recommended, in order), with its model
    analysis: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    run: Mapped[VisibilityRun] = relationship(back_populates="answers")
    mentions: Mapped[list["Mention"]] = relationship(
        back_populates="answer", cascade="all, delete-orphan", order_by="Mention.id"
    )


class Mention(Base):
    """One detected brand/competitor mention or citation inside an answer, with evidence."""

    __tablename__ = "mentions"
    __table_args__ = (
        CheckConstraint("entity_type IN ('brand', 'competitor')", name="ck_mention_entity_type"),
        CheckConstraint("kind IN ('mention', 'citation')", name="ck_mention_kind"),
        UniqueConstraint("answer_id", "entity_type", "entity_name", "kind", name="uq_mention"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("provider_answers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # Snippets (for mentions) or URLs (for citations) supporting the detection
    evidence: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    answer: Mapped[ProviderAnswer] = relationship(back_populates="mentions")


REC_STATUSES = ("open", "planned", "in_progress", "completed", "dismissed")


class Recommendation(Base):
    """An action-plan item. Identified per project by a stable `key`, so its status
    survives re-audits; `detected` says whether the latest data still shows the issue."""

    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint("priority IN ('high', 'medium', 'low')", name="ck_rec_priority"),
        CheckConstraint("effort IN ('high', 'medium', 'low')", name="ck_rec_effort"),
        CheckConstraint("confidence IN ('high', 'medium', 'low')", name="ck_rec_confidence"),
        CheckConstraint(
            "status IN ('open', 'planned', 'in_progress', 'completed', 'dismissed')", name="ck_rec_status"
        ),
        UniqueConstraint("project_id", "key", name="uq_rec_project_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    effort: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    verify: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    detected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("website_audits.id", ondelete="SET NULL"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("visibility_runs.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    project: Mapped[Project] = relationship(back_populates="recommendations")


class FixDraft(Base):
    """A ready-to-review change generated for an action-plan item."""

    __tablename__ = "fix_drafts"
    __table_args__ = (CheckConstraint("format IN ('markdown', 'html', 'json-ld', 'text')", name="ck_fix_format"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Facts the generator could not verify from the site and left for the user to fill in
    placeholders: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    # Pages whose content the draft was based on
    sources: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # "template" (deterministic) or the model that wrote it
    generator: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


BACKLINK_KINDS = ("existing", "opportunity")
BACKLINK_STATUSES = ("found", "suggested", "in_progress", "completed", "verified", "not_found", "dismissed")


class BacklinkItem(Base):
    """An existing link/mention of the business, or a legitimate opportunity to earn one.

    kind="existing":    found on a real page during discovery (status "found"; re-checks keep it current)
    kind="opportunity": status suggested -> in_progress -> completed (by the business) -> verified / not_found
    """

    __tablename__ = "backlink_items"
    __table_args__ = (
        UniqueConstraint("project_id", "url", name="uq_backlink_project_url"),
        CheckConstraint("kind IN ('existing', 'opportunity')", name="ck_backlink_kind"),
        CheckConstraint(
            "status IN ('found', 'suggested', 'in_progress', 'completed', 'verified', 'not_found', 'dismissed')",
            name="ck_backlink_status",
        ),
        CheckConstraint("value_type IN ('backlink', 'mention', 'both', 'unknown')", name="ck_backlink_value"),
        CheckConstraint("link_rel IN ('follow', 'nofollow', 'ugc', 'sponsored', 'unknown')", name="ck_backlink_rel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    submission_url: Mapped[str | None] = mapped_column(String(2048))
    relevance: Mapped[str | None] = mapped_column(Text)  # why it fits this business and location
    why_it_helps: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    link_rel: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    discovered_via: Mapped[str | None] = mapped_column(String(300))  # search backend + query
    evidence: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    outreach: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_error: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    project: Mapped[Project] = relationship(back_populates="backlinks")


class ApiCache(Base):
    """Short-lived cache for paid lookups (web search results), keyed by a hash of the request."""

    __tablename__ = "api_cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[dict] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
