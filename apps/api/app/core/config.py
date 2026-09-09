"""Типизированная конфигурация из переменных окружения.

Умолчания рассчитаны на локальный стек из infra/docker-compose.yml, поэтому портал
запускается без .env. Секреты хранятся в SecretStr, чтобы не утекать в логи и трейсбеки.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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

    # Время жизни ссылки на файл ревизии. Просмотрщик открывает документ надолго, поэтому
    # ссылка должна пережить сеанс работы, но не превращаться в постоянную публичную.
    content_url_ttl_seconds: int = Field(default=3600, gt=0, le=24 * 3600)

    # Ограничения приёма файлов. Эталонный архив распознавалки — 47 МБ, документы бывают
    # в разы больше, поэтому предел с запасом и настраивается окружением.
    max_upload_size_bytes: int = Field(default=1024 * 1024 * 1024, gt=0)

    # Предел JSON-тела запроса. Файлы сюда не попадают: они приходят потоком с собственным
    # ограничением. Самый крупный законный JSON — пакет измерений: 200 фигур по 10 000 точек
    # не бывает, но даже сотня тысяч пар координат укладывается в пару мегабайт. Предел
    # нужен не ради этих запросов, а против запроса, который никто не собирался посылать.
    max_json_body_bytes: int = Field(default=4 * 1024 * 1024, gt=0)

    # Пределы для недоверенного архива распознавалки. Эталонный пакет — 4 файла и 52 МБ
    # в распакованном виде, так что запас многократный.
    archive_max_files: int = Field(default=64, gt=0)
    archive_max_total_bytes: int = Field(default=2 * 1024**3, gt=0)
    archive_max_file_bytes: int = Field(default=1024**3, gt=0)
    archive_max_compression_ratio: int = Field(default=200, gt=1)

    # Предел времени на запрос к базе. Без него зависший запрос держит соединение
    # и рабочий поток приложения до бесконечности.
    database_statement_timeout_seconds: float = Field(default=15.0, gt=0)

    # --- TenderHUB ---
    #
    # Ключ читается из окружения и нигде больше не появляется: ни в логе, ни в ответе API,
    # ни в сгенерированном клиенте. Наружу уходит только признак «интеграция настроена».
    #
    # Имя переменной — то, под которым ключ уже лежит в .env; вендорская документация
    # называет её TENDERHUB_API_KEY, поэтому принимаем оба варианта.
    tenderhub_api_url: str = "https://tender.su10.ru"
    tenderhub_api_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TENDERHUB_API_TOKEN", "TENDERHUB_API_KEY"),
    )
    tenderhub_timeout_seconds: float = Field(default=20.0, gt=0)

    # --- поставщики моделей ---
    #
    # JSON-массив описаний. Задаётся развёртыванием: адрес модели и ключ к ней относятся
    # к устройству установки, а не к продуктовым настройкам (промт 07). Ключи здесь не
    # хранятся — только имя переменной окружения, в которой лежит ключ.
    model_providers: str = ""

    # --- исполнение заданий ---
    #
    # `worker` — задания забирает отдельный процесс (`python -m app.worker`).
    # `inline` — прежнее поведение Stage 1: фоновая задача внутри процесса API. Оставлен
    # для запуска без воркера и для тестов, которые выполняют задание явно.
    job_executor: Literal["worker", "inline"] = "worker"

    worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    # Срок владения заданием. Пульс шлётся втрое чаще: одна пропущенная отметка не должна
    # приводить к тому, что задание отберут у живого исполнителя.
    worker_lease_seconds: int = Field(default=60, gt=0)
    worker_concurrency: int = Field(default=1, gt=0)
    worker_retry_base_seconds: int = Field(default=15, gt=0)
    worker_retry_max_seconds: int = Field(default=900, gt=0)
    # Через сколько молчания исполнитель считается мёртвым. Втрое больше аренды.
    worker_stale_after_seconds: int = Field(default=180, gt=0)

    # --- вход в портал ---
    #
    # `dev` — фиксированная личность без провайдера: так работают `pnpm dev` и тесты.
    # `oidc` — настоящий провайдер. Валидатор ниже не даёт запустить `dev` вне локальной
    # среды: тихий откат к режиму без проверки — это ровно тот способ, которым портал
    # открывают наружу, не заметив.
    auth_mode: Literal["dev", "oidc"] = "dev"

    auth_cookie_name: str = "quantor_session"
    auth_csrf_cookie_name: str = "quantor_csrf"
    # Домен cookie задаётся только в бою: `admin.example.ru` и `api.example.ru` должны
    # получить общий cookie, локально же домен указывать нельзя — браузер отвергнет.
    auth_cookie_domain: str = ""
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_session_ttl_seconds: int = Field(default=12 * 3600, gt=0)

    # Кому выдать права администратора платформы при первом входе. Список почт или
    # субъектов через запятую. Зашивать первого администратора в миграцию нельзя:
    # его идентификатор зависит от провайдера, которого на момент миграции ещё нет.
    auth_bootstrap_platform_admins: str = ""

    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    # Ожидаемый получатель токена. Пусто — проверяется совпадение с client_id.
    oidc_audience: str = ""
    oidc_scopes: str = "openid profile email"
    oidc_jwks_ttl_seconds: int = Field(default=3600, gt=0)
    oidc_timeout_seconds: float = Field(default=10.0, gt=0)

    # Куда вернуть браузер после входа. Отдельно от CORS: список источников разрешает
    # запросы, а сюда уходит переадресация, и подставлять её из запроса нельзя.
    portal_base_url: str = "http://localhost:3000"

    # Аварийное переопределение настроек: `documents.content_url_ttl_seconds=900`.
    # Рычаг на случай, когда неудачное значение в базе положило портал и добраться до
    # админки уже нельзя. Поэтому старше базы и только для чтения из интерфейса.
    settings_overrides: str = ""

    # Переопределение флагов возможностей: `takeoff.ai=true,reports=true`.
    # Включение флага не создаёт функциональность — оно лишь перестаёт её прятать.
    feature_flags: str = ""

    @field_validator("api_cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def tenderhub_enabled(self) -> bool:
        """Интеграция включена ровно тогда, когда задан ключ. Отдельного флага нет намеренно:
        включённая возможность без ключа — это обещание, которое портал не выполнит."""
        return bool(self.tenderhub_api_token.get_secret_value().strip())

    @model_validator(mode="after")
    def _check_auth_is_usable(self) -> Settings:
        """Негодная настройка входа роняет запуск, а не первый запрос.

        Оба случая одинаково опасны: dev-режим вне локальной среды открывает портал всем,
        а режим OIDC без адреса провайдера обещает вход, которого не будет.
        """
        if self.auth_mode == "dev" and not self.is_local:
            raise ValueError(
                f"AUTH_MODE=dev недопустим при ENVIRONMENT={self.environment}: "
                "настройте провайдера входа (AUTH_MODE=oidc, OIDC_ISSUER)"
            )
        if self.auth_mode == "oidc" and not (
            self.oidc_issuer.strip() and self.oidc_client_id.strip()
        ):
            raise ValueError("AUTH_MODE=oidc требует OIDC_ISSUER и OIDC_CLIENT_ID")
        return self

    @property
    def is_local(self) -> bool:
        return self.environment in ("local", "test")

    @property
    def worker_heartbeat_interval_seconds(self) -> float:
        """Как часто продлевать аренду. Втрое чаще её срока — с запасом на одну потерю."""
        return max(self.worker_lease_seconds / 3, 1.0)

    @property
    def auth_cookie_secure(self) -> bool:
        """Вне локальной среды cookie уходит только по HTTPS."""
        return not self.is_local

    @property
    def oidc_expected_audience(self) -> str:
        return self.oidc_audience.strip() or self.oidc_client_id.strip()

    @property
    def oidc_scope_list(self) -> list[str]:
        return [scope for scope in self.oidc_scopes.split() if scope]

    @property
    def bootstrap_platform_admins(self) -> frozenset[str]:
        """Опознаватели первых администраторов, приведённые к нижнему регистру."""
        raw = self.auth_bootstrap_platform_admins.split(",")
        return frozenset(item.strip().lower() for item in raw if item.strip())

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
