"""Точка входа FastAPI.

Приложение обязано импортироваться без живой БД и хранилища: на этом держатся офлайн-экспорт
OpenAPI и тесты оболочки в CI. Подключения создаются лениво, при первом обращении.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import DBAPIError, OperationalError

from app import API_VERSION
from app.api import health
from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_engine
from app.errors import MESSAGES, DomainError, ErrorCode
from app.storage.base import StorageUnavailableError

DESCRIPTION = (
    "API портала автоматизированного подсчёта строительных объёмов. "
    "Stage 1: проекты, импорт распознанных пакетов и просмотрщик документации. "
    "Расчёта объёмов и вызовов моделей на этом этапе нет."
)


def operation_id(route: APIRoute) -> str:
    """Читаемые имена операций.

    Умолчание FastAPI склеивает путь и метод (`read_meta_api_v1_meta_get`), из-за чего
    сгенерированный TypeScript-клиент получает нечитаемые функции. Имя обработчика уникально
    в пределах приложения и даёт `readMeta`, `liveness`, `readiness`.
    """
    return route.name


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log = get_logger(__name__)
    log.info("api_startup", environment=settings.environment, api_version=API_VERSION)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("api_shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=not settings.is_local)

    app = FastAPI(
        title="Quantor API",
        description=DESCRIPTION,
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    _register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(api_v1_router)
    return app


def _error_body(code: ErrorCode, message: str | None = None) -> dict[str, dict[str, str]]:
    return {"detail": {"code": code.value, "message": message or MESSAGES[code]}}


def _register_error_handlers(app: FastAPI) -> None:
    """Наружу уходит стабильный код ошибки, подробности остаются в логах.

    Без этих обработчиков нарушенный инвариант задания и упавшая база превращаются
    в безликий 500, по которому невозможно ни объяснить пользователю причину,
    ни отличить поломку инфраструктуры от ошибки в данных.
    """
    log = get_logger(__name__)

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, error: DomainError) -> JSONResponse:
        log.warning("domain_error", code=error.code.value)
        return JSONResponse(
            status_code=error.status_code,
            content=_error_body(error.code, error.detail),
        )

    # ConnectionError нужен отдельно: отказ в соединении с базой приходит как обычная
    # ошибка сокета и SQLAlchemy её не оборачивает.
    @app.exception_handler(ConnectionError)
    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def _database_error(_: Request, error: Exception) -> JSONResponse:
        log.error("database_unavailable", error_type=type(error).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body(ErrorCode.DATABASE_UNAVAILABLE),
        )

    @app.exception_handler(StorageUnavailableError)
    async def _storage_error(_: Request, error: StorageUnavailableError) -> JSONResponse:
        log.error("storage_unavailable", error_type=type(error).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_error_body(ErrorCode.STORAGE_UNAVAILABLE),
        )


app = create_app()
