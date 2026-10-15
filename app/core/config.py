from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-secret-change-me-in-production-0000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Knowledge Base API"
    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://kb:kb@localhost:5432/kb"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret_key: SecretStr = SecretStr(_DEV_SECRET)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 14

    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_default: int = 100  # per user, per window
    rate_limit_auth: int = 5  # per IP, per window, on login/register

    cors_origins: list[str] = []

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        secret = self.jwt_secret_key.get_secret_value()
        if self.environment == "production" and (secret == _DEV_SECRET or len(secret) < 32):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a random value of 32+ chars in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
