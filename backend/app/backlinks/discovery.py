"""Discover and verify backlinks, brand mentions and legitimate listing opportunities.

Principles:
* Every URL comes from an official search API result, and every page is fetched
  (SSRF-safe) and read before it is shown. Pages that don't load are dropped.
* Whether a page links to the business (and with follow / nofollow / ugc / sponsored)
  or mentions it is read from the page itself, never estimated. No authority scores.
* Link-selling and spam pages are excluded; nothing is submitted automatically.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from app.crawler.fetcher import FetchError, SafeFetcher
from app.crawler.url_safety import UnsafeURLError, site_key
from app.visibility.detection import build_aliases, find_mentions, url_matches_domain

logger = logging.getLogger(__name__)

MAX_RESULTS_PER_QUERY = 10
MAX_PAGES_TO_VERIFY = 30
VERIFY_BUDGET_SECONDS = 90
SPAM_SIGNALS = re.compile(
    r"buy (?:high[- ]quality |cheap )?backlinks|guest post (?:price|service|for sale)|dofollow links? for sale|link building service"
    r"|sponsored post (?:price|rate)|pbn links|casino|betting tips|crypto (?:pump|signals)", re.I,
)
# Big platforms where "opportunity" would just mean "make an account"; kept only as existing mentions
PLATFORM_HOSTS = ("wikipedia.org", "amazon.", "flipkart.com", "youtube.com", "pinterest.", "quora.com")
CATEGORY_RULES = [
    ("directory", r"directory|directories|listing|yellow ?pages|justdial|sulekha|indiamart|tradeindia|yelp|hotfrog|business list"),
    ("chamber_association", r"chamber of commerce|association|federation|council|society of|guild|union of"),
    ("news", r"\bnews\b|times|daily|express|herald|patrika|gazette|tribune|samachar|lokmat|bhaskar"),
    ("review_platform", r"reviews?|trustpilot|tripadvisor|rating"),
    ("community_events", r"community|events?|festival|club|meetup|ngo"),
    ("supplier_partner", r"supplier|distributor|dealer|wholesale|manufacturer|partner"),
    ("blog_resource", r"blog|guide|resources?|top \d+|best \d+"),
]
SUBMIT_TEXT = re.compile(
    r"add (?:your |a )?(?:business|listing|company|shop|store)|list your (?:business|company|shop)|free listing|submit|"
    r"register (?:your )?(?:business|company)|claim (?:this|your) (?:business|listing)|get listed|become a member|join (?:us|now)", re.I,
)


@dataclass
class DiscoveryProfile:
    brand: str
    domain: str
    category: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    competitors: list[str] = field(default_factory=list)


def build_queries(p: DiscoveryProfile) -> list[tuple[str, str]]:
    """(purpose, query) pairs. 'mention' queries look for existing mentions; the rest look for opportunities."""
    place = p.city or p.region or ""
    wider = p.region or p.country or ""
    cat = p.category or "local business"
    queries = [("mention", f'"{p.brand}"')]
    if place:
        queries += [
            ("mention", f'"{p.brand}" {place}'),
            ("opportunity", f"{place} business directory list your business"),
            ("opportunity", f"{cat} directory {place}"),
            ("opportunity", f"{place} chamber of commerce"),
            ("opportunity", f"{place} local news {cat}"),
        ]
    if wider:
        queries += [("opportunity", f"{cat} association {wider}")]
    queries += [("opportunity", f"{cat} suppliers distributors {wider or place}".strip())]
    return queries


def classify(url: str, title: str, text: str) -> str:
    hay = f"{url} {title} {text[:3000]}".lower()
    for category, rx in CATEGORY_RULES:
        if re.search(rx, hay):
            return category
    return "other"


def _rel(a) -> str:
    rel = " ".join(a.get("rel") or []).lower() if isinstance(a.get("rel"), list) else str(a.get("rel") or "").lower()
    for value in ("sponsored", "ugc", "nofollow"):
        if value in rel:
            return value
    return "follow"


@dataclass
class PageCheck:
    url: str
    ok: bool
    error: str | None = None
    title: str | None = None
    text: str = ""
    links_to_site: list[dict] = field(default_factory=list)  # [{href, rel, anchor}]
    mention_snippets: list[str] = field(default_factory=list)
    submission_url: str | None = None
    spam: bool = False


def check_page(fetcher: SafeFetcher, url: str, brand: str, domain: str) -> PageCheck:
    """Fetch a page and record whether it links to / mentions the business."""
    try:
        res = fetcher.fetch(url)
    except (FetchError, UnsafeURLError) as exc:
        return PageCheck(url=url, ok=False, error=str(exc)[:200])
    if res.status_code >= 400 or not res.is_html:
        return PageCheck(url=url, ok=False, error=f"HTTP {res.status_code}" if res.status_code >= 400 else "not an HTML page")
    soup = BeautifulSoup(res.content, "lxml")
    title = " ".join((soup.title.get_text() if soup.title else "").split())[:300] or None
    links, submission = [], None
    for a in soup.find_all("a", href=True):
        href = urljoin(res.final_url, a["href"].strip())
        anchor = " ".join(a.get_text(" ").split())[:120]
        if url_matches_domain(href, domain):
            links.append({"href": href, "rel": _rel(a), "anchor": anchor})
        elif submission is None and SUBMIT_TEXT.search(anchor or ""):
            submission = href
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    snippets = []
    for start, end, _ in find_mentions(text, build_aliases(brand, domain))[:3]:
        snippets.append("…" + text[max(0, start - 80) : end + 80] + "…")
    return PageCheck(url=res.final_url, ok=True, title=title, text=text[:5000], links_to_site=links[:5],
                     mention_snippets=snippets, submission_url=submission, spam=bool(SPAM_SIGNALS.search(text[:20000])))


def value_and_rel(check: PageCheck) -> tuple[str, str]:
    if check.links_to_site:
        rels = {l["rel"] for l in check.links_to_site}
        rel = "follow" if "follow" in rels else sorted(rels)[0]
        return ("both" if check.mention_snippets else "backlink"), rel
    if check.mention_snippets:
        return "mention", "unknown"
    return "unknown", "unknown"


WHY = {
    "directory": "Accurate directory listings help search engines and AI confirm your name, address and phone, and help people find you.",
    "chamber_association": "Membership listings from local and industry bodies are trusted signals that you are a real, established business.",
    "news": "Coverage in local news is an independent mention that AI assistants and search engines treat as credible.",
    "review_platform": "Review platforms show reputation signals that people and AI use when recommending businesses.",
    "community_events": "Taking part in local events or community pages earns genuine local mentions.",
    "supplier_partner": "Suppliers and partners often list stockists or partners, a relevant link from your own industry.",
    "blog_resource": "Being included in a relevant guide or resource page puts you where people research options.",
    "other": "A relevant page that could mention or link to your business.",
}


def relevance_note(check: PageCheck, p: DiscoveryProfile) -> str:
    hay = f"{check.title or ''} {check.text}".lower()
    reasons = []
    for label, term in (("your city", p.city), ("your region", p.region)):
        if term and term.lower() in hay:
            reasons.append(f"mentions {term} ({label})")
    if p.category:
        words = [w for w in re.findall(r"[a-z]{4,}", p.category.lower()) if w not in {"store", "shop", "services", "service"}]
        hits = [w for w in words if w in hay]
        if hits:
            reasons.append(f"about {', '.join(hits)}")
    return ("Relevant: " + "; ".join(reasons)) if reasons else "Relevance not confirmed from page text: review before acting."


def outreach_message(category: str, p: DiscoveryProfile, site_title: str | None) -> str:
    place = f" in {p.city}" if p.city else ""
    target = site_title or "your site"
    if category in ("directory", "review_platform"):
        return (f"Next step: create or claim a free listing for {p.brand} on {target}. Use exactly the same name, address, "
                f"phone and website as on your Google Business Profile, choose the most specific category, and add photos.")
    if category == "chamber_association":
        return (f"Hello, I run {p.brand}, a {p.category or 'local business'}{place}. We'd like to join / be listed as a member. "
                f"Could you tell us how to apply and whether members are listed on your website with a link? Thank you.")
    if category == "news":
        return (f"Hello, I'm reaching out from {p.brand}, a {p.category or 'local business'}{place}. If you cover local businesses, "
                f"we'd be happy to share [ADD: a genuine local story, event, or expertise]. Thank you for your time.")
    if category == "supplier_partner":
        return (f"Hello, {p.brand}{place} stocks / works with [ADD: products or brands you genuinely work with]. If you list "
                f"stockists or partners on your website, could you add us with a link to {p.domain}? Thank you.")
    return (f"Hello, I'm from {p.brand}, a {p.category or 'local business'}{place}. I found {target} and think our "
            f"[ADD: specific, genuinely useful resource or information] could be helpful to your readers.")


def discover(db, backend, profile: DiscoveryProfile, cached_search, fetcher: SafeFetcher | None = None,
             clock=time.monotonic) -> list[dict]:
    """Search, then verify each result page. Returns item dicts for pages that loaded."""
    candidates: dict[str, tuple[str, dict, str]] = {}  # url -> (purpose, result, query)
    seen_domains: set[str] = set()
    for purpose, query in build_queries(profile):
        try:
            results = cached_search(db, backend, query, max_results=MAX_RESULTS_PER_QUERY, country=profile.country)
        except Exception as exc:  # noqa: BLE001 - one failed query shouldn't stop discovery
            logger.warning("search failed for %r: %s", query, exc)
            continue
        for r in results:
            url, host = r.get("url") or "", site_key(urlsplit(r.get("url") or "").hostname or "")
            if not url.startswith(("http://", "https://")) or not host or url_matches_domain(url, profile.domain):
                continue
            if purpose == "opportunity" and (host in seen_domains or any(h in host for h in PLATFORM_HOSTS)):
                continue
            seen_domains.add(host)
            candidates.setdefault(url, (purpose, r, query))
    urls = list(candidates)[:MAX_PAGES_TO_VERIFY]
    own_fetcher = fetcher is None
    fetcher = fetcher or SafeFetcher(user_agent="AEOAuditBot/0.1 (+backlink verification)", timeout=10, max_bytes=1_500_000)
    started = clock()
    items = []
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            checks = pool.map(lambda u: check_page(fetcher, u, profile.brand, profile.domain) if clock() - started < VERIFY_BUDGET_SECONDS else PageCheck(u, False, "time budget reached"), urls)
            for url, check in zip(urls, checks):
                purpose, result, query = candidates[url]
                if not check.ok or check.spam:
                    continue
                value, rel = value_and_rel(check)
                existing = value != "unknown"
                if purpose == "mention" and not existing:
                    continue  # a search hit that doesn't actually mention or link to the business
                category = classify(check.url, check.title or result.get("title") or "", check.text)
                evidence = [f"Search: {query}"]
                evidence += [f"Links to you: {l['href']} (rel: {l['rel']}, anchor: \"{l['anchor']}\")" for l in check.links_to_site]
                evidence += [f"Mentions you: {s}" for s in check.mention_snippets]
                items.append({
                    "kind": "existing" if existing else "opportunity",
                    "status": "found" if existing else "suggested",
                    "url": check.url[:2048], "domain": site_key(urlsplit(check.url).hostname or ""),
                    "title": check.title or result.get("title"), "category": category,
                    "submission_url": None if existing else check.submission_url,
                    "relevance": relevance_note(check, profile), "why_it_helps": WHY[category],
                    "value_type": value, "link_rel": rel,
                    "discovered_via": f"{getattr(backend, 'name', 'search')}: {query}"[:300],
                    "evidence": evidence[:8],
                    "outreach": None if existing else outreach_message(category, profile, check.title),
                    "last_checked_at": datetime.now(timezone.utc),
                })
    finally:
        if own_fetcher:
            fetcher.close()
    return items
