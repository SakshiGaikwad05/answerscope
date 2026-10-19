"""Turn action-plan items into ready-to-review drafts.

Two kinds of generator:

* Template generators (free, deterministic, exact): sitemap.xml from crawled
  pages, robots.txt that allows AI search crawlers, Organization JSON-LD from
  facts the user already gave us.
* AI generators (count against the fix-generation quota): metadata, FAQ, comparison,
  pricing and topic drafts. The model only sees the crawled text of the site and
  must not add facts that aren't in it; anything missing becomes an
  "[ADD: ...]" placeholder. Numbers in the draft that don't appear on the site are
  flagged afterwards, as a guard against invented prices or statistics.

Drafts are suggestions for a human to review, never applied automatically.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.limits import consume_quota
from app.models import AuditPage, FixDraft, Recommendation, User, WebsiteAudit
from app.providers.base import ProviderError
from app.providers.registry import first_configured
from app.services.recommendations import latest_completed_audit

TEMPLATE_KEYS = {"crawl:sitemap", "crawl:robots-txt", "crawl:ai-crawlers-blocked", "schema:organization"}
AI_KEY_PREFIXES = (
    "meta:titles",
    "meta:descriptions",
    "meta:brand-homepage",
    "content:faq",
    "schema:faq",
    "content:comparison",
    "competitors:",
    "content:pricing",
    "content:topic:",
    "content:thin",
    "visibility:unprompted",
)
MAX_PAGES_IN_CONTEXT = 8
MIN_CONTENT_WORDS = 40
AI_SEARCH_AGENTS = ["OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot"]


class FixGenerationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


def supports_fix(key: str) -> bool:
    return key in TEMPLATE_KEYS or key.startswith(AI_KEY_PREFIXES)


@dataclass
class SiteContext:
    brand: str
    website_url: str
    domain: str
    industry: str | None
    competitors: list[str]
    pages: list[AuditPage]
    site_text: str  # everything the model may rely on, for the number check


def _site_context(db: Session, rec: Recommendation) -> SiteContext:
    project = rec.project
    audit: WebsiteAudit | None = latest_completed_audit(db, project.id)
    pages = list(audit.pages) if audit else []
    text = "\n".join(
        " ".join(filter(None, [p.title, p.meta_description, " ".join(h["text"] for h in p.headings), p.text_excerpt]))
        for p in pages
    )
    return SiteContext(
        brand=project.brand_name,
        website_url=project.website_url,
        domain=project.domain,
        industry=project.industry,
        competitors=[c.name for c in project.competitors],
        pages=pages,
        site_text=text,
    )


# --------------------------------------------------------------------------- templates
def _sitemap(ctx: SiteContext) -> FixDraft:
    urls = list(dict.fromkeys(p.url for p in ctx.pages if (p.status_code or 200) < 400)) or [ctx.website_url]
    body = "\n".join(f"  <url><loc>{escape(u)}</loc></url>" for u in urls)
    content = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'
    return FixDraft(
        title="sitemap.xml", format="text", content=content, generator="template", sources=urls,
        placeholders=[] if len(urls) > 1 else ["Add your other important pages: only the homepage was found by the crawl."],
        notes=f"Save as {ctx.website_url.rstrip('/')}/sitemap.xml. It lists the {len(urls)} page(s) the audit crawled; add any "
        "important pages it missed. Reference it from robots.txt with a Sitemap: line.",
    )


def _robots(ctx: SiteContext) -> FixDraft:
    origin = ctx.website_url.rstrip("/")
    agents = "\n\n".join(f"User-agent: {a}\nAllow: /" for a in AI_SEARCH_AGENTS)
    content = f"""# Allow AI search / answer-engine crawlers so your pages can be cited
{agents}

# Everyone else
User-agent: *
Allow: /

