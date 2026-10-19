"""Generate the questions potential customers might ask an AI assistant.

Uses a configured LLM provider when available; otherwise falls back to a
deterministic template set. Every question records its `source` so the UI can
show which one produced it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.providers.base import AIProvider, ProviderError

logger = logging.getLogger(__name__)

CATEGORIES = [
    "best_in_category",
    "recommendation",
    "alternatives",
    "comparison",
    "pricing",
    "features",
    "use_case",
    "beginner",
]
CATEGORY_LABELS = {
    "best_in_category": "Best in category",
    "recommendation": "Brand recommendation",
    "alternatives": "Alternatives",
    "comparison": "Comparison",
    "pricing": "Pricing",
    "features": "Features",
    "use_case": "Use case",
    "beginner": "Beginner-friendly",
}
TARGET_COUNT = 20


@dataclass
class GeneratedQuestion:
    text: str
    category: str
    source: str  # "llm" | "template"


@dataclass
class QuestionContext:
    brand: str
    industry: str | None
    competitors: list[str]
    website_url: str
    site_summary: str | None = None  # homepage title/description/headings, if audited


def _category_phrase(ctx: QuestionContext) -> str:
    if ctx.industry and ctx.industry.strip():
        return ctx.industry.strip()
    return f"products like {ctx.brand}"


def template_questions(ctx: QuestionContext) -> list[GeneratedQuestion]:
    """Deterministic fallback: 20 questions built from brand, category and competitors."""
    brand = ctx.brand.strip()
    cat = _category_phrase(ctx)
    has_industry = bool(ctx.industry and ctx.industry.strip())
    comps = [c.strip() for c in ctx.competitors if c.strip()]
    c1 = comps[0] if comps else None
    c2 = comps[1] if len(comps) > 1 else None

    q: list[tuple[str, str]] = [
        ("best_in_category", f"What are the best {cat} in 2026?" if has_industry else f"What are the best {cat}?"),
        ("best_in_category", f"What are the top-rated {cat} for small businesses?"),
        ("best_in_category", f"Which {cat} do experts recommend most?"),
        ("recommendation", f"Is {brand} a good choice?"),
        ("recommendation", f"Would you recommend {brand}? What are its pros and cons?"),
        ("recommendation", f"What do customers say about {brand}?"),
        ("alternatives", f"What are the best alternatives to {brand}?"),
        ("alternatives", f"What are some cheaper alternatives to {c1}?" if c1 else f"What are some cheaper alternatives to {brand}?"),
        ("comparison", f"{brand} vs {c1}: which is better?" if c1 else f"How does {brand} compare to other {cat}?"),
        ("comparison", f"{brand} vs {c2}: what are the key differences?" if c2 else f"What makes {brand} different from its competitors?"),
        ("comparison", f"Compare {brand}, {c1} and {c2}." if c1 and c2 else f"Which is better for a growing team: {brand} or its main competitors?"),
        ("pricing", f"How much does {brand} cost?"),
        ("pricing", f"Does {brand} have a free plan or free trial?"),
        ("pricing", f"Which {cat} offer the best value for money?"),
        ("features", f"What are the main features of {brand}?"),
        ("features", f"What features should I look for when choosing {cat}?"),
        ("use_case", f"What is {brand} used for?"),
        ("use_case", f"Which {cat} are best for startups?"),
        ("beginner", f"What are the easiest {cat} for beginners?"),
        ("beginner", f"How do I get started with {brand}?"),
    ]
    return [GeneratedQuestion(text=t, category=c, source="template") for c, t in q][:TARGET_COUNT]


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                },
                "required": ["text", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You help companies understand how they appear in AI assistant answers. "
    "You write realistic questions that real potential customers type into AI assistants "
    "such as ChatGPT, Claude, Gemini or Perplexity when researching a purchase."
)


def _llm_prompt(ctx: QuestionContext) -> str:
    competitors = ", ".join(ctx.competitors) if ctx.competitors else "(none provided)"
    lines = [
        f"Brand: {ctx.brand}",
        f"Website: {ctx.website_url}",
        f"Industry / category: {ctx.industry or '(not provided - infer it from the website summary)'}",
        f"Known competitors: {competitors}",
    ]
    if ctx.site_summary:
        lines.append(f"Website summary (from a crawl):\n{ctx.site_summary[:3000]}")
    lines.append(
        "\nWrite exactly 20 distinct questions. Mix these categories (at least two of each):\n"
        "- best_in_category: unbranded 'best X' questions for the brand's category\n"
        "- recommendation: asking whether the brand is a good choice or for brand recommendations\n"
        "- alternatives: alternatives to the brand or to competitors\n"
        "- comparison: the brand vs named competitors\n"
        "- pricing: cost, plans, value for money\n"
        "- features: capabilities and what to look for\n"
        "- use_case: specific jobs, industries or team types\n"
        "- beginner: beginner-friendly / getting-started questions\n"
        "Roughly half the questions should NOT mention the brand by name, because they test whether "
        "AI assistants recommend the brand unprompted. Write them in natural customer language, "
        "one sentence each."
    )
    return "\n".join(lines)


_SPACE = re.compile(r"\s+")


def _clean_llm_questions(raw: dict) -> list[GeneratedQuestion]:
    out: list[GeneratedQuestion] = []
    seen: set[str] = set()
    for item in raw.get("questions", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        text = _SPACE.sub(" ", str(item.get("text", ""))).strip()
        category = item.get("category")
        if not text or len(text) > 300 or category not in CATEGORIES:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(GeneratedQuestion(text=text, category=category, source="llm"))
    return out[:TARGET_COUNT]


def generate_questions(ctx: QuestionContext, provider: AIProvider | None) -> tuple[list[GeneratedQuestion], str | None]:
    """Return (questions, note). `note` explains when the fallback was used."""
    if provider is None or not provider.is_configured():
        return template_questions(ctx), "No AI provider is configured, so questions were generated from templates."
    try:
        raw = provider.complete_json(SYSTEM_PROMPT, _llm_prompt(ctx), QUESTION_SCHEMA)
    except (ProviderError, NotImplementedError) as exc:
        logger.warning("LLM question generation failed, using templates: %s", exc)
        return template_questions(ctx), f"AI question generation failed ({exc}); used templates instead."
    questions = _clean_llm_questions(raw)
    if len(questions) < TARGET_COUNT:
        # Top up with template questions so the set is always complete.
        existing = {q.text.lower() for q in questions}
        for tq in template_questions(ctx):
            if len(questions) >= TARGET_COUNT:
                break
            if tq.text.lower() not in existing:
                questions.append(tq)
        return questions, "The AI returned fewer than 20 usable questions; the rest come from templates."
    return questions, None
