"""Anthropic Claude provider (official `anthropic` SDK).

Answers are generated through the Messages API, optionally with Anthropic's
server-side web search tool so the model can browse and cite sources. API
answers may differ from what the consumer Claude app shows for the same question.
"""

from __future__ import annotations

import json
import logging
import time

import anthropic

from app.config import Settings
from app.providers.base import AIProvider, ProviderAnswer, ProviderError, ProviderNotConfiguredError

logger = logging.getLogger(__name__)

ANSWER_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question accurately and concisely. "
    "If you recommend products, services or companies, name them."
)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PAUSE_CONTINUATIONS = 3


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def parse_response_content(content: list) -> tuple[str, list[dict]]:
    """Return (answer text, sources) from Messages API content blocks.

    Sources include every URL the model cited inline (`type: cited`) and the web
    search results it saw (`type: search_result`).
    """
    texts: list[str] = []
    sources: dict[str, dict] = {}
    for block in content or []:
        btype = _get(block, "type")
        if btype == "text":
            texts.append(_get(block, "text", "") or "")
            for cit in _get(block, "citations") or []:
                url = _get(cit, "url")
                if not url:
                    continue
                entry = sources.get(url)
                if entry is None or entry["type"] != "cited":
                    sources[url] = {
                        "url": url,
                        "title": _get(cit, "title"),
                        "type": "cited",
                        "cited_text": (_get(cit, "cited_text") or "")[:400] or None,
                    }
        elif btype == "web_search_tool_result":
            results = _get(block, "content")
            if isinstance(results, list):  # a dict here means a tool error
                for res in results:
                    url = _get(res, "url")
                    if url and url not in sources:
                        sources[url] = {"url": url, "title": _get(res, "title"), "type": "search_result"}
    return "".join(texts).strip(), list(sources.values())


class AnthropicProvider(AIProvider):
    name = "anthropic"
    display_name = "Anthropic Claude (API)"

    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None) -> None:
        self.settings = settings
        self._client = client

    def is_configured(self) -> bool:
        return self._client is not None or self.settings.anthropic_configured

    def setup_instructions(self) -> str:
        return (
            "Set ANTHROPIC_API_KEY in backend/.env (create a key at https://console.anthropic.com/), "
            "then restart the backend. Optional: AEO_ANTHROPIC_MODEL, AEO_ANTHROPIC_WEB_SEARCH."
        )

    @property
    def model(self) -> str:
        return self.settings.anthropic_model

    def conditions(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "effort": self.settings.anthropic_effort,
            "web_search": self.settings.anthropic_web_search,
            "web_search_max_uses": self.settings.anthropic_web_search_max_uses if self.settings.anthropic_web_search else 0,
            "system_prompt": ANSWER_SYSTEM_PROMPT,
            "server_fallbacks": self.settings.anthropic_server_fallbacks,
        }

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            if not self.settings.anthropic_configured:
                raise ProviderNotConfiguredError("Anthropic API key is not configured")
            assert self.settings.anthropic_api_key is not None
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                base_url=self.settings.anthropic_base_url,
                timeout=self.settings.anthropic_timeout_seconds,
                max_retries=3,
            )
        return self._client

    def _create(self, **kwargs):
        """Call the Messages API, translating SDK errors into ProviderError."""
        try:
            if self.settings.anthropic_server_fallbacks:
                return self.client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs
                )
            return self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic rejected the API key (authentication failed).", fatal=True) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("The Anthropic API key lacks permission for this request.", fatal=True) from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Model '{self.model}' was not found for this API key.", fatal=True) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Rate limited by Anthropic after retries.", retryable=True) from exc
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"Anthropic rejected the request: {exc.message}", fatal=True) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("The request to Anthropic timed out.", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                f"Anthropic API error (HTTP {exc.status_code}).", retryable=exc.status_code >= 500
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Could not connect to the Anthropic API.", retryable=True) from exc

    def answer(self, question: str) -> ProviderAnswer:
        tools = []
        if self.settings.anthropic_web_search:
            tools.append(
                {
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": self.settings.anthropic_web_search_max_uses,
                }
            )
        messages: list[dict] = [{"role": "user", "content": question}]
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 16000,
            "system": ANSWER_SYSTEM_PROMPT,
            "output_config": {"effort": self.settings.anthropic_effort},
        }
        if tools:
            kwargs["tools"] = tools

        started = time.monotonic()
        content: list = []
        response = None
        for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
            response = self._create(messages=messages, **kwargs)
            content.extend(response.content)
            if response.stop_reason != "pause_turn":
                break
            # Server-side tool loop paused; resend so the server resumes where it left off.
            messages = [messages[0], {"role": "assistant", "content": content}]
        assert response is not None
        latency = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            raise ProviderError("The model declined to answer this question.")
        text, sources = parse_response_content(content)
        if not text:
            raise ProviderError(f"The model returned no answer text (stop reason: {response.stop_reason}).")
        logger.info(
            "anthropic answer ok model=%s stop=%s sources=%d latency_ms=%d request_id=%s",
            response.model, response.stop_reason, len(sources), latency, getattr(response, "_request_id", None),
        )
        return ProviderAnswer(
            text=text, model=response.model, sources=sources, stop_reason=response.stop_reason, latency_ms=latency
        )

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        response = self._create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "refusal":
            raise ProviderError("The model declined the request.")
        text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("The model returned malformed JSON.") from exc
        if not isinstance(data, dict):
            raise ProviderError("The model returned JSON of an unexpected shape.")
        return data
