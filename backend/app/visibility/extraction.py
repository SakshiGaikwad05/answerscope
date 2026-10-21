"""AI-assisted extraction of the businesses an answer recommends (optional, NVIDIA model).

Runs only when an NVIDIA-hosted analysis model is configured, so it never spends
assistant credits. The model's output is checked against the answer text: any
business name that doesn't literally appear in the answer is dropped, so the
extraction can't add businesses the assistant never mentioned.
"""

from __future__ import annotations

import logging
import re

from app.providers.base import ProviderError

logger = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "businesses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "position": {"type": "integer"}},
                "required": ["name", "position"],
            },
        }
    },
    "required": ["businesses"],
}

SYSTEM = (
    "You extract structured data from an AI assistant's answer. List every specific business, brand, shop, "
    "clinic, product or service provider that the answer recommends or presents as an option, in the order they "
    "first appear (position 1 = first). Copy each name exactly as written in the answer. Do not add any business "
    "that is not named in the answer. Ignore websites cited only as sources."
)


def _appears(name: str, text: str) -> bool:
    return bool(name) and re.search(re.escape(name.strip()), text, re.I) is not None


def extract_businesses(provider, question: str, answer_text: str) -> list[dict] | None:
    """[{name, position}] verified against the answer text, or None if extraction failed."""
    if not answer_text.strip():
        return []
    try:
        data = provider.complete_json(SYSTEM, f"Question: {question}\n\nAnswer:\n{answer_text[:12000]}", SCHEMA)
    except ProviderError as exc:
        logger.info("entity extraction failed: %s", exc)
        return None
    seen, out = set(), []
    for item in data.get("businesses") or []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:200]
        if not name or name.lower() in seen or not _appears(name, answer_text):
            continue
        seen.add(name.lower())
        out.append({"name": name, "position": len(out) + 1})
    return out
