"""Provider adapter interface.

To add a provider (e.g. OpenAI, Gemini, Perplexity), subclass `AIProvider`,
implement `is_configured`, `answer` and (optionally) `complete_json`, and
register it in `app/providers/registry.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ProviderError(Exception):
    """An AI provider call failed.

    `fatal` errors (bad credentials, unknown model) abort the whole run instead
    of being recorded per question.
    """

    def __init__(self, message: str, *, fatal: bool = False, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.fatal = fatal
        self.retryable = retryable


class ProviderNotConfiguredError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, fatal=True)


@dataclass
class ProviderAnswer:
    text: str
    model: str
    # [{url, title, type: "cited" | "search_result", cited_text?}]
    sources: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    latency_ms: int | None = None


class AIProvider(ABC):
    name: str = "base"
    display_name: str = "Base provider"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def setup_instructions(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    def conditions(self) -> dict:
        """Settings that affect answers; stored with each run for comparability."""
        return {"provider": self.name, "model": self.model}

    @abstractmethod
    def answer(self, question: str) -> ProviderAnswer:
        """Ask the provider the question exactly as a user would and return the answer."""

    def complete_json(self, system: str, prompt: str, schema: dict) -> dict:
        """Return a JSON object matching `schema`. Optional; used for question generation."""
        raise NotImplementedError

    def status(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "configured": self.is_configured(),
            "model": self.model,
            "setup_instructions": None if self.is_configured() else self.setup_instructions(),
            "conditions": self.conditions(),
        }
