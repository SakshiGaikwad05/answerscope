"""Gemini via the Google GenAI Interactions API with the `google_search` tool.

Docs (verified): `client.interactions.create(model=..., input=..., tools=[{"type": "google_search"}])`
(google-genai >= 2.3.0); answer in `output_text`; citations are `url_citation`
annotations on `model_output` text blocks. Grounding citations can be Google
redirect links whose title is the source domain, so the title is kept for matching.
Search suggestions are not displayed by this app. API answers can differ from the Gemini app.
"""

from __future__ import annotations

import logging
import time

from app.config import Settings
from app.providers.base import AIProvider, ProviderAnswer, ProviderError, ProviderNotConfiguredError
from app.providers.common import add_source, key_setup, to_dict

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question accurately and concisely. "
    "If you recommend products, services or businesses, name them."
)


def parse_interaction(data: dict) -> tuple[str, list[dict]]:
    texts: list[str] = []
    sources: dict[str, dict] = {}
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for block in step.get("content") or []:
            if block.get("type") != "text":
                continue
            texts.append(block.get("text") or "")
            for ann in block.get("annotations") or []:
                if ann.get("type") == "url_citation":
                    add_source(sources, ann.get("url"), ann.get("title"), "cited")
    text = (data.get("output_text") or "").strip() or "".join(texts).strip()
    return text, list(sources.values())


class GeminiProvider(AIProvider):
    name = "gemini"
    display_name = "Gemini (Google AI API)"
    assistant = "Gemini"
    experience = "Gemini API grounded with Google Search. Close to Gemini's search answers, but not identical to the Gemini app."

    def __init__(self, settings: Settings, client=None) -> None:
        self.settings = settings
        self._client = client

    def is_configured(self) -> bool:
        return self._client is not None or Settings.has_key(self.settings.gemini_api_key)

    def setup_instructions(self) -> str:
        return key_setup(self.settings, "gemini", "Set GEMINI_API_KEY in backend/.env (from aistudio.google.com) and restart the backend. Optional: AEO_GEMINI_MODEL.")

    @property
    def model(self) -> str:
        return self.settings.gemini_model

    def conditions(self) -> dict:
        return {"provider": self.name, "model": self.model, "web_search": True, "system_prompt": SYSTEM_PROMPT}

    @property
    def client(self):
        if self._client is None:
            if not Settings.has_key(self.settings.gemini_api_key):
                raise ProviderNotConfiguredError("Gemini API key is not configured")
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key.get_secret_value())
        return self._client

    def answer(self, question: str) -> ProviderAnswer:
        from google.genai import errors

        started = time.monotonic()
        try:
            interaction = self.client.interactions.create(
                model=self.model,
                input=question,
                system_instruction=SYSTEM_PROMPT,
                tools=[{"type": "google_search"}],
                store=False,
                timeout=self.settings.provider_timeout_seconds,
            )
        except errors.APIError as exc:
            code = getattr(exc, "code", None) or 0
            if code in (401, 403):
                raise ProviderError("Gemini rejected the API key.", fatal=True) from exc
            if code == 404:
                raise ProviderError(f"Gemini model '{self.model}' was not found.", fatal=True) from exc
            if code == 429:
                raise ProviderError("Rate limited by Gemini after retries.", retryable=True) from exc
            if code == 400:
                raise ProviderError(f"Gemini rejected the request: {getattr(exc, 'message', exc)}", fatal=True) from exc
            raise ProviderError(f"Gemini API error ({code or 'unknown'}).", retryable=code >= 500) from exc
        except Exception as exc:  # noqa: BLE001 - network errors surface as various httpx exceptions
            if "timeout" in type(exc).__name__.lower():
                raise ProviderError("The request to Gemini timed out.", retryable=True) from exc
            raise ProviderError(f"Could not reach the Gemini API ({type(exc).__name__}).", retryable=True) from exc
        data = to_dict(interaction)
        if isinstance(data, dict) and not data.get("output_text"):
            data["output_text"] = getattr(interaction, "output_text", None)
        text, sources = parse_interaction(data)
        if not text:
            raise ProviderError("Gemini returned no answer text.")
        latency = int((time.monotonic() - started) * 1000)
        logger.info("gemini answer ok model=%s sources=%d latency_ms=%d", self.model, len(sources), latency)
        return ProviderAnswer(text=text, model=data.get("model") or self.model, sources=sources, latency_ms=latency)
