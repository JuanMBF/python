"""Application settings loaded from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "HelpDesk Pro"
    api_prefix: str = "/api/v1"
    # Used to group daily metrics by the support team's local calendar day.
    timezone: str = "America/Argentina/Buenos_Aires"

    database_url: str = "sqlite:///./helpdesk.db"

    secret_key: str = "dev-only-secret-key-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 8 * 60
    bcrypt_rounds: int = 12


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