Sitemap: {origin}/sitemap.xml
"""
    return FixDraft(
        title="robots.txt", format="text", content=content, generator="template", sources=[ctx.website_url], placeholders=[],
        notes=f"Save as {origin}/robots.txt. If you want to keep AI *training* crawlers out (e.g. GPTBot, ClaudeBot, "
        "Google-Extended, CCBot), add a Disallow block for them; the search agents above can stay allowed.",
    )


def _organization(ctx: SiteContext) -> FixDraft:
    data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": ctx.brand,
        "url": ctx.website_url,
        "logo": "[ADD: full URL of your logo image]",
        "sameAs": ["[ADD: URLs of your official profiles, e.g. LinkedIn, X, GitHub]"],
    }
    home = next((p for p in ctx.pages if p.meta_description), None)
    if home:
        data["description"] = home.meta_description
    content = '<script type="application/ld+json">\n' + json.dumps(data, indent=2, ensure_ascii=False) + "\n</script>\n"
    return FixDraft(
        title="Organization structured data (JSON-LD)", format="json-ld", content=content, generator="template",
        sources=[ctx.website_url], placeholders=["Logo URL", "Official profile URLs (sameAs)"],
        notes="Paste inside <head> on your homepage, fill in the placeholders, and check it with a schema validator. "
        "The description is copied from your homepage meta description." if home else
        "Paste inside <head> on your homepage, fill in the placeholders, and check it with a schema validator.",
    )


# --------------------------------------------------------------------------- AI drafts
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "format": {"type": "string", "enum": ["markdown", "html", "json-ld", "text"]},
        "content": {"type": "string"},
        "placeholders": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["title", "format", "content", "placeholders", "notes"],
    "additionalProperties": False,
}

SYSTEM = (
    "You draft website content changes that help a business answer its customers' questions clearly, for review "
    "by the site owner. Strict rules: use ONLY facts stated in the provided website content. Never invent prices, "
    "numbers, features, customers, awards, dates or claims about competitors. Where a needed fact is missing, insert "
    "a placeholder in the form [ADD: what is needed] and list it in `placeholders`. Write plainly and specifically; "
    "no hype. Put the draft in `content`, and explain how to use it in `notes`."
)


def _page_block(p: AuditPage) -> str:
    heads = "; ".join(h["text"] for h in p.headings[:15])
    return (
        f"URL: {p.url}\nTitle: {p.title or '(none)'}\nMeta description: {p.meta_description or '(none)'}\n"
        f"Headings: {heads or '(none)'}\nText: {(p.text_excerpt or '')[:1800]}"
    )


def _task(rec: Recommendation, ctx: SiteContext) -> str:
    key = rec.key
    if key.startswith(("meta:titles", "meta:descriptions", "meta:brand-homepage")):
        return (
            "For each page above, write an improved <title> (50-60 characters, include the brand name) and meta description "
            "(140-160 characters) that accurately summarize that page's actual content. Output markdown: one section per URL "
            "with the suggested title and description, followed by the ready-to-paste HTML tags."
        )
    if key in ("content:faq", "schema:faq"):
        return (
            f"Write an FAQ page for {ctx.brand} with 6-10 questions customers actually ask (use the example questions in the "
            "issue evidence where relevant). Answer each in 2-4 sentences using only the website content; use [ADD: ...] for "
            "answers the site doesn't support. Output markdown, then a FAQPage JSON-LD block (in a ```json fence) that mirrors "
            "the visible questions and answers exactly."
        )
    if key.startswith(("content:comparison", "competitors:")):
        rival = key.split(":")[-1] if key.count(":") >= 2 or key.startswith("competitors:") else None
        rival_name = next((c for c in ctx.competitors if rival and c.lower() == rival), rival or "a typical alternative")
        return (
            f"Draft a fair, factual comparison page: {ctx.brand} vs {rival_name}. Include a short intro, a comparison table "
            f"(features, pricing, who it's for, support), 'Choose {ctx.brand} if…' / 'Choose {rival_name} if…' sections, and an "
            f"FAQ. You have NO verified information about {rival_name}: every competitor cell must be a placeholder like "
            f"[ADD: {rival_name} pricing, from their official site]. Output markdown."
        )
    if key == "content:pricing":
        return (
            "Draft a pricing page structure: plan names, what's included, free trial/plan, how billing works, and a short "
            "pricing FAQ. Use prices ONLY if they appear in the website content; otherwise use [ADD: ...] placeholders. "
            "Output markdown."
        )
    if key == "visibility:unprompted":
        return (
            f"Draft an authoritative 'What {ctx.brand} does and who it's for' page that would let an AI assistant describe "
            f"{ctx.brand} accurately when someone asks about the category"
            + (f" ({ctx.industry})" if ctx.industry else "")
            + ": what it is, who it's for, key capabilities, how it differs from alternatives, and how to get started. "
            "Output markdown."
        )
    # content:topic:* and content:thin
    return (
        "Draft a page section that directly answers the customer question in the issue below, using only the website "
        "content. Start with a 1-2 sentence direct answer, then supporting detail with H2/H3 headings. Output markdown."
    )


def _flag_unsupported_numbers(content: str, site_text: str) -> list[str]:
    numbers = set(re.findall(r"[$€£₹]\s?\d[\d,.]*|\d[\d,.]*\s?%|\b\d{2,}[\d,.]*\b", content))
    site = site_text.replace(" ", "")
    return sorted(n for n in numbers if n.replace(" ", "") not in site)


def _ai_draft(db: Session, rec: Recommendation, ctx: SiteContext, user: User) -> FixDraft:
    provider = first_configured()
    if provider is None:
        raise FixGenerationError(400, "provider_not_configured", "AI drafts need an AI provider API key on the server.")
    usable = [p for p in ctx.pages if p.word_count >= MIN_CONTENT_WORDS or p.headings]
    if not usable:
        raise FixGenerationError(
            400, "no_site_content",
            "The audit found no readable content on your pages, so there are no facts to base a draft on. "
            "Fix the site's content visibility (or enable JavaScript rendering) and re-run the audit first.",
        )
    consume_quota(db, user, "fix_generation")
    db.flush()
    pages = usable[:MAX_PAGES_IN_CONTEXT]
    prompt = "\n\n".join(
        [
            f"Business: {ctx.brand} ({ctx.website_url})" + (f"\nIndustry: {ctx.industry}" if ctx.industry else ""),
            f"Known competitors (names only, no verified facts): {', '.join(ctx.competitors) or 'none'}",
            f"Issue to fix: {rec.issue}\nRecommended action: {rec.action}\nEvidence: " + "; ".join(map(str, rec.evidence[:8])),
            "WEBSITE CONTENT (the only facts you may use):\n\n" + "\n\n---\n\n".join(_page_block(p) for p in pages),
            "TASK: " + _task(rec, ctx),
        ]
    )
    try:
        data = provider.complete_json(SYSTEM, prompt, DRAFT_SCHEMA)
    except ProviderError as exc:
        raise FixGenerationError(502, "provider_error", f"The AI provider failed: {exc.message}") from exc
    content = str(data.get("content") or "").strip()
    if not content:
        raise FixGenerationError(502, "empty_draft", "The AI returned an empty draft. Please try again.")
    fmt = data.get("format") if data.get("format") in ("markdown", "html", "json-ld", "text") else "markdown"
    notes = str(data.get("notes") or "").strip()
    unsupported = _flag_unsupported_numbers(content, ctx.site_text)
    if unsupported:
        notes += ("\n\n" if notes else "") + (
            "⚠ Check these figures before publishing — they don't appear on your crawled pages: " + ", ".join(unsupported)
        )
    placeholders = [str(p) for p in data.get("placeholders") or []][:40]
    placeholders += [m for m in re.findall(r"\[ADD:[^\]]*\]", content) if m not in placeholders][:40]
    return FixDraft(
        title=str(data.get("title") or rec.issue)[:300], format=fmt, content=content, placeholders=placeholders,
        notes=notes or None, sources=[p.url for p in pages], generator=provider.model,
    )


def generate_fix(db: Session, rec: Recommendation, *, user: User) -> FixDraft:
    ctx = _site_context(db, rec)
    if rec.key == "crawl:sitemap":
        draft = _sitemap(ctx)
    elif rec.key in ("crawl:robots-txt", "crawl:ai-crawlers-blocked"):
        draft = _robots(ctx)
    elif rec.key == "schema:organization":
        draft = _organization(ctx)
    elif supports_fix(rec.key):
        draft = _ai_draft(db, rec, ctx, user)
    else:
        raise FixGenerationError(400, "unsupported", "No fix generator is available for this item yet.")
    draft.recommendation_id = rec.id
    return draft
