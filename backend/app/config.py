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

from pydantic import AliasChoices, Field, SecretStr
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

    # Accounts
    allow_registration: bool = True
    session_days: int = Field(default=30, ge=1, le=365)
    # Set to true when served over HTTPS (production) so the session cookie is never sent in clear text.
    cookie_secure: bool = False

    # Usage limits for AI actions that cost money (rolling 24 hours). 0 disables the action.
    quota_visibility_runs_per_user_per_day: int = Field(default=3, ge=0)
    quota_question_generations_per_user_per_day: int = Field(default=10, ge=0)
    quota_fix_generations_per_user_per_day: int = Field(default=20, ge=0)
    # Hard caps across all users: a ceiling on what the server's API key can be used for per day.
    quota_visibility_runs_global_per_day: int = Field(default=20, ge=0)
    quota_question_generations_global_per_day: int = Field(default=100, ge=0)
    quota_fix_generations_global_per_day: int = Field(default=200, ge=0)

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
