"""Cross-assistant overview for the dashboard.

Observed metrics come straight from recorded answers and crawls. Anything not yet
measured is reported as missing (None + a reason), never as zero.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Recommendation, VisibilityRun
from app.providers.registry import all_providers
from app.recommendations.engine import group_for
from app.services.recommendations import backlink_summary, latest_completed_audit, run_metrics
from app.services.user_keys import user_settings


def latest_run_per_provider(db: Session, project_id: int) -> dict[str, dict]:
    """{provider: {"completed": latest completed run or None, "latest": latest run of any status or None}}."""
    out: dict[str, dict] = {}
    runs = db.scalars(
        select(VisibilityRun).where(VisibilityRun.project_id == project_id).order_by(VisibilityRun.created_at.desc(), VisibilityRun.id.desc())
    ).all()
    for run in runs:
        slot = out.setdefault(run.provider, {"completed": None, "latest": run})
        if slot["completed"] is None and run.status == "completed":
            slot["completed"] = run
    return out


def build_overview(db: Session, project: Project) -> dict:
    per_provider = latest_run_per_provider(db, project.id)
    assistants, included, excluded = [], [], []
    competitor_rates: dict[str, list[float]] = {}
    other_businesses: dict[str, int] = {}
    for provider in all_providers(user_settings(db, project.user_id)):
        slot = per_provider.get(provider.name, {})
        run, latest = slot.get("completed"), slot.get("latest")
        row = {
            "provider": provider.name, "assistant": provider.assistant or provider.display_name,
            "configured": provider.is_configured(), "experience": provider.experience,
            "setup": None if provider.is_configured() else provider.setup_instructions(),
            "latest_status": latest.status if latest else None, "latest_error": latest.error if latest else None,
            "run_id": run.id if run else None, "tested_at": run.completed_at.isoformat() if run and run.completed_at else None,
            "model": run.model if run else None, "metrics": None,
        }
        if run:
            m = run_metrics(run)
            row["metrics"] = {k: m.get(k) for k in (
                "questions_tested", "questions_failed", "unbranded_mention_rate", "brand_mention_rate", "website_citation_rate",
                "average_position", "listed_in", "answers_with_list", "location_relevance_rate", "branded_unknown", "branded_questions")}
            if m.get("unbranded_mention_rate") is not None:
                included.append((row["assistant"], m["unbranded_mention_rate"]))
            else:
                excluded.append(f"{row['assistant']}: no questions without your brand name were tested")
            for e in m["entities"]:
                if e["entity_type"] == "competitor" and e["mention_rate"] is not None:
                    competitor_rates.setdefault(e["name"], []).append(e["mention_rate"])
            for b in m.get("other_businesses", []):
                other_businesses[b["name"]] = other_businesses.get(b["name"], 0) + b["answers"]
        else:
            excluded.append(f"{row['assistant']}: " + ("not tested yet" if provider.is_configured() else "no API key"))
        assistants.append(row)

    score = round(sum(v for _, v in included) / len(included), 1) if included else None
    audit = latest_completed_audit(db, project.id)
    local = ((audit.site_info or {}).get("local") if audit else None) or None
    open_recs = db.scalars(
        select(Recommendation).where(
            Recommendation.project_id == project.id, Recommendation.detected.is_(True),
            Recommendation.status.in_(("open", "planned", "in_progress")),
        )
    ).all()
    top = sorted(open_recs, key=lambda r: -r.score)[:5]
    return {
        "ai_visibility": {
            "score": score,
            "kind": "observed",
            "formula": "Average, across the assistants tested, of the unprompted mention rate (share of answers to questions "
                       "that don't name you which mention you anyway). Untested assistants are excluded, not counted as zero.",
            "included": [{"assistant": a, "unprompted_mention_rate": v} for a, v in included],
            "excluded": excluded,
        },
        "assistants": assistants,
        "website_health": {"score": audit.score if audit else None, "kind": "observed", "audit_id": audit.id if audit else None},
        "local_seo": {
            "score": local.get("score") if local else None,
            "kind": "observed",
            "measured": local.get("measured") if local else 0,
            "unknown": local.get("unknown") if local else 0,
            "failing": [c["label"] for c in (local or {}).get("checks", []) if c["status"] == "fail"],
            "inconsistencies": (local or {}).get("inconsistencies", []),
            "note": None if local else "Run a website audit to measure local SEO completeness.",
        },
        "backlinks": backlink_summary(db, project),
        "competitors": sorted(
            ({"name": n, "average_mention_rate": round(sum(v) / len(v), 1), "assistants": len(v)} for n, v in competitor_rates.items()),
            key=lambda x: -x["average_mention_rate"],
        ),
        "other_businesses": sorted(({"name": n, "answers": c} for n, c in other_businesses.items()), key=lambda x: -x["answers"])[:8],
        "top_actions": [{"id": r.id, "issue": r.issue, "priority": r.priority, "effort": r.effort, "group": group_for(r.key),
                         "blocking": r.blocking} for r in top],
    }
