"""Application settings. All secrets come from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"

    database_url: SecretStr = SecretStr("")
    analytics_database_url: SecretStr = SecretStr("")
    auth_secret: SecretStr = SecretStr("")
    encryption_key: SecretStr = SecretStr("")

    ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    ai_provider_api_key: SecretStr = SecretStr("")
    ai_model: str = "gemini-3.5-flash"
    ai_fallback_model: str = "gemini-3.1-flash-lite"

    # Limits for model-written Python. Lower these on small hosts (a 512 MB free instance needs about 300 and 1).
    python_memory_mb: int = 1024
    python_timeout_s: int = 25
    python_max_concurrent: int = 2

    allowed_origins: str = "http://localhost:3000"
    max_upload_mb: int = 50

    @property
    def database_url_psycopg(self) -> str:
        """Plain libpq URL for psycopg."""
        return self.database_url.get_secret_value()

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy URL using the psycopg (v3) driver."""
        url = self.database_url.get_secret_value()
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_provider_api_key.get_secret_value())

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


class ConfigError(RuntimeError):
    """The deployment is misconfigured. The message names variables, never their values."""


def validate_for_production(s: Settings) -> None:
    """Refuse to start a production engine that would run unsafely."""
    problems: list[str] = []
    if not s.database_url.get_secret_value():
        problems.append("DATABASE_URL is not set")
    if not s.analytics_database_url.get_secret_value():
        problems.append("ANALYTICS_DATABASE_URL is not set (the read-only role used for generated SQL)")
    elif s.analytics_database_url.get_secret_value() == s.database_url.get_secret_value():
        problems.append("ANALYTICS_DATABASE_URL must be a different, read-only role, not the application role")
    if len(s.auth_secret.get_secret_value()) < 32:
        problems.append("AUTH_SECRET must be at least 32 characters")
    origins = s.cors_origins
    if not origins or any(o == "*" or not o.startswith("https://") for o in origins):
        problems.append("ALLOWED_ORIGINS must list explicit https:// origins (no wildcard)")
    if problems:
        raise ConfigError("Invalid production configuration: " + "; ".join(problems) + ".")


@lru_cache
def get_settings() -> Settings:
    return Settings()
