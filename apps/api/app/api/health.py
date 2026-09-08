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

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.schema_version import SchemaOutdatedError, check_schema_current, expected_revision
from app.db.session import get_session_factory, ping_database
from app.services import workers as workers_service
from app.storage import get_object_storage

router = APIRouter(tags=["health"])
log = get_logger(__name__)

ComponentState = Literal["ok", "degraded", "unavailable", "outdated"]


class ComponentHealth(BaseModel):
    name: str
    status: ComponentState
    duration_ms: float = Field(ge=0)
    detail: str | None = None
    """Безопасное пояснение: что именно не так и чем это чинится. Без DSN и трейсбеков."""
    required: bool = True
    """False — отказ этого компонента не делает API неготовым. См. пояснение у readiness."""


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
    """Готовность API отвечать на запросы.

    Ключевое различие — между обязательными компонентами и необязательными. Без базы,
    схемы и хранилища API не может ответить почти ни на что: это 503, и балансировщик
    обязан увести с него трафик.

    Исполнитель заданий — другое дело. Когда он лежит, портал по-прежнему показывает
    проекты, документы и чертежи; не работает только запуск новых импортов. Отдавать
    503 в этом случае значит увести трафик с полностью исправного API и превратить
    частичную поломку в полную (ADR-0015).
    """
    settings = get_settings()
    timeout = settings.readiness_timeout_seconds
    storage = get_object_storage()

    components = list(
        await asyncio.gather(
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
    )
    components.append(await _probe_worker(settings))

    required_failed = any(
        component.required and component.status != "ok" for component in components
    )
    if required_failed:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    all_ok = all(component.status == "ok" for component in components)
    return ReadinessResponse(
        status="ok" if all_ok else "degraded",
        components=components,
        schema_revision=expected_revision(),
    )


async def load_worker_health(settings: Settings) -> workers_service.WorkerHealth:
    """Читает пульс исполнителей.

    Отдельная функция модуля, а не тело пробы: проверки готовности подменяют
    зависимости именно так, и проба воркера не должна быть исключением.
    """
    factory = get_session_factory()
    async with factory() as session:
        return await workers_service.health(
            session, stale_after_seconds=settings.worker_stale_after_seconds
        )


async def _probe_worker(settings: Settings) -> ComponentHealth:
    """Состояние исполнителя заданий по его пульсу.

    В базу, а не в сам процесс: воркер живёт на другой машине, и стучаться к нему по
    сети означало бы поставить готовность API в зависимость ещё от одного соединения.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    state: ComponentState = "ok"
    detail: str | None = None

    if settings.job_executor == "inline":
        detail = "задания выполняются внутри процесса API (JOB_EXECUTOR=inline)"
        return ComponentHealth(
            name="job_worker",
            status="ok",
            duration_ms=round((loop.time() - started) * 1000, 2),
            detail=detail,
            required=False,
        )

    try:
        async with asyncio.timeout(settings.readiness_timeout_seconds):
            health = await load_worker_health(settings)
        if health.alive > 0:
            detail = f"исполнителей на связи: {health.alive}"
        elif health.is_present:
            state = "unavailable"
            detail = "исполнители зарегистрированы, но молчат — новые задания не начнутся"
        else:
            # Не «сломано», а «не запускали». На свежей установке это обычное состояние,
            # и пугать красным здесь не за что.
            state = "degraded"
            detail = "исполнитель ни разу не запускался: `pnpm dev:worker`"
    except Exception as exc:
        state = "unavailable"
        log.warning("worker_probe_failed", error_type=type(exc).__name__)

    return ComponentHealth(
        name="job_worker",
        status=state,
        duration_ms=round((loop.time() - started) * 1000, 2),
        detail=detail,
        required=False,
    )
