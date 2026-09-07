"""Liveness и readiness.

- /health/live — процесс жив, внешних зависимостей не трогает (для рестарт-политик).
- /health/ready — БД, схема и объектное хранилище в порядке (для балансировщика и диагностики).

Наружу отдаются только безопасные коды состояния: ни DSN, ни креды, ни трейсбеки.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.schema_version import SchemaOutdatedError, check_schema_current, expected_revision
from app.db.session import ping_database
from app.storage import get_object_storage

router = APIRouter(tags=["health"])
log = get_logger(__name__)

ComponentState = Literal["ok", "unavailable", "outdated"]


class ComponentHealth(BaseModel):
    name: str
    status: ComponentState
    duration_ms: float = Field(ge=0)
    detail: str | None = None
    """Безопасное пояснение: что именно не так и чем это чинится. Без DSN и трейсбеков."""


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    components: list[ComponentHealth]
    schema_revision: str
    """Ревизия миграций, которую ожидает код. Помогает сверить стенды между собой."""


async def _probe(
    name: str,
    check: Callable[[], Awaitable[None]],
    limit_seconds: float,
    *,
    outdated_hint: str | None = None,
) -> ComponentHealth:
    loop = asyncio.get_running_loop()
    started = loop.time()
    state: ComponentState = "ok"
    detail: str | None = None

    try:
        async with asyncio.timeout(limit_seconds):
            await check()
    except SchemaOutdatedError as exc:
        # Единственный случай, когда наружу уходит текст ошибки: он описывает наше же
        # состояние (номера ревизий) и не содержит ничего чужого.
        state = "outdated"
        detail = f"{exc}. {outdated_hint}" if outdated_hint else str(exc)
        log.error("schema_outdated", component=name, detail=str(exc))
    except Exception as exc:
        state = "unavailable"
        # Причина нужна в логах, но не в HTTP-ответе.
        log.warning("healthcheck_failed", component=name, error_type=type(exc).__name__)

    return ComponentHealth(
        name=name,
        status=state,
        duration_ms=round((loop.time() - started) * 1000, 2),
        detail=detail,
    )


@router.get("/health/live", response_model=LivenessResponse, summary="Liveness probe")
async def liveness() -> LivenessResponse:
    return LivenessResponse(status="ok")


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(response: Response) -> ReadinessResponse:
    settings = get_settings()
    timeout = settings.readiness_timeout_seconds
    storage = get_object_storage()

    components = await asyncio.gather(
        _probe("database", ping_database, timeout),
        # Схема проверяется отдельно от доступности: живая база с устаревшей схемой —
        # это другая поломка и другая команда для починки.
        _probe(
            "database_schema",
            check_schema_current,
            timeout,
            outdated_hint="Выполните `pnpm db:migrate`",
        ),
        _probe("object_storage", storage.check_available, timeout),
    )

    healthy = all(component.status == "ok" for component in components)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if healthy else "degraded",
        components=list(components),
        schema_revision=expected_revision(),
    )
