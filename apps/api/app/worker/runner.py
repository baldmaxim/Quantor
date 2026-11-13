"""Цикл исполнителя: взять задание, выполнить, отпустить.

Устройство намеренно простое. Очереди, брокера и оркестратора здесь нет: задание уже
живёт в базе (ADR-0005), а `for update skip locked` даёт ровно то, ради чего заводят
брокера, — двое одновременно пришедших исполнителей не возьмут одно и то же. Redis,
Celery и Temporal добавили бы инфраструктуру, которую надо сопровождать, без выигрыша
на текущих нагрузках.

Три вещи, которые здесь важнее остального:

- **задание берётся и отпускается в короткой транзакции**, а выполняется в другой сессии.
  Иначе строка остаётся заблокированной на всё время импорта, и «выполняется» не видно
  ни в интерфейсе, ни в диагностике;
- **аренда продлевается пульсом из отдельной сессии** и проверяется на каждом ударе:
  задание могли отобрать, решив, что исполнитель умер;
- **брошенные задания подбирает тот же процесс.** Отдельного сторожа нет: он был бы
  ещё одним, что надо запускать и мониторить, а работы там на один запрос раз в полминуты.

Отметка жизни исполнителя (`workers.heartbeat_at`) идёт по своему таймеру, а не только
при захвате задания: иначе простаивающий исполнитель через порог молчания выглядел бы
в готовности мёртвым, а сборщик потом и вовсе удалял бы его запись. Тот же таймер держит
отметку свежей во время долгого задания — пульс аренды пишет в `jobs`, а не в `workers`.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import signal
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app import API_VERSION
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import Job
from app.services import jobs as jobs_service
from app.services import workers as workers_service
from app.storage import get_object_storage
from app.worker import registry
from app.worker.db import dispose_worker_engine, get_worker_session_factory
from app.worker.heartbeat import keep_alive

log = get_logger(__name__)

# Как часто подбирать брошенные задания. Реже пульса и реже опроса очереди: работа
# редкая, а запрос идёт по всей таблице выполняющихся.
REAP_INTERVAL_SECONDS = 30.0


def make_worker_id() -> str:
    """Имя исполнителя: хост, процесс и хвост случайности.

    Читаемое, а не UUID: по нему сразу видно, на какой машине крутится исполнитель,
    и это первое, что спрашивают при разборе.
    """
    host = platform.node()[:32] or "unknown"
    return f"{host}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


@dataclass(slots=True)
class _LeaseFlag:
    """Признак того, что аренду отобрали. Отдельный объект — чтобы пульс мог его выставить."""

    lost: bool = False


class Worker:
    """Один процесс-исполнитель."""

    def __init__(
        self,
        settings: Settings | None = None,
        handlers: Mapping[JobType, registry.JobHandler] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Реестр — параметр: отдельный исполнитель (app.cad_worker) берёт только свои типы,
        # основной — прежний реестр. Захват фильтруется по этим же типам.
        self._handlers: Mapping[JobType, registry.JobHandler] = (
            registry.HANDLERS if handlers is None else handlers
        )
        self.worker_id = make_worker_id()
        self._stopping = asyncio.Event()

    def _supported_types(self) -> list[str]:
        return [job_type.value for job_type in self._handlers]

    def request_stop(self) -> None:
        """Просит остановиться после текущего задания.

        Начатое задание не бросается: прерванный на середине импорт оставляет
        полуразобранный пакет, и разбираться с этим потом дороже, чем подождать секунду.
        """
        self._stopping.set()

    async def _register(self, session: AsyncSession) -> None:
        await workers_service.register(
            session,
            worker_id=self.worker_id,
            host=platform.node()[:255] or "unknown",
            pid=os.getpid(),
            version=API_VERSION,
            job_types=self._supported_types(),
        )

    async def beat(self, session: AsyncSession) -> None:
        """Одна отметка жизни. Запись пропала — исполнитель регистрируется заново.

        Пропасть она может, если исполнитель долго не мог достучаться до базы и сборщик
        другого процесса счёл его мёртвым. Работающий процесс не должен оставаться
        невидимым для готовности до перезапуска.
        """
        if await workers_service.touch(session, worker_id=self.worker_id):
            return
        await self._register(session)
        log.warning("worker_reregistered", worker_id=self.worker_id)

    async def run(self) -> None:
        settings = self._settings
        factory = get_worker_session_factory()

        async with factory() as session:
            await self._register(session)
            await session.commit()

        log.info(
            "worker_started",
            worker_id=self.worker_id,
            job_types=self._supported_types(),
            executor="worker",
        )

        reaper = asyncio.create_task(self._reap_forever())
        pulse = asyncio.create_task(self._beat_forever())
        try:
            while not self._stopping.is_set():
                claimed = await self._claim_and_run()
                if not claimed:
                    # Пустая очередь — обычное состояние, а не повод суетиться.
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(settings.worker_poll_interval_seconds):
                            await self._stopping.wait()
        finally:
            # Отметка гасится до снятия с учёта: иначе удар после `unregister` вернул бы
            # остановленного исполнителя в список живых.
            reaper.cancel()
            pulse.cancel()
            await asyncio.gather(reaper, pulse, return_exceptions=True)
            async with factory() as session:
                await workers_service.unregister(session, worker_id=self.worker_id)
                await session.commit()
            await dispose_worker_engine()
            log.info("worker_stopped", worker_id=self.worker_id)

    async def _claim_and_run(self) -> bool:
        """Берёт одно задание и выполняет его. False — брать было нечего."""
        settings = self._settings
        factory = get_worker_session_factory()

        # Короткая транзакция: захват фиксируется сразу, иначе строка остаётся
        # заблокированной на всё время работы и «выполняется» никому не видно.
        async with factory() as session:
            job = await jobs_service.claim(
                session,
                worker_id=self.worker_id,
                job_types=self._supported_types(),
                lease_seconds=settings.worker_lease_seconds,
            )
            if job is None:
                return False
            job_id, job_type, attempt = job.id, job.job_type, job.attempt
            await workers_service.heartbeat(
                session, worker_id=self.worker_id, current_job_id=job_id
            )
            await session.commit()

        log.info("job_claimed", job_id=str(job_id), job_type=job_type.value, attempt=attempt)
        await self._execute(job_id)

        async with factory() as session:
            await workers_service.heartbeat(session, worker_id=self.worker_id, current_job_id=None)
            await session.commit()
        return True

    async def _execute(self, job_id: uuid.UUID) -> None:
        settings = self._settings
        factory = get_worker_session_factory()
        flag = _LeaseFlag()

        async with (
            keep_alive(
                job_id=job_id,
                worker_id=self.worker_id,
                lease_seconds=settings.worker_lease_seconds,
                interval_seconds=settings.worker_heartbeat_interval_seconds,
                on_lost=lambda: setattr(flag, "lost", True),
            ),
            factory() as session,
        ):
            job = await session.get(Job, job_id)
            if job is None:  # pragma: no cover — задание не может исчезнуть
                log.error("job_missing", job_id=str(job_id))
                return

            handler = self._handlers.get(job.job_type)
            if handler is None:
                # Тип задания есть в базе, а исполнителя для него нет. Это не отказ
                # работы, а рассогласование установки, и висеть «выполняется» оно
                # не должно.
                await jobs_service.fail(
                    session,
                    job=job,
                    error_code=ErrorCode.IMPORT_FAILED.value,
                    error_message=f"нет исполнителя для типа {job.job_type.value}",
                )
                await session.commit()
                return

            try:
                await handler(session, job, get_object_storage(), settings)
                await session.commit()
            except Exception as error:
                # Любой отказ гасится здесь и только здесь. Исключение, выпущенное
                # наружу, остановило бы цикл исполнителя — то есть одно неудачное
                # задание унесло бы с собой все остальные.
                log.exception("job_crashed", job_id=str(job_id))
                await session.rollback()
                await self._mark_failed(job_id, type(error).__name__)

        if flag.lost:
            # Аренду отобрали, пока мы работали. Результат уже записан, но задание
            # могло достаться другому исполнителю: пишем об этом честно.
            log.warning("job_finished_without_lease", job_id=str(job_id))

    async def _mark_failed(self, job_id: uuid.UUID, reason: str) -> None:
        """Записывает отказ отдельной сессией: прежняя после отката недействительна."""
        factory = get_worker_session_factory()
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status is not JobStatus.RUNNING:
                return
            await jobs_service.fail(
                session,
                job=job,
                error_code=ErrorCode.IMPORT_FAILED.value,
                error_message=reason,
            )
            await session.commit()

    async def _beat_forever(self) -> None:
        """Отмечает исполнителя живым не реже порога молчания — и в простое, и в работе.

        Раз в интервал пульса аренды (треть её срока): порог молчания — три аренды, так что
        до тревоги в готовности должно пропасть девять отметок подряд. Нагрузка — одно
        обновление по ключу раз в двадцать секунд на процесс, на фоне опроса очереди
        раз в секунду её не видно.
        """
        settings = self._settings
        factory = get_worker_session_factory()
        while True:
            await asyncio.sleep(settings.worker_heartbeat_interval_seconds)
            try:
                async with factory() as session:
                    await self.beat(session)
                    await session.commit()
            except Exception as error:
                # Как и сборщик: недоступная на минуту база — не повод останавливать работу.
                log.warning("worker_heartbeat_failed", error_type=type(error).__name__)

    async def _reap_forever(self) -> None:
        """Подбирает задания, чей исполнитель замолчал."""
        settings = self._settings
        factory = get_worker_session_factory()
        while True:
            await asyncio.sleep(REAP_INTERVAL_SECONDS)
            try:
                async with factory() as session:
                    released = await jobs_service.release_expired(
                        session,
                        base_seconds=settings.worker_retry_base_seconds,
                        max_seconds=settings.worker_retry_max_seconds,
                    )
                    pruned = await workers_service.prune_stale(
                        session, older_than_seconds=settings.worker_stale_after_seconds * 10
                    )
                    await session.commit()
                if released or pruned:
                    log.info("jobs_reaped", released=released, workers_pruned=pruned)
            except Exception as error:
                # Сборщик не должен ронять исполнителя: недоступная на минуту база —
                # причина подождать, а не остановить работу целиком.
                log.warning("reaper_failed", error_type=type(error).__name__)


async def run_worker(
    settings: Settings | None = None,
    handlers: Mapping[JobType, registry.JobHandler] | None = None,
) -> None:
    """Точка входа: запускает исполнителя и корректно останавливает по сигналу."""
    resolved = settings or get_settings()
    configure_logging(level=resolved.log_level, json_output=not resolved.is_local)

    worker = Worker(resolved, handlers)
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        with contextlib.suppress(NotImplementedError):
            # Windows не поддерживает обработчики сигналов в цикле событий; там
            # остановка приходит обычным KeyboardInterrupt.
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run()
    except KeyboardInterrupt:  # pragma: no cover — ручная остановка
        worker.request_stop()
