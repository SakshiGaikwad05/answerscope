"""Compare two visibility runs like-for-like.

Only questions answered successfully in BOTH runs are compared (matched by
question text), so a changed question set can't masquerade as a change in
visibility. Differences in provider, model or settings are reported as
comparability warnings. A change of a single answer is flagged as possibly
normal variation: AI answers vary between runs even when nothing changed.

The comparison shows what changed, never why. Edits to the site, model updates
and ordinary answer variability all look the same in two runs.
"""

from __future__ import annotations

import re

from app.models import ProviderAnswer, Recommendation, VisibilityRun
from app.services.recommendations import annotate_answer, brand_spec_for, run_metrics

# Settings that must match for the runs to be directly comparable
CONDITION_KEYS = {
    "provider": "AI provider",
    "model": "model",
    "effort": "effort setting",
    "web_search": "web search setting",
    "system_prompt": "system prompt",
    "brand": "brand name",
    "domain": "website domain",
}


def question_key(text: str) -> str:
    return re.sub(r"[\s?.!]+$", "", re.sub(r"\s+", " ", (text or "").strip().lower()))


def _answers_by_question(run: VisibilityRun) -> dict[str, ProviderAnswer]:
    return {question_key(a.question_text): a for a in run.answers if not a.error}


def _state(answer: ProviderAnswer, brand) -> dict:
    extra = annotate_answer(answer, brand)
    return {
        "brand_mentioned": answer.brand_mentioned and not extra["brand_unknown"],
        "website_cited": answer.website_cited,
        "brand_unknown": extra["brand_unknown"],
        "competitors": sorted({m.entity_name for m in answer.mentions if m.entity_type == "competitor" and m.kind == "mention"}),
    }


def comparability(base: VisibilityRun, target: VisibilityRun) -> list[str]:
    """Human-readable reasons the two runs aren't measured under identical conditions."""
    a, b = base.conditions or {}, target.conditions or {}
    warnings = []
    for key, label in CONDITION_KEYS.items():
        if a.get(key) != b.get(key):
            warnings.append(f"Different {label}: {a.get(key)!r} vs {b.get(key)!r}.")
    comps_a = {c["name"] for c in a.get("competitors", [])}
    comps_b = {c["name"] for c in b.get("competitors", [])}
    if comps_a != comps_b:
        warnings.append("Different competitor lists; only competitors tracked in both runs are compared.")
    return warnings


def _delta(base_value, target_value):
    if base_value is None or target_value is None:
        return None
    return round(target_value - base_value, 1)


def compare_runs(base: VisibilityRun, target: VisibilityRun, resolved_items: list[Recommendation] | None = None) -> dict:
    brand = brand_spec_for(target)
    base_answers, target_answers = _answers_by_question(base), _answers_by_question(target)
    shared = [k for k in target_answers if k in base_answers]
    comps_base = {c["name"] for c in (base.conditions or {}).get("competitors", [])}
    shared_comps = [c["name"] for c in (target.conditions or {}).get("competitors", []) if c["name"] in comps_base]

    m_base = run_metrics(base, answers=[base_answers[k] for k in shared], competitors=shared_comps)
    m_target = run_metrics(target, answers=[target_answers[k] for k in shared], competitors=shared_comps)
    n = len(shared)

    def metric(key: str, label: str, count_key: str | None = None) -> dict:
        row = {"key": key, "label": label, "base": m_base.get(key), "target": m_target.get(key), "delta_pts": _delta(m_base.get(key), m_target.get(key))}
        if count_key:
            row["base_count"], row["target_count"] = m_base.get(count_key), m_target.get(count_key)
            row["answers_changed"] = None if row["base_count"] is None else abs(row["target_count"] - row["base_count"])
        return row

    metrics = [
        metric("unbranded_mention_rate", "Unprompted mention rate", "unbranded_mentions"),
        metric("brand_mention_rate", "Brand mention rate (all questions)", "brand_mentions"),
        metric("website_citation_rate", "Website citation rate", "website_citations"),
        metric("branded_known_rate", "AI knows you (questions naming you)", "branded_known"),
    ]
    for row in metrics:
        # One answer either way is within normal run-to-run variation.
        row["may_be_noise"] = row.get("answers_changed") is not None and row["answers_changed"] <= 1

    entities = []
    by_name_base = {e["name"]: e for e in m_base["entities"]}
    for e in m_target["entities"]:
        b = by_name_base.get(e["name"], {})
        entities.append({
            "name": e["name"],
            "entity_type": e["entity_type"],
            "base_mention_rate": b.get("mention_rate"),
            "target_mention_rate": e["mention_rate"],
            "delta_pts": _delta(b.get("mention_rate"), e["mention_rate"]),
            "base_citation_rate": b.get("citation_rate"),
            "target_citation_rate": e["citation_rate"],
        })

    changes = {k: [] for k in ("gained_mention", "lost_mention", "gained_citation", "lost_citation", "now_known", "now_unknown")}
    competitor_changes = []
    unchanged = 0
    for k in shared:
        before, after = _state(base_answers[k], brand), _state(target_answers[k], brand)
        q = target_answers[k].question_text
        changed = False
        for flag, up, down in (("brand_mentioned", "gained_mention", "lost_mention"), ("website_cited", "gained_citation", "lost_citation")):
            if after[flag] and not before[flag]:
                changes[up].append(q); changed = True
            elif before[flag] and not after[flag]:
                changes[down].append(q); changed = True
        if before["brand_unknown"] and not after["brand_unknown"]:
            changes["now_known"].append(q); changed = True
        elif after["brand_unknown"] and not before["brand_unknown"]:
            changes["now_unknown"].append(q); changed = True
        gained = [c for c in after["competitors"] if c not in before["competitors"] and c in shared_comps]
        lost = [c for c in before["competitors"] if c not in after["competitors"] and c in shared_comps]
        if gained or lost:
            competitor_changes.append({"question": q, "gained": gained, "lost": lost})
            changed = True
        unchanged += not changed

    return {
        "base": {"id": base.id, "created_at": base.created_at.isoformat(), "model": base.model, "questions_tested": len(base_answers)},
        "target": {"id": target.id, "created_at": target.created_at.isoformat(), "model": target.model, "questions_tested": len(target_answers)},
        "questions_compared": n,
        "questions_only_in_base": len([k for k in base_answers if k not in target_answers]),
        "questions_only_in_target": len([k for k in target_answers if k not in base_answers]),
        "comparable": not comparability(base, target),
        "warnings": comparability(base, target),
        "one_answer_pts": round(100 / n, 1) if n else None,
        "metrics": metrics,
        "entities": entities,
        "question_changes": changes,
        "competitor_changes": competitor_changes,
        "unchanged_questions": unchanged,
        "resolved_between": [
            {"id": r.id, "issue": r.issue, "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None, "status": r.status}
            for r in (resolved_items or [])
        ],
    }
