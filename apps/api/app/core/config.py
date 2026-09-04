"""Типизированная конфигурация из переменных окружения.

Умолчания рассчитаны на локальный стек из infra/docker-compose.yml, поэтому портал
запускается без .env. Секреты хранятся в SecretStr, чтобы не утекать в логи и трейсбеки.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/core/config.py -> apps/api/app/core -> app -> api -> apps -> корень репозитория
REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    api_host: str = "0.0.0.0"  # noqa: S104 — dev-стенд открывают с другой машины в локальной сети
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "quantor"
    postgres_user: str = "quantor"
    postgres_password: SecretStr = SecretStr("quantor_dev_password")

    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "quantor_dev"
    s3_secret_access_key: SecretStr = SecretStr("quantor_dev_secret")
    s3_bucket: str = "quantor-dev"
    s3_use_path_style: bool = True

    # Таймаут проверок готовности, чтобы /health/ready не висел на недоступной зависимости.
    readiness_timeout_seconds: float = Field(default=3.0, gt=0)

    @field_validator("api_cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def is_local(self) -> bool:
        return self.environment in ("local", "test")

    @property
    def database_url(self) -> str:
        """DSN для SQLAlchemy async. Пароль подставляется только здесь и не логируется."""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
