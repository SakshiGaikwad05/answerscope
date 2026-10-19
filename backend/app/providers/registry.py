from app.config import Settings, get_settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import AIProvider

# Register additional providers here: name -> factory(settings) -> AIProvider
PROVIDER_FACTORIES = {
    AnthropicProvider.name: AnthropicProvider,
}

_overrides: dict[str, AIProvider] = {}


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


def override_provider(name: str, provider: AIProvider | None) -> None:
    """Swap in a provider implementation (used by tests)."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider
        PROVIDER_FACTORIES.setdefault(name, lambda _s: provider)
