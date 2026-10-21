"""Helpers shared by provider adapters."""

from __future__ import annotations

import json
import re
from typing import Any

from app.providers.base import ProviderError


def to_dict(obj: Any) -> Any:
    """SDK response objects -> plain dicts/lists, so parsers work on SDK objects and test fixtures alike."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return to_dict(fn())
            except TypeError:
                continue
    if hasattr(obj, "__dict__"):
        return {k: to_dict(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def add_source(sources: dict[str, dict], url: str | None, title: str | None, kind: str, cited_text: str | None = None) -> None:
    """Merge a source, letting "cited" win over "search_result" for the same URL."""
    if not url:
        return
    existing = sources.get(url)
    if existing is None or (existing["type"] != "cited" and kind == "cited"):
        entry = {"url": url, "title": title, "type": kind}
        if cited_text:
            entry["cited_text"] = cited_text[:400]
        sources[url] = entry


def http_status_error(provider: str, status: int, detail: str = "") -> ProviderError:
    """Map an HTTP status from a provider API to a ProviderError."""
    if status in (401, 403):
        return ProviderError(f"{provider} rejected the API key (HTTP {status}).", fatal=True)
    if status == 404:
        return ProviderError(f"{provider} model or endpoint not found (HTTP 404). Check the configured model.", fatal=True)
    if status == 429:
        return ProviderError(f"Rate limited by {provider} after retries.", retryable=True)
    if status == 400 or status == 422:
        return ProviderError(f"{provider} rejected the request (HTTP {status}): {detail[:200]}", fatal=True)
    if status >= 500:
        return ProviderError(f"{provider} server error (HTTP {status}).", retryable=True)
    return ProviderError(f"{provider} API error (HTTP {status}).")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_json_object(text: str) -> dict:
    """Parse a JSON object from model text that may be fenced or have prose around it."""
    t = _FENCE.sub("", (text or "").strip())
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found") from None
        data = json.loads(t[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON is not an object")
    return data


def key_setup(settings, provider: str, server_message: str) -> str:
    """Setup hint: the API keys page when users can add their own keys, otherwise the server .env."""
    if settings.user_keys_enabled:
        from app.services.user_keys import KEY_SPECS

        spec = KEY_SPECS[provider]
        return f"Add your {spec.label} API key on the API keys page (create one at {spec.url})."
    return server_message
