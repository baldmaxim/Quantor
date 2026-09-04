"""Точка входа FastAPI.

Приложение обязано импортироваться без живой БД и хранилища: на этом держатся офлайн-экспорт
OpenAPI и тесты оболочки в CI. Подключения создаются лениво, при первом обращении.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app import API_VERSION
from app.api import health
from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.db.session import dispose_engine

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

    app.include_router(health.router)
    app.include_router(api_v1_router)
    return app


app = create_app()
