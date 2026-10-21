from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.crawler.url_safety import UnsafeURLError, normalize_url

MAX_COMPETITORS = 10


def _clean_name(value: str) -> str:
    value = " ".join((value or "").split())
    if not value:
        raise ValueError("must not be empty")
    if len(value) > 200:
        raise ValueError("must be at most 200 characters")
    return value


def _optional_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return normalize_url(value)
    except UnsafeURLError as exc:
        raise ValueError(str(exc)) from exc


class CompetitorIn(BaseModel):
    name: str
    website_url: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _clean_name(v)

    @field_validator("website_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _optional_url(v)


def _clean_optional(v: str | None) -> str | None:
    v = " ".join((v or "").split())
    return v or None


class LocalProfile(BaseModel):
    """Local business details the owner provides. Only these (and facts found on the site) are ever
    used in generated schema markup or listings: nothing is invented."""

    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=2)
    service_area: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    opening_hours: str | None = Field(default=None, max_length=300)
    services: list[str] = Field(default_factory=list, max_length=30)
    profile_urls: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("city", "region", "service_area", "address", "opening_hours")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _clean_optional(v)

    @field_validator("country")
    @classmethod
    def _country(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        if not v:
            return None
        if len(v) != 2 or not v.isalpha():
            raise ValueError("Country must be a 2-letter code, e.g. IN or US")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        v = _clean_optional(v)
        if v and (sum(ch.isdigit() for ch in v) < 6 or not all(ch.isdigit() or ch in " +-().ext" for ch in v)):
            raise ValueError("Enter a valid phone number")
        return v

    @field_validator("services")
    @classmethod
    def _services(cls, v: list[str]) -> list[str]:
        out = []
        for item in v:
            item = _clean_optional(item)
            if item and len(item) <= 120 and item.lower() not in {x.lower() for x in out}:
                out.append(item)
        return out

    @field_validator("profile_urls")
    @classmethod
    def _profiles(cls, v: list[str]) -> list[str]:
        out = []
        for url in v:
            if url and url.strip():
                normalized = _optional_url(url)
                if normalized and normalized not in out:
                    out.append(normalized)
        return out


class ProjectBase(LocalProfile):
    industry: str | None = Field(default=None, max_length=200)
    competitors: list[CompetitorIn] = Field(default_factory=list, max_length=MAX_COMPETITORS)

    @field_validator("industry")
    @classmethod
    def _industry(cls, v: str | None) -> str | None:
        return _clean_optional(v)

    @field_validator("competitors", mode="before")
    @classmethod
    def _accept_strings(cls, v):
        # Allow ["Acme", "Globex"] as shorthand
        if isinstance(v, list):
            return [{"name": x} if isinstance(x, str) else x for x in v]
        return v


class ProjectCreate(ProjectBase):
    brand_name: str
    website_url: str

    @field_validator("brand_name")
    @classmethod
    def _brand(cls, v: str) -> str:
        return _clean_name(v)

    @field_validator("website_url")
    @classmethod
    def _website(cls, v: str) -> str:
        try:
            return normalize_url(v)
        except UnsafeURLError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def _unique_competitors(self):
        seen = {self.brand_name.lower()}
        unique = []
        for c in self.competitors:
            if c.name.lower() in seen:
                continue
            seen.add(c.name.lower())
            unique.append(c)
        self.competitors = unique
        return self


class ProjectUpdate(ProjectBase):
    pass


class RunCreate(BaseModel):
    provider: str = "anthropic"


class MultiRunCreate(BaseModel):
    # Assistants to test; empty = every configured assistant
    providers: list[str] = Field(default_factory=list, max_length=10)


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    website_url: str | None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    brand_name: str
    website_url: str
    domain: str
    industry: str | None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    service_area: str | None = None
    address: str | None = None
    phone: str | None = None
    opening_hours: str | None = None
    services: list[str] = []
    profile_urls: list[str] = []
    created_at: datetime
    competitors: list[CompetitorOut]


class AuditSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    status: str
    progress_message: str | None
    error: str | None
    score: float | None
    pages_crawled: int
    created_at: datetime
    completed_at: datetime | None


class AuditPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str
    status_code: int | None
    title: str | None
    meta_description: str | None
    canonical: str | None
    lang: str | None
    h1: list
    headings: list
    word_count: int
    internal_links: int
    external_links: int
    schema_types: list
    has_faq: bool
    faq_questions: list
    issues: list
    text_excerpt: str | None


class AuditDetailOut(AuditSummaryOut):
    site_info: dict
    checks: list
    content_gaps: list
    pages: list[AuditPageOut]


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    text: str
    category: str
    source: str
    created_at: datetime


class QuestionsGeneratedOut(BaseModel):
    questions: list[QuestionOut]
    source: str
    note: str | None


class RunSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    provider: str
    model: str
    status: str
    error: str | None
    total_questions: int
    completed_questions: int
    conditions: dict
    created_at: datetime
    completed_at: datetime | None


class MentionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    entity_type: str
    entity_name: str
    kind: str
    occurrences: int
    evidence: list


class AnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    question_id: int | None
    question_text: str
    question_category: str
    provider: str
    model: str
    answer_text: str | None
    sources: list
    brand_mentioned: bool
    website_cited: bool
    error: str | None
    latency_ms: int | None
    created_at: datetime
    mentions: list[MentionOut]
    # Derived on read (see services.recommendations.annotate_answer)
    branded_question: bool = False
    brand_unknown: bool = False
    brand_unknown_evidence: str | None = None
    position: int | None = None
    listed: int | None = None
    location_mentioned: bool | None = None
    recommended_businesses: list | None = None


class RunDetailOut(RunSummaryOut):
    metrics: dict
    answers: list[AnswerOut]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    audit_id: int | None
    run_id: int | None
    category: str
    priority: str  # impact
    effort: str
    confidence: str
    blocking: bool
    score: float
    status: str
    note: str | None
    issue: str
    why_it_matters: str
    action: str
    verify: str | None
    evidence: list
    detected: bool
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None
    status_updated_at: datetime | None
    created_at: datetime
    fix_available: bool = False
    group: str = "technical"  # technical | local | content | backlinks | ai_visibility


class FixDraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    recommendation_id: int
    title: str
    format: str
    content: str
    placeholders: list
    notes: str | None
    sources: list
    generator: str
    created_at: datetime


class RecommendationUpdate(BaseModel):
    status: Literal["open", "planned", "in_progress", "completed", "dismissed"] | None = None
    note: str | None = Field(default=None, max_length=2000)


class BacklinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    url: str
    domain: str
    title: str | None
    category: str
    submission_url: str | None
    relevance: str | None
    why_it_helps: str | None
    value_type: str
    link_rel: str
    discovered_via: str | None
    evidence: list
    outreach: str | None
    note: str | None
    last_checked_at: datetime | None
    check_error: str | None
    verified_at: datetime | None
    status_updated_at: datetime | None
    created_at: datetime


class BacklinkCreate(BaseModel):
    url: str = Field(max_length=2048)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        normalized = _optional_url(v)
        if not normalized:
            raise ValueError("Enter a URL")
        return normalized


class BacklinkUpdate(BaseModel):
    # "verified" / "found" / "not_found" are set only by an actual check, never by hand
    status: Literal["suggested", "in_progress", "completed", "dismissed"] | None = None
    note: str | None = Field(default=None, max_length=2000)
