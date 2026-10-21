"""Perplexity via the Agent API (the successor to the Sonar API).

Docs (verified): POST https://api.perplexity.ai/v1/agent with `input` and a
`preset` ("fast", "low", "medium", "high"); every preset includes web search.
The answer is in `output` items of type "message" (content parts of type
"output_text" with `url_citation` annotations); items of type "search_results"
list the pages consulted. API answers can differ from the Perplexity app.
"""

from __future__ import annotations

import logging
import time

import httpx

from app.config import Settings
from app.providers.base import AIProvider, ProviderAnswer, ProviderError, ProviderNotConfiguredError
from app.providers.common import add_source, http_status_error, key_setup

logger = logging.getLogger(__name__)

AGENT_URL = "https://api.perplexity.ai/v1/agent"
SEARCH_URL = "https://api.perplexity.ai/search"
INSTRUCTIONS = (
    "Answer the user's question accurately and concisely. If you recommend products, services or businesses, name them."
)


def parse_agent_response(data: dict) -> tuple[str, list[dict]]:
    texts: list[str] = []
    sources: dict[str, dict] = {}
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") in ("output_text", "text"):
                    texts.append(part.get("text") or "")
                    for ann in part.get("annotations") or []:
                        if ann.get("type") in ("url_citation", "citation"):
                            add_source(sources, ann.get("url"), ann.get("title"), "cited")
        elif item.get("type") == "search_results":
            for res in item.get("results") or []:
                add_source(sources, res.get("url"), res.get("title"), "search_result")
    return "".join(texts).strip(), list(sources.values())


class PerplexityProvider(AIProvider):
    name = "perplexity"
    display_name = "Perplexity (Agent API)"
    assistant = "Perplexity"
    experience = "Perplexity Agent API with web search. Close to Perplexity's answers, but not identical to the Perplexity app."

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport

    def is_configured(self) -> bool:
        return Settings.has_key(self.settings.perplexity_api_key)

    def setup_instructions(self) -> str:
        return key_setup(self.settings, "perplexity", "Set PERPLEXITY_API_KEY in backend/.env (from perplexity.ai/settings/api) and restart the backend. Optional: AEO_PERPLEXITY_PRESET.")

    @property
    def model(self) -> str:
        return f"preset:{self.settings.perplexity_preset}"

    def conditions(self) -> dict:
        return {"provider": self.name, "model": self.model, "web_search": True, "system_prompt": INSTRUCTIONS}

    def _post(self, url: str, body: dict) -> dict:
        if not self.is_configured():
            raise ProviderNotConfiguredError("Perplexity API key is not configured")
        headers = {"Authorization": f"Bearer {self.settings.perplexity_api_key.get_secret_value()}"}
        last: ProviderError | None = None
        with httpx.Client(timeout=self.settings.provider_timeout_seconds, transport=self._transport) as client:
            for attempt in range(3):
                try:
                    resp = client.post(url, json=body, headers=headers)
                except httpx.TimeoutException as exc:
                    last = ProviderError("The request to Perplexity timed out.", retryable=True)
                    last.__cause__ = exc
                except httpx.HTTPError as exc:
                    last = ProviderError("Could not connect to the Perplexity API.", retryable=True)
                    last.__cause__ = exc
                else:
                    if resp.status_code == 200:
                        return resp.json()
                    last = http_status_error("Perplexity", resp.status_code, resp.text)
                    if not last.retryable:
                        raise last
                if attempt < 2:
                    time.sleep(2 ** attempt)
        assert last is not None
        raise last

    def answer(self, question: str) -> ProviderAnswer:
        started = time.monotonic()
        data = self._post(AGENT_URL, {"preset": self.settings.perplexity_preset, "input": question, "instructions": INSTRUCTIONS})
        if data.get("error"):
            raise ProviderError(f"Perplexity returned an error: {str(data['error'])[:200]}")
        if data.get("status") not in (None, "completed"):
            raise ProviderError(f"Perplexity response did not complete (status: {data.get('status')}).")
        text, sources = parse_agent_response(data)
        if not text:
            raise ProviderError("Perplexity returned no answer text.")
        latency = int((time.monotonic() - started) * 1000)
        logger.info("perplexity answer ok model=%s sources=%d latency_ms=%d", data.get("model"), len(sources), latency)
        return ProviderAnswer(text=text, model=data.get("model") or self.model, sources=sources, latency_ms=latency)

    def search(self, query: str, *, max_results: int = 10, country: str | None = None) -> list[dict]:
        """Perplexity Search API: ranked web results [{url, title, snippet}]."""
        body: dict = {"query": query, "max_results": max_results}
        if country:
            body["country"] = country.upper()
        data = self._post(SEARCH_URL, body)
        return [
            {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("snippet")}
            for r in data.get("results") or []
            if r.get("url")
        ]
