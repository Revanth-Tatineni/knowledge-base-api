"""Every environment variable the app reads, loaded and validated once into `settings`."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-secret-change-me-in-production-0000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    PROJECT_NAME: str = "Knowledge Base API"
    ENVIRONMENT: Literal["local", "test", "production"] = "local"
    LOG_LEVEL: str = "INFO"
    HOST: str = "127.0.0.1"
    PORT: int = Field(8000, ge=1, le=65535)

    DATABASE_URL: str = "postgresql+asyncpg://kb:kb@localhost:5432/kb"
    DB_POOL_SIZE: int = Field(5, ge=1)
    DB_MAX_OVERFLOW: int = Field(10, ge=0)

    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET_KEY: SecretStr = SecretStr(_DEV_SECRET)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(15, ge=1)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(14, ge=1)

    RATE_LIMIT_ENABLED: bool = True
    CORS_ORIGINS: list[str] = []

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        secret = self.JWT_SECRET_KEY.get_secret_value()
        if self.is_production and (secret == _DEV_SECRET or len(secret) < 32):
            raise ValueError(
                "JWT_SECRET_KEY must be set to a random value of 32+ chars in production"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
