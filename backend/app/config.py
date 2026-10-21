"""Application settings, loaded from backend/.env and environment variables.

backend/.env takes priority over environment variables, so a variable exported
in your shell for another tool (e.g. a different ANTHROPIC_API_KEY) can't
silently override the app's configuration. Settings missing from .env still
fall back to environment variables, then to the defaults below.

Secrets (API keys) live only here and are never returned by the API or logged.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Absolute path, so the file is found regardless of the working directory.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
# Set to "1" to ignore backend/.env entirely (the test suite does this).
DISABLE_ENV_FILE_VAR = "AEO_DISABLE_ENV_FILE"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Earlier sources win: explicit arguments, then backend/.env, then the environment.
        if os.environ.get(DISABLE_ENV_FILE_VAR) == "1":
            return init_settings, env_settings, file_secret_settings
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    # Set DATABASE_URL (with its password) in backend/.env; no credentials live in code.
    database_url: str = "postgresql+psycopg://localhost:5432/aeo"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    # Crawler limits
    crawl_max_pages: int = Field(default=15, ge=1, le=100)
    crawl_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    crawl_max_bytes: int = Field(default=2_000_000, ge=10_000)
    crawl_max_redirects: int = Field(default=5, ge=0, le=10)
    crawl_max_seconds: float = Field(default=120.0, gt=0, le=600)
    crawl_user_agent: str = "AEOAuditBot/0.1 (+https://github.com/; website audit tool)"

    # Anthropic (Claude) provider. Leave the key empty to disable AI features.
    # Only the key uses the SDK's standard name; the other options are prefixed
    # with AEO_ so variables exported for other tools (e.g. ANTHROPIC_MODEL,
    # ANTHROPIC_BASE_URL) can't silently change how visibility tests run.
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str = Field(default="https://api.anthropic.com", validation_alias=AliasChoices("AEO_ANTHROPIC_BASE_URL"))
    anthropic_model: str = Field(default="claude-opus-5-5", validation_alias=AliasChoices("AEO_ANTHROPIC_MODEL"))
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="medium", validation_alias=AliasChoices("AEO_ANTHROPIC_EFFORT")
    )
    anthropic_web_search: bool = Field(default=True, validation_alias=AliasChoices("AEO_ANTHROPIC_WEB_SEARCH"))
    anthropic_web_search_max_uses: int = Field(
        default=3, ge=1, le=10, validation_alias=AliasChoices("AEO_ANTHROPIC_WEB_SEARCH_MAX_USES")
    )
    anthropic_server_fallbacks: bool = Field(default=True, validation_alias=AliasChoices("AEO_ANTHROPIC_SERVER_FALLBACKS"))
    anthropic_timeout_seconds: float = Field(default=180.0, validation_alias=AliasChoices("AEO_ANTHROPIC_TIMEOUT_SECONDS"))

    visibility_max_questions: int = Field(default=20, ge=1, le=50)

    # --- Users' own API keys ("bring your own key"). Saved keys are encrypted with this Fernet key;
    # generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Changing it makes saved keys unreadable (users are asked to re-enter them). Unset = saving keys is disabled.
    secrets_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AEO_SECRETS_KEY"))
    # Shared secret the Next.js frontend sends with every /api request (BACKEND_PROXY_SECRET there).
    # When set, the API refuses requests without it, so a publicly reachable backend can't be called directly
    # and the client IP it passes (x-aeo-client-ip) can be trusted for rate limiting.
    proxy_secret: SecretStr | None = Field(default=None, validation_alias=AliasChoices("AEO_PROXY_SECRET"))
    # false: never use this server's own provider keys for users (public deployments where users pay for their tests)
    use_server_api_keys: bool = Field(default=True, validation_alias=AliasChoices("AEO_USE_SERVER_API_KEYS"))

    # --- Other AI assistants (official APIs). Leave a key empty to skip that assistant.
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-5.5", validation_alias=AliasChoices("AEO_OPENAI_MODEL"))
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.8-flash", validation_alias=AliasChoices("AEO_GEMINI_MODEL"))
    perplexity_api_key: SecretStr | None = None
    # Agent API preset; all presets include web search. "low" = everyday research (formerly pro-search).
    perplexity_preset: Literal["fast", "low", "medium", "high"] = Field(
        default="low", validation_alias=AliasChoices("AEO_PERPLEXITY_PRESET")
    )
    provider_timeout_seconds: float = Field(default=120.0, gt=0, le=600, validation_alias=AliasChoices("AEO_PROVIDER_TIMEOUT_SECONDS"))

    # --- NVIDIA-hosted models (analysis only: questions, entity extraction, outreach drafts).
    nvidia_api_key: SecretStr | None = None
    nvidia_base_url: str = Field(default="https://integrate.api.nvidia.com/v1", validation_alias=AliasChoices("AEO_NVIDIA_BASE_URL"))
    nvidia_model: str = Field(default="meta/llama-3.3-70b-instruct", validation_alias=AliasChoices("AEO_NVIDIA_MODEL"))

    # --- Web search APIs for backlink / brand-mention discovery (Perplexity Search API is used if its key is set)
    brave_api_key: SecretStr | None = None

    # Accounts
    allow_registration: bool = True
    session_days: int = Field(default=30, ge=1, le=365)
    # Set to true when served over HTTPS (production) so the session cookie is never sent in clear text.
    cookie_secure: bool = False

    # Usage limits for AI actions that cost money (rolling 24 hours). 0 disables the action.
    quota_visibility_runs_per_user_per_day: int = Field(default=8, ge=0)
    quota_question_generations_per_user_per_day: int = Field(default=10, ge=0)
    quota_fix_generations_per_user_per_day: int = Field(default=20, ge=0)
    # Hard caps across all users: a ceiling on what the server's API key can be used for per day.
    quota_visibility_runs_global_per_day: int = Field(default=60, ge=0)
    quota_question_generations_global_per_day: int = Field(default=100, ge=0)
    quota_fix_generations_global_per_day: int = Field(default=200, ge=0)
    quota_backlink_discoveries_per_user_per_day: int = Field(default=3, ge=0)
    quota_backlink_discoveries_global_per_day: int = Field(default=30, ge=0)

    # Request rate limits (per client IP / per user, per minute)
    rate_limit_auth_per_minute: int = Field(default=10, ge=1)
    rate_limit_writes_per_minute: int = Field(default=30, ge=1)

    # "inline": jobs run in the API process (simple local setup).
    # "worker": the API only queues jobs; run `python -m app.worker` separately (production).
    job_mode: Literal["inline", "worker"] = "inline"

    # Render JavaScript-only sites in a headless browser (needs `playwright install chromium-headless-shell`)
    render_js: bool = True
    render_max_pages: int = Field(default=8, ge=1, le=30)
    render_timeout_seconds: float = Field(default=20.0, gt=0, le=60)

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Hosts like Render and Heroku hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @staticmethod
    def has_key(value: SecretStr | None) -> bool:
        return bool(value and value.get_secret_value().strip())

    @property
    def user_keys_enabled(self) -> bool:
        return self.has_key(self.secrets_key)

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
