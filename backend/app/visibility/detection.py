"""Detect brand / competitor mentions and website citations in AI answers.

Rules (kept deliberately simple and explainable):

* A *mention* is a whole-word, case-insensitive match (outside URLs) of the entity name, a
  compact form of it ("Acme Corp" -> "AcmeCorp") or its domain ("acme.com").
  For single-word names that are also ordinary words (e.g. "Notion", "Apple"),
  a match must start with a capital letter or match the domain, to avoid
  counting "an apple" as a mention of Apple.
* A *citation* is a URL on the entity's domain (or a subdomain) that the provider
  cited as a source, or that appears as a link in the answer text. Search results
  the model saw but did not cite are recorded as sources, not citations.

Every detection stores evidence: answer snippets for mentions, URLs for citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.crawler.url_safety import site_key

SNIPPET_RADIUS = 90
MAX_SNIPPETS = 3
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)


@dataclass
class EntitySpec:
    name: str
    entity_type: str  # "brand" | "competitor"
    domain: str | None = None
    competitor_id: int | None = None
    aliases: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.aliases:
            self.aliases = build_aliases(self.name, self.domain)


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    candidate = url if "://" in url else "https://" + url
    try:
        host = urlsplit(candidate).hostname
    except ValueError:
        return None
    return site_key(host) if host else None


def build_aliases(name: str, domain: str | None = None) -> list[str]:
    name = name.strip()
    aliases = [name] if name else []
    compact = re.sub(r"[\s\-_.]+", "", name)
    if compact and compact.lower() != name.lower() and len(compact) >= 4:
        aliases.append(compact)
    if domain:
        aliases.append(site_key(domain))
    seen, out = set(), []
    for a in aliases:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def _requires_capital(alias: str) -> bool:
    # Single alphabetic word -> could be an ordinary word, so require capitalization.
    return alias.isalpha() and " " not in alias and "." not in alias


def find_mentions(text: str, aliases: list[str]) -> list[tuple[int, int, str]]:
    """Return non-overlapping (start, end, matched_text) spans."""
    spans: list[tuple[int, int, str]] = []
    # Text inside URLs is a link (handled as a citation), not a mention by name.
    url_spans = [(m.start(), m.end()) for m in _URL_RE.finditer(text)]
    for alias in aliases:
        if not alias:
            continue
        pattern = re.compile(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", re.I)
        for m in pattern.finditer(text):
            matched = m.group(0)
            if _requires_capital(alias) and not (matched[0].isupper() or matched == alias):
                continue
            if any(a <= m.start() < b for a, b in url_spans):
                continue
            spans.append((m.start(), m.end(), matched))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str]] = []
    for span in spans:
        if merged and span[0] < merged[-1][1]:
            continue
        merged.append(span)
    return merged


def snippet(text: str, start: int, end: int, radius: int = SNIPPET_RADIUS) -> str:
    a, b = max(0, start - radius), min(len(text), end + radius)
    out = re.sub(r"\s+", " ", text[a:b]).strip()
    return ("…" if a > 0 else "") + out + ("…" if b < len(text) else "")


def extract_urls(text: str) -> list[str]:
    urls = [u.rstrip(".,;:!?*") for u in _URL_RE.findall(text or "")]
    return list(dict.fromkeys(urls))


def url_matches_domain(url: str, domain: str) -> bool:
    host = domain_of(url)
    if not host or not domain:
        return False
    domain = site_key(domain)
    return host == domain or host.endswith("." + domain)


@dataclass
class AnswerAnalysis:
    brand_mentioned: bool
    website_cited: bool
    detections: list[dict]  # rows for the mentions table


def analyze_entity(text: str, sources: list[dict], entity: EntitySpec) -> list[dict]:
    rows: list[dict] = []
    spans = find_mentions(text, entity.aliases)
    if spans:
        rows.append(
            {
                "entity_type": entity.entity_type,
                "entity_name": entity.name,
                "competitor_id": entity.competitor_id,
                "kind": "mention",
                "occurrences": len(spans),
                "evidence": [{"type": "snippet", "text": snippet(text, s, e), "matched": m} for s, e, m in spans[:MAX_SNIPPETS]],
            }
        )
    if entity.domain:
        evidence = []
        for src in sources:
            if src.get("type") == "cited" and url_matches_domain(src.get("url", ""), entity.domain):
                evidence.append({"type": "cited_source", "url": src["url"], "title": src.get("title")})
        for url in extract_urls(text):
            if url_matches_domain(url, entity.domain) and all(e["url"] != url for e in evidence):
                evidence.append({"type": "linked_in_answer", "url": url})
        if evidence:
            rows.append(
                {
                    "entity_type": entity.entity_type,
                    "entity_name": entity.name,
                    "competitor_id": entity.competitor_id,
                    "kind": "citation",
                    "occurrences": len(evidence),
                    "evidence": evidence[:10],
                }
            )
    return rows


def analyze_answer(text: str, sources: list[dict], brand: EntitySpec, competitors: list[EntitySpec]) -> AnswerAnalysis:
    detections = analyze_entity(text, sources, brand)
    for comp in competitors:
        detections.extend(analyze_entity(text, sources, comp))
    brand_rows = [d for d in detections if d["entity_type"] == "brand"]
    return AnswerAnalysis(
        brand_mentioned=any(d["kind"] == "mention" for d in brand_rows),
        website_cited=any(d["kind"] == "citation" for d in brand_rows),
        detections=detections,
    )


def question_names_brand(question: str, brand: EntitySpec) -> bool:
    """True if the question itself names the brand (a "branded" question).

    Answers to branded questions almost always repeat the name, so they say
    little about whether the AI would bring the brand up on its own.
    """
    return bool(find_mentions(question, brand.aliases))


# Phrases an assistant uses when it doesn't know an entity at all. Kept narrow on
# purpose: "I couldn't find X's pricing" is not the same as "I couldn't find X".
_UNKNOWN_PATTERNS = [
    r"(?:couldn['’]?t|could not|can['’]?t|cannot|was unable to|wasn['’]?t able to|unable to|did not|didn['’]?t)\s+"
    r"(?:find|locate|verify|identify)\s+(?:anything\b|(?:any|much|enough)\s+"
    r"(?:(?:reliable|specific|verifiable|public|credible|solid|concrete|useful)\s+)?"
    r"(?:information|info|details|reviews|data|records?|mentions?|evidence|sources?)\b)",
    r"(?:no|not any|little)\s+(?:reliable\s+|specific\s+|verifiable\s+|public\s+|credible\s+)?(?:information|details|data)\s+(?:about|on|regarding)\b",
    r"(?:not|isn['’]?t|am not|i['’]?m not)\s+familiar with",
    r"(?:not aware of|have no (?:knowledge|record) of)",
    r"(?:didn['’]?t|did not|doesn['’]?t|does not)\s+(?:turn up|return|show up|surface|appear in)\s+"
    r"(?:the|that|this|any|in)\b(?:\s+\w+)?\s*(?:site|website|company|business|results?|search(?:es)?|information)?",
    r"(?:nothing|no results?)\s+(?:came up|turned up|showed up)",
]
_UNKNOWN_RE = re.compile("|".join(f"(?:{p})" for p in _UNKNOWN_PATTERNS), re.I)
UNKNOWN_PROXIMITY = 300


def detect_brand_unknown(text: str, brand: EntitySpec) -> str | None:
    """If the answer says the AI couldn't find / doesn't know the brand, return the evidence snippet."""
    if not text:
        return None
    spans = find_mentions(text, brand.aliases)
    if not spans:
        return None
    for m in _UNKNOWN_RE.finditer(text):
        if any(abs(m.start() - s) <= UNKNOWN_PROXIMITY or abs(m.start() - e) <= UNKNOWN_PROXIMITY for s, e, _ in spans):
            return snippet(text, m.start(), m.end(), radius=120)
    return None
