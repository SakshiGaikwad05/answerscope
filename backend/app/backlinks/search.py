"""Web search backends for backlink / brand-mention discovery, with a database cache.

Only official search APIs are used (no scraping of search engines):
* Brave Search API: GET https://api.search.brave.com/res/v1/web/search, header
  X-Subscription-Token, params q / count (max 20) / country; results in web.results[].
* Perplexity Search API (see providers/perplexity_provider.py).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import ApiCache
from app.providers.base import ProviderError
from app.providers.common import http_status_error

logger = logging.getLogger(__name__)
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
CACHE_DAYS = 7


class BraveSearch:
    name = "brave"

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def search(self, query: str, *, max_results: int = 10, country: str | None = None) -> list[dict]:
        params = {"q": query, "count": min(max_results, 20)}
        if country:
            params["country"] = country.upper()
        headers = {"X-Subscription-Token": self.settings.brave_api_key.get_secret_value(), "Accept": "application/json"}
        try:
            with httpx.Client(timeout=20, transport=self._transport) as client:
                resp = client.get(BRAVE_URL, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderError("The Brave Search API timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the Brave Search API.", retryable=True) from exc
        if resp.status_code != 200:
            raise http_status_error("Brave Search", resp.status_code, resp.text)
        results = (resp.json().get("web") or {}).get("results") or []
        return [{"url": r.get("url"), "title": r.get("title"), "snippet": r.get("description")} for r in results if r.get("url")]


def backend_name(backend) -> str:
    return getattr(backend, "name", "search")


def cached_search(db: Session, backend, query: str, *, max_results: int = 10, country: str | None = None) -> list[dict]:
    """Search with a 7-day cache keyed by backend + query + country, so repeats cost nothing."""
    key = hashlib.sha256(json.dumps([backend_name(backend), query, max_results, (country or "").upper()]).encode()).hexdigest()
    now = datetime.now(timezone.utc)
    row = db.get(ApiCache, key)
    if row is not None:
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
        if expires > now:
            return row.value.get("results", [])
        db.delete(row)
        db.flush()
    results = backend.search(query, max_results=max_results, country=country)
    db.add(ApiCache(key=key, kind="web_search", value={"query": query, "results": results}, expires_at=now + timedelta(days=CACHE_DAYS)))
    db.flush()
    return results
