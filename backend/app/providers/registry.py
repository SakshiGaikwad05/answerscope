from app.config import Settings, get_settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import AIProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.nvidia_provider import NvidiaAnalysisProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.perplexity_provider import PerplexityProvider

# AI assistants whose answers are measured for visibility, in display order.
# Register additional providers here: name -> factory(settings) -> AIProvider
PROVIDER_FACTORIES = {
    OpenAIProvider.name: OpenAIProvider,
    AnthropicProvider.name: AnthropicProvider,
    GeminiProvider.name: GeminiProvider,
    PerplexityProvider.name: PerplexityProvider,
}

_overrides: dict[str, object] = {}


def get_provider(name: str, settings: Settings | None = None) -> AIProvider:
    if name in _overrides:
        return _overrides[name]
    factory = PROVIDER_FACTORIES.get(name)
    if factory is None:
        raise KeyError(name)
    return factory(settings or get_settings())


def all_providers(settings: Settings | None = None) -> list[AIProvider]:
    return [get_provider(name, settings) for name in PROVIDER_FACTORIES]


def first_configured(settings: Settings | None = None) -> AIProvider | None:
    return next((p for p in all_providers(settings) if p.is_configured()), None)


def analysis_provider(settings: Settings | None = None):
    """Model used for analysis tasks (questions, entity extraction, drafts).

    NVIDIA-hosted model if NVIDIA_API_KEY is set, otherwise Claude, otherwise None
    (callers then fall back to deterministic templates).
    """
    if "nvidia" in _overrides:
        return _overrides["nvidia"]
    nvidia = NvidiaAnalysisProvider(settings or get_settings())
    if nvidia.is_configured():
        return nvidia
    claude = get_provider("anthropic", settings)
    return claude if claude.is_configured() else None


def search_backend(settings: Settings | None = None):
    """Web search API for backlink / brand-mention discovery, or None if none is configured."""
    if "search" in _overrides:
        return _overrides["search"]
    from app.backlinks.search import BraveSearch

    s = settings or get_settings()
    if Settings.has_key(s.brave_api_key):
        return BraveSearch(s)
    perplexity = PerplexityProvider(s)
    return perplexity if perplexity.is_configured() else None


def override_provider(name: str, provider) -> None:
    """Swap in a provider implementation (used by tests)."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider
        if name not in ("nvidia", "search"):
            PROVIDER_FACTORIES.setdefault(name, lambda _s: provider)
