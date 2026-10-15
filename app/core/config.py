"""Application settings loaded from environment variables (or a local .env file)."""

from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
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

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        # Fail at startup: otherwise the API boots fine and every metrics request answers 500.
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError):  # OSError: a folder like "America"
            raise ValueError(
                f"Zona horaria desconocida: {value!r}. Usá un nombre IANA como America/Argentina/Buenos_Aires"
            ) from None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
