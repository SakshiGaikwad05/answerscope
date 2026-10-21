"""ChatGPT via the OpenAI Responses API with the `web_search` tool.

Docs (verified): tool type "web_search"; answers in `message` output items with
`url_citation` annotations (url, title); `include=["web_search_call.action.sources"]`
returns every URL consulted; `user_location` {type: "approximate", city, region, country}
localizes search. API answers can differ from the ChatGPT app.
"""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.providers.base import AIProvider, ProviderAnswer, ProviderError, ProviderNotConfiguredError, SearchLocation
from app.providers.common import add_source, key_setup, to_dict

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question accurately and concisely. "
    "If you recommend products, services or businesses, name them."
)


def parse_response(data: dict) -> tuple[str, list[dict]]:
    """(answer text, sources) from a Responses API response dict."""
    texts: list[str] = []
    sources: dict[str, dict] = {}
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") in ("output_text", "text"):
                    texts.append(part.get("text") or "")
                    for ann in part.get("annotations") or []:
                        if ann.get("type") == "url_citation":
                            add_source(sources, ann.get("url"), ann.get("title"), "cited")
        elif item.get("type") == "web_search_call":
            for src in ((item.get("action") or {}).get("sources") or []):
                add_source(sources, src.get("url"), src.get("title"), "search_result")
    text = "".join(texts).strip() or (data.get("output_text") or "").strip()
    return text, list(sources.values())


class OpenAIProvider(AIProvider):
    name = "openai"
    display_name = "ChatGPT (OpenAI API)"
    assistant = "ChatGPT"
    experience = "OpenAI Responses API with live web search. Close to ChatGPT search, but not identical to the ChatGPT app."
    supports_location = True

    def __init__(self, settings: Settings, client=None) -> None:
        self.settings = settings
        self._client = client

    def is_configured(self) -> bool:
        return self._client is not None or Settings.has_key(self.settings.openai_api_key)

    def setup_instructions(self) -> str:
        return key_setup(self.settings, "openai", "Set OPENAI_API_KEY in backend/.env (from platform.openai.com) and restart the backend. Optional: AEO_OPENAI_MODEL.")

    @property
    def model(self) -> str:
        return self.settings.openai_model

    def conditions(self) -> dict:
        return {"provider": self.name, "model": self.model, "web_search": True, "system_prompt": SYSTEM_PROMPT}

    @property
    def client(self):
        if self._client is None:
            if not Settings.has_key(self.settings.openai_api_key):
                raise ProviderNotConfiguredError("OpenAI API key is not configured")
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                timeout=self.settings.provider_timeout_seconds,
                max_retries=3,
            )
        return self._client

    def answer(self, question: str, location: SearchLocation | None = None) -> ProviderAnswer:
        import openai

        tool: dict = {"type": "web_search"}
        if location and not location.is_empty():
            tool["user_location"] = location.as_user_location()
        started = time.monotonic()
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=question,
                tools=[tool],
                include=["web_search_call.action.sources"],
            )
        except openai.AuthenticationError as exc:
            raise ProviderError("OpenAI rejected the API key.", fatal=True) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError("The OpenAI API key lacks permission for this request.", fatal=True) from exc
        except openai.NotFoundError as exc:
            raise ProviderError(f"OpenAI model '{self.model}' was not found for this key.", fatal=True) from exc
        except openai.RateLimitError as exc:
            raise ProviderError("Rate limited by OpenAI (or out of credits) after retries.", retryable=True) from exc
        except openai.BadRequestError as exc:
            raise ProviderError(f"OpenAI rejected the request: {exc.message}", fatal=True) from exc
        except openai.APITimeoutError as exc:
            raise ProviderError("The request to OpenAI timed out.", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"OpenAI API error (HTTP {exc.status_code}).", retryable=exc.status_code >= 500) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not connect to the OpenAI API.", retryable=True) from exc
        data = to_dict(response)
        text, sources = parse_response(data)
        if not text:
            raise ProviderError(f"OpenAI returned no answer text (status: {data.get('status')}).")
        latency = int((time.monotonic() - started) * 1000)
        logger.info("openai answer ok model=%s sources=%d latency_ms=%d", data.get("model"), len(sources), latency)
        return ProviderAnswer(text=text, model=data.get("model") or self.model, sources=sources,
                              stop_reason=data.get("status"), latency_ms=latency)
