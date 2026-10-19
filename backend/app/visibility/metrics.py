"""Visibility metrics, computed only from recorded provider answers.

Definitions (shown in the UI as well):

* questions_tested      - answers successfully returned by the provider in the run.
* unbranded_mention_rate - HEADLINE. % of answers to questions that do NOT name the
                          brand which mention it anyway, i.e. the AI brings it up unprompted.
* branded questions     - questions that name the brand. Answers almost always repeat the
                          name, so they're reported separately: how many show the AI knows
                          the brand vs. say it couldn't find / doesn't know it.
* brand_mention_rate    - % of all tested answers that genuinely mention the brand. An answer
                          that only says "I couldn't find information about X" is NOT a mention.
* website_citation_rate - % of tested answers that cite or link the brand's website.
* entity mention / citation rates - the same, for each competitor, on the same answers.
* share_of_voice        - brand's mentioning answers / all entities' mentioning answers.

Rates are None when no answers were successfully tested (never a placeholder).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnswerRecord:
    category: str
    error: str | None
    brand_mentioned: bool
    website_cited: bool
    # {(entity_type, entity_name, kind), ...}
    detections: set[tuple[str, str, str]]
    branded: bool = False  # the question itself names the brand
    brand_unknown: bool = False  # the answer says the AI couldn't find / doesn't know the brand

    @property
    def mentions_brand(self) -> bool:
        """A real mention: the name appears and the answer doesn't say the brand is unknown."""
        return self.brand_mentioned and not self.brand_unknown


def pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def compute_run_metrics(records: list[AnswerRecord], brand: str, competitors: list[str]) -> dict:
    tested = [r for r in records if r.error is None]
    n = len(tested)

    def entity_stats(entity_type: str, name: str) -> dict:
        mentioned = sum(1 for r in tested if (entity_type, name, "mention") in r.detections)
        cited = sum(1 for r in tested if (entity_type, name, "citation") in r.detections)
        return {
            "name": name,
            "entity_type": entity_type,
            "answers_mentioning": mentioned,
            "answers_citing": cited,
            "mention_rate": pct(mentioned, n),
            "citation_rate": pct(cited, n),
        }

    brand_mentions = sum(1 for r in tested if r.mentions_brand)
    brand_citations = sum(1 for r in tested if r.website_cited)
    brand_stats = entity_stats("brand", brand)
    brand_stats["answers_mentioning"] = brand_mentions
    brand_stats["answers_citing"] = brand_citations
    brand_stats["mention_rate"] = pct(brand_mentions, n)
    brand_stats["citation_rate"] = pct(brand_citations, n)
    competitor_stats = [entity_stats("competitor", c) for c in competitors]

    total_mentioning = brand_mentions + sum(c["answers_mentioning"] for c in competitor_stats)
    for entity in [brand_stats, *competitor_stats]:
        entity["share_of_voice"] = pct(entity["answers_mentioning"], total_mentioning)

    categories: dict[str, dict] = {}
    for r in tested:
        c = categories.setdefault(r.category, {"category": r.category, "tested": 0, "brand_mentions": 0, "website_citations": 0})
        c["tested"] += 1
        c["brand_mentions"] += int(r.mentions_brand)
        c["website_citations"] += int(r.website_cited)
    for c in categories.values():
        c["mention_rate"] = pct(c["brand_mentions"], c["tested"])
        c["citation_rate"] = pct(c["website_citations"], c["tested"])

    competitor_only = sum(
        1
        for r in tested
        if not r.mentions_brand and any(d[0] == "competitor" and d[2] == "mention" for d in r.detections)
    )
    unbranded = [r for r in tested if not r.branded]
    branded = [r for r in tested if r.branded]
    unbranded_mentions = sum(1 for r in unbranded if r.mentions_brand)
    branded_known = sum(1 for r in branded if r.mentions_brand)
    branded_unknown = sum(1 for r in branded if r.brand_unknown)
    return {
        # Headline: does the AI bring the brand up when the question doesn't name it?
        "unbranded_questions": len(unbranded),
        "unbranded_mentions": unbranded_mentions,
        "unbranded_mention_rate": pct(unbranded_mentions, len(unbranded)),
        # Questions that name the brand: does the AI know it, or say it can't find it?
        "branded_questions": len(branded),
        "branded_known": branded_known,
        "branded_known_rate": pct(branded_known, len(branded)),
        "brand_unknown_answers": sum(1 for r in tested if r.brand_unknown),
        "branded_unknown": branded_unknown,
        "total_questions": len(records),
        "questions_tested": n,
        "questions_failed": len(records) - n,
        "brand_mentions": brand_mentions,
        "website_citations": brand_citations,
        "brand_mention_rate": pct(brand_mentions, n),
        "website_citation_rate": pct(brand_citations, n),
        "answers_with_competitor_but_not_brand": competitor_only,
        "entities": [brand_stats, *competitor_stats],
        "by_category": sorted(categories.values(), key=lambda c: c["category"]),
    }
