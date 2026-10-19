from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.auth import current_user
from app.config import get_settings
from app.crawler import url_safety
from app.db import get_db
from app.fixes.generator import FixGenerationError, generate_fix, supports_fix
from app.limits import consume_quota, limit_writes, usage_summary
from app.models import (
    Competitor,
    FixDraft,
    Project,
    Question,
    Recommendation,
    User,
    VisibilityRun,
    WebsiteAudit,
)
from app.providers.registry import all_providers, first_configured, get_provider
from app.questions.generator import CATEGORY_LABELS, QuestionContext, generate_questions
from app.schemas import (
    AnswerOut,
    AuditDetailOut,
    AuditSummaryOut,
    FixDraftOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    QuestionOut,
    QuestionsGeneratedOut,
    RecommendationOut,
    RecommendationUpdate,
    RunCreate,
    RunDetailOut,
    RunSummaryOut,
)
from app.services import jobs
from app.services.recommendations import (
    annotate_answer,
    brand_spec_for,
    latest_completed_audit,
    latest_completed_run,
    refresh_recommendations,
    run_metrics,
)
from app.visibility.compare import compare_runs
from app.visibility.detection import domain_of

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Indirection so tests can stub DNS resolution.
resolve_target = url_safety.resolve_public_target


# Every lookup goes through the project's owner. Other users' objects return 404
# (not 403) so IDs can't be probed.
def _project_or_404(db: Session, project_id: int, user: User) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def _owned(obj, user: User, what: str):
    if obj is None or obj.project.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
    return obj


# --------------------------------------------------------------------------- meta
@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/providers")
def providers(user: User = Depends(current_user)) -> list[dict]:
    return [p.status() for p in all_providers()]


@router.get("/meta/question-categories")
def question_categories() -> dict:
    return CATEGORY_LABELS


@router.get("/usage")
def usage(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """The current user's AI usage over the last 24 hours, against their limits."""
    return usage_summary(db, user)


# --------------------------------------------------------------------------- projects
def _set_competitors(project: Project, competitors) -> None:
    existing = {c.name.lower(): c for c in project.competitors}
    keep, seen = [], {project.brand_name.lower()}
    for c in competitors:
        key = c.name.lower()
        if key in seen:
            continue
        seen.add(key)
        row = existing.get(key) or Competitor(name=c.name)
        row.website_url = c.website_url
        keep.append(row)
    project.competitors = keep


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Project:
    limit_writes(f"user:{user.id}")
    try:
        target = resolve_target(payload.website_url)
    except url_safety.UnsafeURLError as exc:
        raise HTTPException(422, str(exc)) from exc
    project = Project(
        user_id=user.id,
        brand_name=payload.brand_name,
        website_url=target.url,
        domain=url_safety.site_key(target.host),
        industry=payload.industry,
    )
    _set_competitors(project, payload.competitors)
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info("user %s created project %s for %s", user.id, project.id, project.domain)
    return project


@router.get("/projects")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    projects = db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .options(selectinload(Project.competitors))
        .order_by(Project.created_at.desc())
    ).all()
    out = []
    for p in projects:
        audit = latest_completed_audit(db, p.id)
        run = latest_completed_run(db, p.id)
        metrics = run_metrics(run) if run else None
        out.append(
            {
                **ProjectOut.model_validate(p).model_dump(mode="json"),
                "latest_audit_score": audit.score if audit else None,
                "latest_brand_mention_rate": metrics["brand_mention_rate"] if metrics else None,
                "latest_unprompted_mention_rate": metrics["unbranded_mention_rate"] if metrics else None,
                "latest_activity": max(
                    [x for x in [p.created_at, audit.created_at if audit else None, run.created_at if run else None] if x]
                ).isoformat(),
            }
        )
    return out


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Project:
    return _project_or_404(db, project_id, user)


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int, payload: ProjectUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Project:
    project = _project_or_404(db, project_id, user)
    project.industry = payload.industry
    _set_competitors(project, payload.competitors)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    project = _project_or_404(db, project_id, user)
    db.delete(project)
    db.commit()


