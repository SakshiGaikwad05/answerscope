from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BacklinkItem, Project, Question, Recommendation, VisibilityRun, WebsiteAudit
from app.recommendations.engine import RecInput, build_recommendations, is_evaluated
from app.visibility.detection import EntitySpec, detect_brand_unknown, question_names_brand
from app.visibility.metrics import AnswerRecord, compute_run_metrics
from app.visibility.position import brand_position, location_terms, mentions_location


def brand_spec_for(run: VisibilityRun) -> EntitySpec:
    cond = run.conditions or {}
    return EntitySpec(name=cond.get("brand", run.project.brand_name), entity_type="brand", domain=cond.get("domain", run.project.domain))


def annotate_answer(answer, brand: EntitySpec, location: dict | None = None) -> dict:
    """Derived, re-computable facts about an answer (not stored, so detection fixes apply to old runs)."""
    text = answer.answer_text or ""
    unknown = None if answer.error else detect_brand_unknown(text, brand)
    pos = None if answer.error else brand_position(text, brand)
    return {
        "branded_question": question_names_brand(answer.question_text, brand),
        "brand_unknown": unknown is not None,
        "brand_unknown_evidence": unknown,
        # Position in the answer's recommendation list; None when the answer has no list
        "position": pos["position"] if pos else None,
        "listed": pos["listed"] if pos else None,
        # None when no location is on file for the business
        "location_mentioned": None if answer.error else mentions_location(text, location_terms(location)),
        "recommended_businesses": ((answer.analysis or {}).get("businesses") if getattr(answer, "analysis", None) else None),
    }


def _record(a, extra: dict) -> AnswerRecord:
    return AnswerRecord(
        category=a.question_category,
        error=a.error,
        brand_mentioned=a.brand_mentioned,
        website_cited=a.website_cited,
        detections={(m.entity_type, m.entity_name, m.kind) for m in a.mentions},
        branded=extra["branded_question"],
        brand_unknown=extra["brand_unknown"],
        position=extra["position"],
        listed=extra["listed"],
        location_mentioned=extra["location_mentioned"],
        recommended=extra["recommended_businesses"],
    )


def _assistant_name(provider: str) -> str:
    from app.providers.registry import PROVIDER_FACTORIES, get_provider

    try:
        return get_provider(provider).assistant or provider if provider in PROVIDER_FACTORIES else provider
    except Exception:  # noqa: BLE001
        return provider


def latest_completed_runs_per_provider(db: Session, project_id: int) -> list[VisibilityRun]:
    runs = db.scalars(
        select(VisibilityRun)
        .where(VisibilityRun.project_id == project_id, VisibilityRun.status == "completed")
        .order_by(VisibilityRun.created_at.desc(), VisibilityRun.id.desc())
    ).all()
    latest: dict[str, VisibilityRun] = {}
    for r in runs:
        latest.setdefault(r.provider, r)
    return list(latest.values())


def run_metrics(run: VisibilityRun, answers=None, competitors: list[str] | None = None) -> dict:
    """Metrics for a run, optionally restricted to some of its answers / competitors (for comparisons)."""
    cond = run.conditions or {}
    brand = brand_spec_for(run)
    records = []
    location = cond.get("location")
    for a in run.answers if answers is None else answers:
        records.append(_record(a, annotate_answer(a, brand, location)))
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
    """Rebuild the project's recommendations from its latest audit and every assistant's latest run."""
    audit = latest_completed_audit(db, project.id)
    run = None
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
        inp.local = info.get("local")
    inp.backlinks = backlink_summary(db, project)
    # Combine the latest completed run of EVERY assistant, so advice reflects all of them;
    # evidence is labelled with the assistant it came from.
    runs = latest_completed_runs_per_provider(db, project.id)
    if runs:
        run = max(runs, key=lambda r: (r.created_at, r.id))  # newest run, used as the items' source link
        records, inp.answers = [], []
        names = {}
        for r in runs:
            names[r.provider] = _assistant_name(r.provider)
            brand = brand_spec_for(r)
            for a in r.answers:
                extra = annotate_answer(a, brand, (r.conditions or {}).get("location"))
                records.append(_record(a, extra))
                label = f"[{names[r.provider]}] " if len(runs) > 1 else ""
                inp.answers.append(
                    {
                        "question": label + a.question_text,
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
        competitors = sorted({c["name"] for r in runs for c in (r.conditions or {}).get("competitors", [])})
        inp.run_metrics = compute_run_metrics(records, brand=project.brand_name, competitors=competitors)
        inp.run_metrics["assistants"] = sorted(names.values())

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


def backlink_summary(db: Session, project: Project) -> dict:
    items = db.scalars(select(BacklinkItem).where(BacklinkItem.project_id == project.id)).all()
    if not items:
        return {"discovered": False}
    opp = [i for i in items if i.kind == "opportunity"]
    return {
        "discovered": True,
        "backend": next((i.discovered_via.split(":")[0] for i in items if i.discovered_via), None),
        "existing": sum(1 for i in items if i.kind == "existing"),
        "opportunities": len(opp),
        "suggested": sum(1 for i in opp if i.status == "suggested"),
        "verified": sum(1 for i in opp if i.status == "verified"),
        "top": [i.url for i in opp if i.status == "suggested"][:5],
    }
