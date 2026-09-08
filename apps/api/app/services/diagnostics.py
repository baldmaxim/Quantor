"""Эксплуатационная диагностика установки.

Отличие от `/health/ready` принципиальное. Готовность отвечает на один вопрос — можно ли
слать трафик, — и обязана быть быстрой, публичной и бедной. Диагностика отвечает на другой:
что именно сломано и что с этим делать. Она закрыта правами, подробнее и допускает
подсказку к починке.

Три правила, которые здесь важнее остального:

- **у каждой пробы свой предел времени, и сверх того есть общий бюджет.** Предел на пробу
  сам по себе страницу не спасает: восемь проб по три секунды, выстроенные в очередь за
  ограничителем, дают двадцать четыре;
- **одна мёртвая необязательная зависимость не вешает страницу.** Отказ пробы — это её
  состояние, а не исключение;
- **состояние «не знаю» показывается как «не знаю».** `unknown` и `not_configured` не
  превращаются ни в «в порядке», ни в ноль: по этой странице принимают решения.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

import httpx

from app import API_VERSION, SCHEMA_VERSION
from app.core import model_registry
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.schema_version import SchemaOutdatedError, check_schema_current, expected_revision
from app.db.session import get_session_factory, ping_database
from app.services import workers as workers_service
from app.storage import get_object_storage

log = get_logger(__name__)

# Ограничитель параллелизма: пробы ходят в разные системы, но соединений у процесса
# конечное число, и запускать все сразу — способ отобрать их у обычных запросов.
DEFAULT_CONCURRENCY = 4

# Общий бюджет на всю страницу. Больше — человек уходит, не дождавшись; меньше —
# не успевают ответить медленные, но живые зависимости.
DEFAULT_BUDGET_SECONDS = 8.0


class ProbeStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


class ProbeSource(StrEnum):
    """Откуда взялось состояние. Показывается рядом с ним — иначе непонятно, насколько свежее."""

    LIVE = "live"
    REPORTED = "reported"
    """Сообщено другим процессом: так узнаётся состояние воркера."""
    CONFIG = "config"
    """Выведено из настроек, без обращения к сети."""
    UNKNOWN = "unknown"
    """Проба не успела в отведённый бюджет."""


@dataclass(frozen=True, slots=True)
class ComponentDiagnostics:
    name: str
    title: str
    status: ProbeStatus
    source: ProbeSource
    checked_at: datetime
    duration_ms: float | None = None
    detail: str | None = None
    remediation: str | None = None
    """Что сделать. Команда или действие — но никогда не учётные данные."""
    facts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Probe:
    name: str
    title: str
    run: Callable[[], Awaitable[ComponentDiagnostics]]
    timeout_seconds: float
    required: bool = True


def _now() -> datetime:
    return datetime.now(UTC)


def _component(
    name: str,
    title: str,
    status: ProbeStatus,
    source: ProbeSource,
    *,
    duration_ms: float | None = None,
    detail: str | None = None,
    remediation: str | None = None,
    facts: dict[str, str] | None = None,
) -> ComponentDiagnostics:
    return ComponentDiagnostics(
        name=name,
        title=title,
        status=status,
        source=source,
        checked_at=_now(),
        duration_ms=duration_ms,
        detail=detail,
        remediation=remediation,
        facts=facts or {},
    )


async def _timed(run: Callable[[], Awaitable[None]]) -> float:
    loop = asyncio.get_running_loop()
    started = loop.time()
    await run()
    return round((loop.time() - started) * 1000, 2)


# --------------------------------------------------------------------- пробы


async def _probe_database() -> ComponentDiagnostics:
    duration = await _timed(ping_database)
    return _component(
        "database", "PostgreSQL", ProbeStatus.HEALTHY, ProbeSource.LIVE, duration_ms=duration
    )


async def _probe_schema() -> ComponentDiagnostics:
    try:
        duration = await _timed(check_schema_current)
    except SchemaOutdatedError as error:
        # Устаревшая схема — это не «база недоступна». База жива, чинится одной командой,
        # и путать эти два состояния значит отправить искать не там.
        return _component(
            "database_schema",
            "Схема базы",
            ProbeStatus.DEGRADED,
            ProbeSource.LIVE,
            detail=str(error),
            remediation="Выполните `pnpm db:migrate`",
            facts={"expected": expected_revision()},
        )
    return _component(
        "database_schema",
        "Схема базы",
        ProbeStatus.HEALTHY,
        ProbeSource.LIVE,
        duration_ms=duration,
        facts={"revision": expected_revision()},
    )


async def _probe_storage(settings: Settings) -> ComponentDiagnostics:
    storage = get_object_storage()
    duration = await _timed(storage.check_available)
    return _component(
        "object_storage",
        "Объектное хранилище",
        ProbeStatus.HEALTHY,
        ProbeSource.LIVE,
        duration_ms=duration,
        # Имя корзины не секрет, а вот ключи доступа сюда не попадают никогда.
        facts={"bucket": settings.s3_bucket},
    )


async def _probe_worker(settings: Settings) -> ComponentDiagnostics:
    """Состояние исполнителя — по его пульсу в базе, а не стуком к нему по сети."""
    if settings.job_executor == "inline":
        return _component(
            "job_worker",
            "Исполнитель заданий",
            ProbeStatus.DEGRADED,
            ProbeSource.CONFIG,
            detail="задания выполняются внутри процесса API",
            remediation="Для многопользовательской работы: JOB_EXECUTOR=worker",
        )

    factory = get_session_factory()
    async with factory() as session:
        health = await workers_service.health(
            session, stale_after_seconds=settings.worker_stale_after_seconds
        )

    if health.alive > 0:
        return _component(
            "job_worker",
            "Исполнитель заданий",
            ProbeStatus.HEALTHY,
            ProbeSource.REPORTED,
            facts={"alive": str(health.alive), "total": str(health.total)},
        )
    if health.is_present:
        return _component(
            "job_worker",
            "Исполнитель заданий",
            ProbeStatus.UNAVAILABLE,
            ProbeSource.REPORTED,
            detail="исполнители зарегистрированы, но молчат — новые задания не начнутся",
            remediation="Проверьте процесс воркера и его журнал",
            facts={"stale": str(health.stale)},
        )
    return _component(
        "job_worker",
        "Исполнитель заданий",
        ProbeStatus.NOT_CONFIGURED,
        ProbeSource.REPORTED,
        detail="исполнитель ни разу не запускался",
        remediation="Запустите `pnpm dev:worker`",
    )


async def _probe_tenderhub(settings: Settings) -> ComponentDiagnostics:
    """Интеграция. Без ключа сеть не трогается вовсе — проверять нечего."""
    if not settings.tenderhub_enabled:
        return _component(
            "tenderhub",
            "TenderHUB",
            ProbeStatus.NOT_CONFIGURED,
            ProbeSource.CONFIG,
            detail="ключ доступа не задан",
            remediation="Добавьте TENDERHUB_API_TOKEN в окружение",
        )
    return _component(
        "tenderhub",
        "TenderHUB",
        ProbeStatus.HEALTHY,
        ProbeSource.CONFIG,
        detail="ключ задан; связь проверяется явно на странице интеграций",
        facts={"base_url": settings.tenderhub_api_url},
    )


async def _probe_oidc(settings: Settings) -> ComponentDiagnostics:
    """Провайдер входа: читается его discovery-документ.

    Секрет клиента сюда не попадает ни в каком виде: наружу уходит только то, что и так
    открыто по адресу discovery.
    """
    if settings.auth_mode == "dev":
        return _component(
            "oidc",
            "Провайдер входа",
            ProbeStatus.DEGRADED,
            ProbeSource.CONFIG,
            detail="портал работает без проверки личности (AUTH_MODE=dev)",
            remediation="Допустимо только локально: вне local запуск не пройдёт",
        )

    issuer = settings.oidc_issuer.strip().rstrip("/")
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        async with httpx.AsyncClient(timeout=settings.oidc_timeout_seconds) as client:
            response = await client.get(f"{issuer}/.well-known/openid-configuration")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        log.warning("oidc_probe_failed", error_type=type(error).__name__)
        return _component(
            "oidc",
            "Провайдер входа",
            ProbeStatus.UNAVAILABLE,
            ProbeSource.LIVE,
            detail=f"discovery не прочитан ({type(error).__name__})",
            remediation="Проверьте доступность OIDC_ISSUER",
            facts={"issuer": issuer},
        )

    return _component(
        "oidc",
        "Провайдер входа",
        ProbeStatus.HEALTHY,
        ProbeSource.LIVE,
        duration_ms=round((loop.time() - started) * 1000, 2),
        facts={
            "issuer": str(payload.get("issuer", issuer)),
            "jwks": "есть" if payload.get("jwks_uri") else "нет",
        },
    )


async def _probe_model_providers(settings: Settings) -> ComponentDiagnostics:
    """Сводка реестра. Ни одного обращения к модели: связь проверяется отдельно и по кнопке."""
    specs = model_registry.parse(settings.model_providers)
    if not specs:
        return _component(
            "model_providers",
            "Поставщики моделей",
            ProbeStatus.NOT_CONFIGURED,
            ProbeSource.CONFIG,
            detail="ни один поставщик не описан",
        )

    usable = [spec for spec in specs if spec.is_usable]
    status = ProbeStatus.HEALTHY if usable else ProbeStatus.DEGRADED
    return _component(
        "model_providers",
        "Поставщики моделей",
        status,
        ProbeSource.CONFIG,
        detail=None if usable else "описаны, но ни один не готов к работе",
        facts={"total": str(len(specs)), "usable": str(len(usable))},
    )


async def _probe_api(settings: Settings) -> ComponentDiagnostics:
    return _component(
        "api",
        "API",
        ProbeStatus.HEALTHY,
        ProbeSource.CONFIG,
        facts={
            "api_version": API_VERSION,
            "schema_version": str(SCHEMA_VERSION),
            "environment": settings.environment,
            "executor": settings.job_executor,
        },
    )


# ------------------------------------------------------------------ выполнение


def build_probes(settings: Settings) -> list[Probe]:
    timeout = settings.readiness_timeout_seconds
    return [
        Probe("api", "API", lambda: _probe_api(settings), timeout, required=True),
        Probe("database", "PostgreSQL", _probe_database, timeout, required=True),
        Probe("database_schema", "Схема базы", _probe_schema, timeout, required=True),
        Probe(
            "object_storage",
            "Объектное хранилище",
            lambda: _probe_storage(settings),
            timeout,
            required=True,
        ),
        Probe(
            "job_worker",
            "Исполнитель заданий",
            lambda: _probe_worker(settings),
            timeout,
            required=False,
        ),
        Probe(
            "tenderhub", "TenderHUB", lambda: _probe_tenderhub(settings), timeout, required=False
        ),
        Probe("oidc", "Провайдер входа", lambda: _probe_oidc(settings), timeout, required=False),
        Probe(
            "model_providers",
            "Поставщики моделей",
            lambda: _probe_model_providers(settings),
            timeout,
            required=False,
        ),
    ]


async def _run_one(probe: Probe) -> ComponentDiagnostics:
    """Выполняет пробу. Наружу не бросает: отказ — это состояние, а не исключение."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        async with asyncio.timeout(probe.timeout_seconds):
            return await probe.run()
    except TimeoutError:
        return _component(
            probe.name,
            probe.title,
            ProbeStatus.UNAVAILABLE,
            ProbeSource.LIVE,
            duration_ms=round((loop.time() - started) * 1000, 2),
            detail="не ответило за отведённое время",
        )
    except Exception as error:
        # Текст исключения наружу не уходит: в нём бывает строка подключения.
        log.warning("diagnostics_probe_failed", probe=probe.name, error_type=type(error).__name__)
        return _component(
            probe.name,
            probe.title,
            ProbeStatus.UNAVAILABLE,
            ProbeSource.LIVE,
            duration_ms=round((loop.time() - started) * 1000, 2),
            detail=f"проба не выполнена ({type(error).__name__})",
        )


