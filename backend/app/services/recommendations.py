from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Question, Recommendation, VisibilityRun, WebsiteAudit
from app.recommendations.engine import RecInput, build_recommendations, is_evaluated
from app.visibility.detection import EntitySpec, detect_brand_unknown, question_names_brand
from app.visibility.metrics import AnswerRecord, compute_run_metrics


def brand_spec_for(run: VisibilityRun) -> EntitySpec:
    cond = run.conditions or {}
    return EntitySpec(name=cond.get("brand", run.project.brand_name), entity_type="brand", domain=cond.get("domain", run.project.domain))


def annotate_answer(answer, brand: EntitySpec) -> dict:
    """Derived, re-computable facts about an answer (not stored, so detection fixes apply to old runs)."""
    unknown = None if answer.error else detect_brand_unknown(answer.answer_text or "", brand)
    return {"branded_question": question_names_brand(answer.question_text, brand), "brand_unknown": unknown is not None, "brand_unknown_evidence": unknown}


def run_metrics(run: VisibilityRun, answers=None, competitors: list[str] | None = None) -> dict:
    """Metrics for a run, optionally restricted to some of its answers / competitors (for comparisons)."""
    cond = run.conditions or {}
    brand = brand_spec_for(run)
    records = []
    for a in run.answers if answers is None else answers:
        extra = annotate_answer(a, brand)
        records.append(
            AnswerRecord(
                category=a.question_category,
                error=a.error,
                brand_mentioned=a.brand_mentioned,
                website_cited=a.website_cited,
                detections={(m.entity_type, m.entity_name, m.kind) for m in a.mentions},
                branded=extra["branded_question"],
                brand_unknown=extra["brand_unknown"],
            )
        )
    return compute_run_metrics(
        records,
        brand=cond.get("brand", run.project.brand_name),
        competitors=competitors if competitors is not None else [c["name"] for c in cond.get("competitors", [])],
    )


def latest_completed_audit(db: Session, project_id: int) -> WebsiteAudit | None:
    return db.scalar(
        select(WebsiteAudit)
        .where(WebsiteAudit.project_id == project_id, WebsiteAudit.status == "completed")
        .order_by(WebsiteAudit.created_at.desc(), WebsiteAudit.id.desc())
        .limit(1)
    )


def latest_completed_run(db: Session, project_id: int) -> VisibilityRun | None:
    return db.scalar(
        select(VisibilityRun)
        .where(VisibilityRun.project_id == project_id, VisibilityRun.status == "completed")
        .order_by(VisibilityRun.created_at.desc(), VisibilityRun.id.desc())
        .limit(1)
    )


def refresh_recommendations(db: Session, project: Project) -> list[Recommendation]:
    """Rebuild the project's recommendations from its latest completed audit and run."""
    audit = latest_completed_audit(db, project.id)
    run = latest_completed_run(db, project.id)
    questions = list(
        db.scalars(
            select(Question.text).where(Question.project_id == project.id, Question.is_active.is_(True)).order_by(Question.id)
        )
    )
    inp = RecInput(brand=project.brand_name, domain=project.domain, competitors=[c.name for c in project.competitors], questions=questions)
    if audit:
        inp.audit_checks = audit.checks
        inp.content_gaps = audit.content_gaps
        inp.page_issues = {p.url: p.issues for p in audit.pages}
        info = audit.site_info or {}
        inp.homepage_js_only = bool(info.get("js_rendered_shell"))
        # Content checks are only unmeasurable if the shell couldn't be rendered in a browser.
        inp.js_shell_homepage = inp.homepage_js_only and not info.get("homepage_rendered")
    if run:
        inp.run_metrics = run_metrics(run)
        brand = brand_spec_for(run)
        inp.answers = []
        for a in run.answers:
            extra = annotate_answer(a, brand)
            inp.answers.append(
                {
                    "question": a.question_text,
                    "category": a.question_category,
                    # A real mention: "I couldn't find information about X" doesn't count.
                    "brand_mentioned": a.brand_mentioned and not extra["brand_unknown"],
                    "website_cited": a.website_cited,
                    "error": a.error,
                    "sources": a.sources,
                    "competitors_mentioned": sorted(
                        {m.entity_name for m in a.mentions if m.entity_type == "competitor" and m.kind == "mention"}
                    ),
                    **extra,
                }
            )

    now = datetime.now(timezone.utc)
    existing = {r.key: r for r in db.scalars(select(Recommendation).where(Recommendation.project_id == project.id))}
    fresh = build_recommendations(inp)
    fresh_keys = set()
    for rec in fresh:
        fresh_keys.add(rec["key"])
        row = existing.get(rec["key"])
        if row is None:
            row = Recommendation(project_id=project.id, key=rec["key"], status="open", first_detected_at=now)
            db.add(row)
        # Content is refreshed from the latest evidence; the user's status and note are kept.
        row.audit_id = audit.id if audit and rec["source"] == "audit" else None
        row.run_id = run.id if run and rec["source"] == "visibility" else None
        for attr in ("category", "priority", "effort", "confidence", "blocking", "score", "issue", "why_it_matters", "action", "verify", "evidence"):
            setattr(row, attr, rec[attr])
        row.detected = True
        row.last_detected_at = now
        row.resolved_at = None
    for key, row in existing.items():
        # Only mark resolved when the latest data actually re-checked this issue.
        if key not in fresh_keys and row.detected and is_evaluated(key, inp):
            row.detected = False
            row.resolved_at = now
    db.commit()
    return list(db.scalars(select(Recommendation).where(Recommendation.project_id == project.id)))
