"""Position in a recommendation list, and location relevance, derived from answer text.

Position is reported only when it is determinable: the answer must contain a list
(numbered, bulleted, or markdown-heading items) with at least two entries. Then the
brand's position is the index of the first list item that mentions it. Answers
without a list get no position rather than a guessed one.
"""

from __future__ import annotations

import re

from app.visibility.detection import EntitySpec, find_mentions

_ITEM = re.compile(r"^\s{0,6}(?:#{1,4}\s*)?(?:\d{1,2}[.)]|[-*•]|\*\*\d{1,2}[.)]?\*\*)\s+(.+)$")
MIN_LIST_ITEMS = 2


def list_items(text: str) -> list[str]:
    """Top-level list entries (one line each) in the order they appear."""
    items = []
    for line in (text or "").splitlines():
        m = _ITEM.match(line)
        if m and m.group(1).strip():
            items.append(m.group(1).strip())
    return items


def brand_position(text: str, brand: EntitySpec) -> dict | None:
    """{"position": k or None, "listed": n} if the answer has a list, else None (not determinable)."""
    items = list_items(text)
    if len(items) < MIN_LIST_ITEMS:
        return None
    for i, item in enumerate(items, start=1):
        if find_mentions(item, brand.aliases):
            return {"position": i, "listed": len(items)}
    return {"position": None, "listed": len(items)}


def location_terms(location: dict | None) -> list[str]:
    loc = location or {}
    terms = [loc.get("city"), loc.get("service_area")]
    out = []
    for t in terms:
        for part in re.split(r"[,/;]| and ", t or ""):
            part = part.strip()
            if len(part) >= 3 and part.lower() not in {o.lower() for o in out}:
                out.append(part)
    return out


def mentions_location(text: str, terms: list[str]) -> bool | None:
    """True/False if the business has a location on file, None if not (relevance can't be judged)."""
    if not terms:
        return None
    lowered = (text or "").lower()
    return any(re.search(r"(?<![\w])" + re.escape(t.lower()) + r"(?![\w])", lowered) for t in terms)