async def run_probes(
    probes: list[Probe],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
) -> list[ComponentDiagnostics]:
    """Выполняет пробы с ограниченным параллелизмом и общим пределом времени.

    Предел на пробу без общего бюджета страницу не спасает: восемь проб по три секунды,
    выстроенные за ограничителем, дают двадцать четыре. Не успевшие возвращаются как
    «неизвестно» — честнее, чем заставлять человека ждать.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(probe: Probe) -> ComponentDiagnostics:
        async with semaphore:
            return await _run_one(probe)

    tasks = [asyncio.create_task(guarded(probe)) for probe in probes]
    try:
        async with asyncio.timeout(budget_seconds):
            return list(await asyncio.gather(*tasks))
    except TimeoutError:
        results: list[ComponentDiagnostics] = []
        for probe, task in zip(probes, tasks, strict=True):
            if task.done() and not task.cancelled():
                results.append(task.result())
            else:
                task.cancel()
                results.append(
                    _component(
                        probe.name,
                        probe.title,
                        ProbeStatus.UNKNOWN,
                        ProbeSource.UNKNOWN,
                        detail="проба не уложилась в общий бюджет страницы",
                    )
                )
        await asyncio.gather(*tasks, return_exceptions=True)
        return results


def overall(components: list[ComponentDiagnostics], probes: list[Probe]) -> ProbeStatus:
    """Итог по установке.

    Считается по обязательным компонентам. Отсутствующий воркер или ненастроенная
    интеграция не делают установку сломанной — они делают её неполной, и это видно
    по самим компонентам.
    """
    required = {probe.name for probe in probes if probe.required}
    states = [item.status for item in components if item.name in required]
    if any(state is ProbeStatus.UNAVAILABLE for state in states):
        return ProbeStatus.UNAVAILABLE
    if any(state in (ProbeStatus.DEGRADED, ProbeStatus.UNKNOWN) for state in states):
        return ProbeStatus.DEGRADED
    return ProbeStatus.HEALTHY
