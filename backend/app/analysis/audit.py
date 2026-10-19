"""Turn crawl results into scored, evidence-backed audit checks.

The audit score is a weighted average of check scores (each 0..1):

    score = 100 * sum(weight_i * score_i) / sum(weight_i)

Page-level checks score the fraction of crawled pages that pass. Every check
records the evidence (URLs, values) it was computed from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.analysis.extract import PageData
from app.crawler.crawler import CrawlResult

TITLE_MIN, TITLE_MAX = 10, 65
DESC_MIN, DESC_MAX = 50, 165
THIN_CONTENT_WORDS = 250
ORG_SCHEMA_TYPES = {"Organization", "Corporation", "LocalBusiness", "SoftwareApplication", "Product", "WebSite", "Brand"}
KEY_AI_CRAWLERS = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Google-Extended"]

# Topics customers commonly ask answer engines about, and the signals that a
# site covers them (URL path fragments or phrases in headings/titles).
CONTENT_TOPICS: list[dict] = [
    {
        "id": "pricing",
        "label": "Pricing and plans",
        "question": "How much does {brand} cost?",
        "paths": ["pricing", "price", "plans"],
        "phrases": [r"\bpricing\b", r"\bplans?\b", r"\bper (month|user|seat)\b", r"\bfree trial\b"],
    },
    {
        "id": "features",
        "label": "Features / what the product does",
        "question": "What are the main features of {brand}?",
        "paths": ["feature", "product", "platform", "how-it-works"],
        "phrases": [r"\bfeatures?\b", r"\bhow it works\b", r"\bcapabilities\b"],
    },
    {
        "id": "comparison",
        "label": "Comparisons with competitors",
        "question": "How does {brand} compare to alternatives?",
        "paths": ["compare", "comparison", "-vs-", "/vs", "versus"],
        "phrases": [r"\bvs\.?\b", r"\bversus\b", r"\bcompar(e|ison)\b"],
    },
    {
        "id": "alternatives",
        "label": "Alternatives",
        "question": "What are the best alternatives to {brand}?",
        "paths": ["alternative"],
        "phrases": [r"\balternatives?\b"],
    },
    {
        "id": "use_cases",
        "label": "Use cases / who it is for",
        "question": "Who is {brand} for and what is it used for?",
        "paths": ["use-case", "usecases", "solutions", "industries", "customers", "case-stud"],
        "phrases": [r"\buse cases?\b", r"\bwho (it'?s|is it) for\b", r"\bsolutions? for\b", r"\bcase stud(y|ies)\b"],
    },
    {
        "id": "getting_started",
        "label": "Getting started / onboarding",
        "question": "How do I get started with {brand}?",
        "paths": ["getting-started", "get-started", "onboarding", "quickstart", "docs", "guide", "signup", "sign-up"],
        "phrases": [r"\bget(ting)? started\b", r"\bquick ?start\b", r"\bhow to (set up|start)\b", r"\bsign up\b"],
    },
    {
        "id": "about",
        "label": "About the company",
        "question": "Who makes {brand} and is it trustworthy?",
        "paths": ["about", "company", "team"],
        "phrases": [r"\babout us\b", r"\bour (story|mission|team)\b", r"\bfounded\b"],
    },
    {
        "id": "faq",
        "label": "Frequently asked questions",
        "question": "Common questions about {brand}",
        "paths": ["faq", "questions"],
        "phrases": [r"\bfaqs?\b", r"\bfrequently asked\b"],
    },
]


@dataclass
class AuditOutcome:
    score: float
    checks: list[dict]
    page_issues: dict[str, list[dict]]
    content_gaps: list[dict]
    site_info: dict = field(default_factory=dict)


def page_issues(page: PageData) -> list[dict]:
    issues: list[dict] = []

    def add(code: str, severity: str, message: str) -> None:
        issues.append({"code": code, "severity": severity, "message": message})

    if page.js_shell:
        add("js_rendered", "high", page.js_shell_evidence or "Content is only rendered by JavaScript.")
    if not page.title:
        add("missing_title", "high", "Page has no <title>.")
    elif len(page.title) < TITLE_MIN:
        add("short_title", "medium", f"Title is very short ({len(page.title)} characters).")
    elif len(page.title) > TITLE_MAX:
        add("long_title", "low", f"Title is long ({len(page.title)} characters) and may be truncated.")
    if not page.meta_description:
        add("missing_meta_description", "high", "Page has no meta description.")
    elif len(page.meta_description) < DESC_MIN:
        add("short_meta_description", "medium", f"Meta description is short ({len(page.meta_description)} characters).")
    elif len(page.meta_description) > DESC_MAX:
        add("long_meta_description", "low", f"Meta description is long ({len(page.meta_description)} characters).")
    if len(page.h1) == 0:
        add("missing_h1", "medium", "Page has no H1 heading.")
    elif len(page.h1) > 1:
        add("multiple_h1", "low", f"Page has {len(page.h1)} H1 headings.")
    if not any(h["level"] == 2 for h in page.headings):
        add("no_subheadings", "low", "Page has no H2 subheadings to structure its content.")
    if page.word_count < THIN_CONTENT_WORDS:
        add("thin_content", "medium", f"Only {page.word_count} words of visible text.")
    if not page.schema_types:
        add("no_structured_data", "medium", "No structured data (JSON-LD / microdata) found.")
    for err in page.schema_errors:
        add("invalid_structured_data", "medium", err)
    if not page.canonical:
        add("missing_canonical", "low", "No canonical URL declared.")
    if page.meta_robots and "noindex" in page.meta_robots:
        add("noindex", "high", "Page is marked noindex, so search and answer engines may ignore it.")
    return issues


def _fraction_check(cid, label, category, weight, pages: list[PageData], predicate, detail_fn, why) -> dict:
    total = len(pages)
    passing = [p for p in pages if predicate(p)]
    failing = [p for p in pages if not predicate(p)]
    frac = len(passing) / total if total else 0.0
    return {
        "id": cid,
        "label": label,
        "category": category,
        "weight": weight,
        "score": round(frac, 3),
        "passed": frac >= 0.9,
        "detail": detail_fn(len(passing), total),
        "why": why,
        "evidence": [p.url for p in failing][:10],
    }


def _bool_check(cid, label, category, weight, passed: bool, detail: str, why: str, evidence=None) -> dict:
    return {
        "id": cid,
        "label": label,
        "category": category,
        "weight": weight,
        "score": 1.0 if passed else 0.0,
        "passed": passed,
        "detail": detail,
        "why": why,
        "evidence": list(evidence or [])[:10],
    }


def topic_coverage(pages: list[PageData], brand: str) -> list[dict]:
    """For each customer topic, record which crawled pages appear to cover it."""
    gaps = []
    for topic in CONTENT_TOPICS:
        matches = []
        for p in pages:
            path = p.url.lower()
            heading_text = " ".join([p.title or ""] + [h["text"] for h in p.headings]).lower()
            if any(fragment in path for fragment in topic["paths"]) or any(
                re.search(rx, heading_text) for rx in topic["phrases"]
            ):
                matches.append(p.url)
        gaps.append(
            {
                "topic": topic["id"],
                "label": topic["label"],
                "example_question": topic["question"].format(brand=brand),
                "covered": bool(matches),
                "pages": matches[:5],
            }
        )
    return gaps


def evaluate(crawl: CrawlResult, brand: str) -> AuditOutcome:
    pages = [cp.data for cp in crawl.pages]
    home = pages[0] if pages else None
    checks: list[dict] = []

    # --- Crawlability -------------------------------------------------------
    robots = crawl.robots or {}
    checks.append(
        _bool_check(
            "robots_txt", "robots.txt is present", "crawlability", 1, bool(robots.get("found")),
            "robots.txt found." if robots.get("found") else "No robots.txt found (crawlers assume everything is allowed).",
            "A robots.txt file tells search and AI crawlers what they may read and where your sitemap is.",
            [robots.get("url")] if robots.get("url") else [],
        )
    )
    ai = robots.get("ai_crawlers") or {}
    blocked = [agent for agent in KEY_AI_CRAWLERS if ai.get(agent) and not ai[agent]["allowed"]]
    checks.append(
        _bool_check(
            "ai_crawler_access", "AI crawlers are allowed", "crawlability", 3, not blocked,
            f"robots.txt blocks: {', '.join(blocked)}." if blocked else "No major AI crawler is blocked from the homepage.",
            "Answer engines can only cite content their crawlers are allowed to read. Blocking is a valid business choice, but it limits visibility.",
            blocked,
        )
    )
    sitemap = crawl.sitemap or {}
    checks.append(
        _bool_check(
            "sitemap", "XML sitemap is available", "crawlability", 2, bool(sitemap.get("found")),
            f"Sitemap found with {sitemap.get('url_count', 0)} URLs." if sitemap.get("found") else "No sitemap.xml found.",
            "Sitemaps help crawlers discover all important pages.",
            [sitemap.get("url")] if sitemap.get("url") else [],
        )
    )
    checks.append(
        _bool_check(
            "https", "Site is served over HTTPS", "crawlability", 2, crawl.https,
            "Homepage is served over HTTPS." if crawl.https else "Homepage is not served over HTTPS.",
            "HTTPS is a basic trust signal for search engines and users.",
            [crawl.root_url],
        )
    )
    indexable = [p for p in pages if not (p.meta_robots and "noindex" in p.meta_robots)]
    checks.append(
        _fraction_check(
            "indexable", "Pages are indexable", "crawlability", 2, pages,
            lambda p: not (p.meta_robots and "noindex" in p.meta_robots),
            lambda n, t: f"{n} of {t} crawled pages are indexable.",
            "Pages marked noindex are excluded from search indexes that answer engines draw on.",
        )
    )

    js_pages = [p for p in pages if p.js_shell]
    checks.append(
        _fraction_check(
            "js_rendering", "Content is visible without JavaScript", "crawlability", 5, pages,
            lambda p: not p.js_shell,
            lambda n, t: f"{n} of {t} crawled pages contain their content in the HTML."
            + (" The homepage is an empty JavaScript app shell." if home and home.js_shell else ""),
            "Most AI crawlers (GPTBot, ClaudeBot, PerplexityBot) don't run JavaScript. Content that only appears "
            "after scripts run is invisible to them, and links rendered by scripts can't be followed.",
        )
    )
    if home and home.js_shell:
        # Make the homepage evidence the first thing shown.
        checks[-1]["evidence"] = [home.js_shell_evidence] + [p.url for p in js_pages][:9]

    # --- Metadata -------------------------------------------------------------
    checks.append(
        _fraction_check(
            "titles", "Pages have descriptive titles", "metadata", 3, pages,
            lambda p: bool(p.title) and TITLE_MIN <= len(p.title) <= TITLE_MAX,
            lambda n, t: f"{n} of {t} pages have a title between {TITLE_MIN} and {TITLE_MAX} characters.",
            "Titles are one of the strongest signals of what a page is about.",
        )
    )
    checks.append(
        _fraction_check(
            "meta_descriptions", "Pages have meta descriptions", "metadata", 3, pages,
            lambda p: bool(p.meta_description) and DESC_MIN <= len(p.meta_description) <= DESC_MAX,
            lambda n, t: f"{n} of {t} pages have a meta description between {DESC_MIN} and {DESC_MAX} characters.",
            "Meta descriptions give crawlers and users a concise summary of each page.",
        )
    )
    checks.append(
        _fraction_check(
            "canonical", "Pages declare a canonical URL", "metadata", 1, pages,
            lambda p: bool(p.canonical),
            lambda n, t: f"{n} of {t} pages declare a canonical URL.",
            "Canonical URLs prevent duplicate versions of a page from diluting signals.",
        )
    )
    brand_lower = brand.lower()
    brand_in_home = bool(home) and (
        brand_lower in (home.title or "").lower() or any(brand_lower in h.lower() for h in home.h1)
    )
    checks.append(
        _bool_check(
            "brand_on_homepage", "Brand name is in the homepage title or H1", "metadata", 2, brand_in_home,
            "Brand name appears in the homepage title/H1." if brand_in_home
            else f"\"{brand}\" does not appear in the homepage title or H1.",
            "Clearly associating the brand name with the site helps models connect your name to your domain.",
            [f"Title: {home.title}" if home else "No homepage"] + ([f"H1: {h}" for h in home.h1[:2]] if home else []),
        )
    )

    # --- Content structure --------------------------------------------------
    checks.append(
        _fraction_check(
            "h1", "Pages have exactly one H1", "structure", 2, pages,
            lambda p: len(p.h1) == 1,
            lambda n, t: f"{n} of {t} pages have exactly one H1.",
            "A single clear H1 tells crawlers the main topic of the page.",
        )
    )
    checks.append(
        _fraction_check(
            "subheadings", "Content is organized with subheadings", "structure", 2, pages,
            lambda p: any(h["level"] == 2 for h in p.headings),
            lambda n, t: f"{n} of {t} pages use H2 subheadings.",
            "Well-structured sections are easier for answer engines to extract and quote.",
        )
    )
    checks.append(
        _fraction_check(
            "content_depth", "Pages have substantive content", "structure", 2, pages,
            lambda p: p.word_count >= THIN_CONTENT_WORDS,
            lambda n, t: f"{n} of {t} pages have at least {THIN_CONTENT_WORDS} words of visible text.",
            "Thin pages give models little factual material to draw on. (Pages rendered only with JavaScript may also appear thin.)",
        )
    )

    # --- Structured data & FAQ ----------------------------------------------
    all_types = sorted({t for p in pages for t in p.schema_types})
    checks.append(
        _fraction_check(
            "structured_data", "Pages include structured data", "structured_data", 2, pages,
            lambda p: bool(p.schema_types),
            lambda n, t: f"{n} of {t} pages include JSON-LD or microdata.",
            "Schema.org markup states facts (organization, product, FAQ) in a machine-readable way.",
        )
    )
    org_types = [t for t in all_types if t in ORG_SCHEMA_TYPES]
    checks.append(
        _bool_check(
            "org_schema", "Organization / product schema present", "structured_data", 2, bool(org_types),
            f"Found: {', '.join(org_types)}." if org_types else "No Organization, Product or SoftwareApplication schema found.",
            "Entity schema helps models confirm who you are, what you sell and your official URLs.",
            all_types,
        )
    )
    invalid = [p.url for p in pages if p.schema_errors]
    if all_types or invalid:
        checks.append(
            _bool_check(
                "valid_schema", "Structured data parses correctly", "structured_data", 1, not invalid,
                "All JSON-LD blocks parsed." if not invalid else f"{len(invalid)} page(s) have JSON-LD that fails to parse.",
                "Broken JSON-LD is ignored by parsers.",
                invalid,
            )
        )
    faq_pages = [p.url for p in pages if p.has_faq]
    checks.append(
        _bool_check(
            "faq_content", "FAQ content is present", "content", 3, bool(faq_pages),
            f"FAQ-style content found on {len(faq_pages)} page(s)." if faq_pages else "No FAQ-style content detected on crawled pages.",
            "Question-and-answer content maps directly onto the questions people ask AI assistants.",
            faq_pages,
        )
    )
    faq_schema_pages = [p.url for p in pages if "FAQPage" in p.schema_types]
    if faq_pages:
        checks.append(
            _bool_check(
                "faq_schema", "FAQ content has FAQPage schema", "structured_data", 1, bool(faq_schema_pages),
                "FAQPage schema found." if faq_schema_pages else "FAQ content exists but has no FAQPage schema.",
                "FAQPage markup makes question/answer pairs explicit to machines.",
                faq_schema_pages or faq_pages,
            )
        )

    # --- Topic coverage -------------------------------------------------------
    coverage = topic_coverage(pages, brand)
    covered = [c for c in coverage if c["covered"]]
    checks.append(
        {
            "id": "topic_coverage",
            "label": "Site answers common customer questions",
            "category": "content",
            "weight": 4,
            "score": round(len(covered) / len(coverage), 3) if coverage else 0.0,
            "passed": len(covered) == len(coverage),
            "detail": f"{len(covered)} of {len(coverage)} common question topics have a matching page or section.",
            "why": "Answer engines can only cite you for questions your site actually answers.",
            "evidence": [f"Missing: {c['label']}" for c in coverage if not c["covered"]],
        }
    )

    total_weight = sum(c["weight"] for c in checks)
    score = round(100 * sum(c["weight"] * c["score"] for c in checks) / total_weight, 1) if total_weight else 0.0

    issues = {p.url: page_issues(p) for p in pages}
    site_info = {
        "start_url": crawl.start_url,
        "root_url": crawl.root_url,
        "https": crawl.https,
        "robots": robots,
        "sitemap": sitemap,
        "failures": crawl.failures[:20],
        "skipped_by_robots": crawl.skipped_by_robots[:20],
        "stopped_early": crawl.stopped_early,
        "schema_types": all_types,
        "indexable_pages": len(indexable),
        "js_rendered_shell": bool(home and home.js_shell),
        # Content of JavaScript-only pages was read from a headless-browser render
        "homepage_rendered": bool(home and home.rendered),
        "rendered_pages": list(crawl.rendered_pages)[:30],
        "render_error": crawl.render_error,
        "js_rendered_pages": [p.url for p in js_pages][:20],
    }
    return AuditOutcome(score=score, checks=checks, page_issues=issues, content_gaps=coverage, site_info=site_info)