# --------------------------------------------------------------------------- audits
@router.post("/projects/{project_id}/audits", response_model=AuditSummaryOut, status_code=status.HTTP_202_ACCEPTED)
def start_audit(
    project_id: int, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> WebsiteAudit:
    project = _project_or_404(db, project_id, user)
    limit_writes(f"user:{user.id}")
    active = db.scalar(
        select(WebsiteAudit.id).where(WebsiteAudit.project_id == project.id, WebsiteAudit.status.in_(("pending", "running")))
    )
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "An audit is already running for this project")
    audit = WebsiteAudit(project_id=project.id, status="pending", progress_message="Queued")
    db.add(audit)
    db.commit()
    db.refresh(audit)
    jobs.enqueue(background, jobs.run_audit_job, audit.id)
    return audit


@router.get("/projects/{project_id}/audits", response_model=list[AuditSummaryOut])
def list_audits(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _project_or_404(db, project_id, user)
    return db.scalars(
        select(WebsiteAudit).where(WebsiteAudit.project_id == project_id).order_by(WebsiteAudit.created_at.desc(), WebsiteAudit.id.desc())
    ).all()


@router.get("/audits/{audit_id}", response_model=AuditDetailOut)
def get_audit(audit_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> WebsiteAudit:
    return _owned(db.get(WebsiteAudit, audit_id), user, "Audit")


# --------------------------------------------------------------------------- questions
def _site_summary(db: Session, project: Project) -> str | None:
    audit = latest_completed_audit(db, project.id)
    if not audit or not audit.pages:
        return None
    parts = []
    for page in audit.pages[:6]:
        heads = "; ".join(h["text"] for h in page.headings[:8])
        parts.append(f"- {page.url}\n  title: {page.title or ''}\n  description: {page.meta_description or ''}\n  headings: {heads}")
    return "\n".join(parts)


@router.post("/projects/{project_id}/questions/generate", response_model=QuestionsGeneratedOut)
def generate(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = _project_or_404(db, project_id, user)
    limit_writes(f"user:{user.id}")
    provider = first_configured()
    if provider is not None:
        # Only AI generation costs money; the template fallback is free.
        consume_quota(db, user, "question_generation")
        db.commit()
    ctx = QuestionContext(
        brand=project.brand_name,
        industry=project.industry,
        competitors=[c.name for c in project.competitors],
        website_url=project.website_url,
        site_summary=_site_summary(db, project),
    )
    generated, note = generate_questions(ctx, provider)
    db.execute(update(Question).where(Question.project_id == project.id).values(is_active=False))
    rows = [Question(project_id=project.id, text=q.text, category=q.category, source=q.source) for q in generated]
    db.add_all(rows)
    db.commit()
    sources = {q.source for q in generated}
    return {
        "questions": rows,
        "source": "llm" if sources == {"llm"} else ("template" if sources == {"template"} else "mixed"),
        "note": note,
    }


@router.get("/projects/{project_id}/questions", response_model=list[QuestionOut])
def list_questions(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _project_or_404(db, project_id, user)
    return db.scalars(
        select(Question).where(Question.project_id == project_id, Question.is_active.is_(True)).order_by(Question.id)
    ).all()


# --------------------------------------------------------------------------- visibility runs
def _queue_run(
    db: Session, background: BackgroundTasks, user: User, project: Project, provider_name: str,
    questions: list[Question], extra_conditions: dict | None = None,
) -> VisibilityRun:
    """Shared by new runs and retests: same checks, quota and queueing."""
    try:
        provider = get_provider(provider_name)
    except KeyError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown provider '{provider_name}'") from None
    if not provider.is_configured():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "provider_not_configured", "message": f"{provider.display_name} is not configured.", "setup": provider.setup_instructions()},
        )
    if not questions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Generate questions before running a visibility test")
    active = db.scalar(
        select(VisibilityRun.id).where(VisibilityRun.project_id == project.id, VisibilityRun.status.in_(("pending", "running")))
    )
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "A visibility test is already running for this project")
    consume_quota(db, user, "visibility_run")
    run = VisibilityRun(
        project_id=project.id,
        provider=provider.name,
        model=provider.model,
        status="pending",
        total_questions=len(questions),
        conditions={**jobs.build_run_conditions(project, provider, list(questions)), **(extra_conditions or {})},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    jobs.enqueue(background, jobs.run_visibility_job, run.id)
    return run


@router.post("/projects/{project_id}/runs", response_model=RunSummaryOut, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    project_id: int,
    payload: RunCreate,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> VisibilityRun:
    project = _project_or_404(db, project_id, user)
    limit_writes(f"user:{user.id}")
    questions = db.scalars(
        select(Question).where(Question.project_id == project.id, Question.is_active.is_(True)).order_by(Question.id)
    ).all()[: get_settings().visibility_max_questions]
    return _queue_run(db, background, user, project, payload.provider, list(questions))


@router.post("/runs/{run_id}/retest", response_model=RunSummaryOut, status_code=status.HTTP_202_ACCEPTED)
def retest_run(
    run_id: int, background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> VisibilityRun:
    """Ask the exact same questions again, so the new run can be compared like-for-like."""
    base = _owned(db.get(VisibilityRun, run_id), user, "Run")
    limit_writes(f"user:{user.id}")
    ids = (base.conditions or {}).get("question_ids") or [a.question_id for a in base.answers if a.question_id]
    by_id = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(ids), Question.project_id == base.project_id))}
    questions = [by_id[i] for i in ids if i in by_id]
    if not questions:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The questions from that run no longer exist; start a new test instead")
    return _queue_run(db, background, user, base.project, base.provider, questions, {"retest_of": base.id})


@router.get("/projects/{project_id}/runs", response_model=list[RunSummaryOut])
def list_runs(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _project_or_404(db, project_id, user)
    return db.scalars(
        select(VisibilityRun).where(VisibilityRun.project_id == project_id).order_by(VisibilityRun.created_at.desc(), VisibilityRun.id.desc())
    ).all()


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    run = _owned(db.get(VisibilityRun, run_id), user, "Run")
    data = RunSummaryOut.model_validate(run).model_dump()
    data["metrics"] = run_metrics(run)
    brand = brand_spec_for(run)
    data["answers"] = [
        {**AnswerOut.model_validate(a).model_dump(), **annotate_answer(a, brand)} for a in run.answers
    ]
    return data


# --------------------------------------------------------------------------- dashboard / recommendations
@router.get("/projects/{project_id}/dashboard")
def dashboard(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    project = _project_or_404(db, project_id, user)
    audit = latest_completed_audit(db, project.id)
    run = latest_completed_run(db, project.id)
    recent_audits = db.scalars(
        select(WebsiteAudit).where(WebsiteAudit.project_id == project.id).order_by(WebsiteAudit.created_at.desc(), WebsiteAudit.id.desc()).limit(5)
    ).all()
    recent_runs = db.scalars(
        select(VisibilityRun).where(VisibilityRun.project_id == project.id).order_by(VisibilityRun.created_at.desc(), VisibilityRun.id.desc()).limit(5)
    ).all()
    # Open work only: still detected and not completed or dismissed.
    rec_counts = dict(
        db.execute(
            select(Recommendation.priority, func.count())
            .where(
                Recommendation.project_id == project.id,
                Recommendation.detected.is_(True),
                Recommendation.status.in_(("open", "planned", "in_progress")),
            )
            .group_by(Recommendation.priority)
        ).all()
    )
    status_counts = dict(
        db.execute(
            select(Recommendation.status, func.count()).where(Recommendation.project_id == project.id).group_by(Recommendation.status)
        ).all()
    )
    resolved_count = db.scalar(
        select(func.count()).select_from(Recommendation).where(Recommendation.project_id == project.id, Recommendation.detected.is_(False))
    )
    question_count = db.scalar(
        select(func.count()).select_from(Question).where(Question.project_id == project.id, Question.is_active.is_(True))
    )
    return {
        "project": ProjectOut.model_validate(project).model_dump(mode="json"),
        "providers": [p.status() for p in all_providers()],
        "usage": usage_summary(db, user),
        "latest_audit": AuditSummaryOut.model_validate(audit).model_dump(mode="json") if audit else None,
        "latest_audit_checks": audit.checks if audit else [],
        "latest_run": RunSummaryOut.model_validate(run).model_dump(mode="json") if run else None,
        "latest_run_metrics": run_metrics(run) if run else None,
        "recent_audits": [AuditSummaryOut.model_validate(a).model_dump(mode="json") for a in recent_audits],
        "recent_runs": [RunSummaryOut.model_validate(r).model_dump(mode="json") for r in recent_runs],
        "recommendation_counts": {k: rec_counts.get(k, 0) for k in ("high", "medium", "low")},
        "action_plan": {
            **{k: status_counts.get(k, 0) for k in ("open", "planned", "in_progress", "completed", "dismissed")},
            "no_longer_detected": resolved_count,
        },
        "active_question_count": question_count,
        "competitor_domains": {c.name: domain_of(c.website_url) for c in project.competitors},
    }


def _rec_out(rec: Recommendation) -> dict:
    data = RecommendationOut.model_validate(rec).model_dump()
    data["fix_available"] = supports_fix(rec.key)
    return data


@router.get("/projects/{project_id}/recommendations", response_model=list[RecommendationOut])
def list_recommendations(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _project_or_404(db, project_id, user)
    rows = db.scalars(select(Recommendation).where(Recommendation.project_id == project_id)).all()
    # Still-detected items first, by score (blocking root causes, then impact × confidence ÷ effort).
    return [_rec_out(r) for r in sorted(rows, key=lambda r: (not r.detected, -r.score, r.id))]


@router.patch("/recommendations/{rec_id}", response_model=RecommendationOut)
def update_recommendation(
    rec_id: int, payload: RecommendationUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    rec = _owned(db.get(Recommendation, rec_id), user, "Recommendation")
    if payload.status is not None and payload.status != rec.status:
        rec.status = payload.status
        rec.status_updated_at = datetime.now(timezone.utc)
    if "note" in payload.model_fields_set:
        rec.note = (payload.note or "").strip() or None
    db.commit()
    db.refresh(rec)
    return _rec_out(rec)


@router.post("/projects/{project_id}/recommendations/refresh", response_model=list[RecommendationOut])
def refresh(project_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id, user)
    refresh_recommendations(db, project)
    return list_recommendations(project_id, user, db)


# --------------------------------------------------------------------------- fix generator
@router.get("/recommendations/{rec_id}/fixes", response_model=list[FixDraftOut])
def list_fixes(rec_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = _owned(db.get(Recommendation, rec_id), user, "Recommendation")
    return db.scalars(select(FixDraft).where(FixDraft.recommendation_id == rec.id).order_by(FixDraft.id.desc())).all()


@router.post("/recommendations/{rec_id}/fixes", response_model=FixDraftOut, status_code=status.HTTP_201_CREATED)
def create_fix(rec_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> FixDraft:
    """Draft a ready-to-review change for an action-plan item, grounded in the crawled site content."""
    rec = _owned(db.get(Recommendation, rec_id), user, "Recommendation")
    limit_writes(f"user:{user.id}")
    if not supports_fix(rec.key):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fix generator is available for this item yet")
    try:
        draft = generate_fix(db, rec, user=user)
    except FixGenerationError as exc:
        db.rollback()
        raise HTTPException(exc.status_code, {"code": exc.code, "message": exc.message}) from exc
    db.add(draft)
    db.commit()
    db.refresh(draft)
    logger.info("user %s generated fix %s (%s) for %s", user.id, draft.id, draft.generator, rec.key)
    return draft


# --------------------------------------------------------------------------- compare
@router.get("/projects/{project_id}/compare")
def compare(project_id: int, base: int, target: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    """Compare two completed visibility runs of the same project, on the questions they share."""
    project = _project_or_404(db, project_id, user)
    runs = {}
    for name, rid in (("base", base), ("target", target)):
        run = db.get(VisibilityRun, rid)
        if run is None or run.project_id != project.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Run {rid} not found in this project")
        if run.status != "completed":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Run #{rid} hasn't completed, so it can't be compared yet")
        runs[name] = run
    if base == target:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose two different runs to compare")
    earlier, later = sorted(runs.values(), key=lambda r: r.created_at)
    resolved = db.scalars(
        select(Recommendation).where(
            Recommendation.project_id == project.id,
            Recommendation.resolved_at.is_not(None),
            Recommendation.resolved_at >= earlier.created_at,
            Recommendation.resolved_at <= (later.completed_at or later.created_at),
        )
    ).all()
    return compare_runs(runs["base"], runs["target"], resolved)
