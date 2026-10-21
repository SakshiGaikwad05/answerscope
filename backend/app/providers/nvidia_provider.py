"""NVIDIA-hosted open models (e.g. Llama 3.3 70B), used for ANALYSIS only.

Docs (verified): POST https://integrate.api.nvidia.com/v1/chat/completions with
`Authorization: Bearer $NVIDIA_API_KEY`; the OpenAI Python client works with
base_url "https://integrate.api.nvidia.com/v1"; model "meta/llama-3.3-70b-instruct";
max_tokens up to 4096; no structured-output parameter is documented, so JSON is
requested in the prompt and parsed defensively.

These models are not ChatGPT, Claude, Gemini or Perplexity and have no live web
search, so they are never used to measure AI visibility, only to generate
questions, extract entities from real assistant answers, and draft text.
"""

from __future__ import annotations

import json
import logging

from app.config import Settings
from app.providers.base import ProviderError, ProviderNotConfiguredError
from app.providers.common import key_setup, parse_json_object

logger = logging.getLogger(__name__)


class NvidiaAnalysisProvider:
    name = "nvidia"
    display_name = "NVIDIA-hosted model (analysis only)"

    def __init__(self, settings: Settings, client=None) -> None:
        self.settings = settings
        self._client = client

    def is_configured(self) -> bool:
        return self._client is not None or Settings.has_key(self.settings.nvidia_api_key)

    def setup_instructions(self) -> str:
        return key_setup(self.settings, "nvidia", "Set NVIDIA_API_KEY in backend/.env (from build.nvidia.com) and restart the backend. Optional: AEO_NVIDIA_MODEL.")

    @property
    def model(self) -> str:
        return self.settings.nvidia_model

    @property
    def client(self):
        if self._client is None:
            if not Settings.has_key(self.settings.nvidia_api_key):
                raise ProviderNotConfiguredError("NVIDIA API key is not configured")
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.settings.nvidia_base_url,
                api_key=self.settings.nvidia_api_key.get_secret_value(),
                timeout=self.settings.provider_timeout_seconds,
                max_retries=3,
            )
        return self._client

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        import openai

        instructions = (
            f"{system}\n\nRespond with ONLY a JSON object (no prose, no code fences) that matches this JSON Schema:\n"
            + json.dumps(schema)
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": instructions}, {"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=4096,
            )
        except openai.AuthenticationError as exc:
            raise ProviderError("NVIDIA rejected the API key.", fatal=True) from exc
        except openai.NotFoundError as exc:
            raise ProviderError(f"NVIDIA model '{self.model}' was not found.", fatal=True) from exc
        except openai.RateLimitError as exc:
            raise ProviderError("Rate limited by the NVIDIA API after retries.", retryable=True) from exc
        except openai.APITimeoutError as exc:
            raise ProviderError("The request to the NVIDIA API timed out.", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"NVIDIA API error (HTTP {exc.status_code}).", retryable=exc.status_code >= 500) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("Could not connect to the NVIDIA API.", retryable=True) from exc
        choice = (resp.choices or [None])[0]
        text = getattr(getattr(choice, "message", None), "content", None) or ""
        if getattr(choice, "finish_reason", None) == "length":
            raise ProviderError("The NVIDIA model's answer was cut off (max_tokens).")
        try:
            return parse_json_object(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("The NVIDIA model returned malformed JSON.") from exc
