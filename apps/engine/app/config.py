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


@lru_cache
def get_settings() -> Settings:
    return Settings()
