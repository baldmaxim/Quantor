"""Постановка заданий на исполнение.

Исполнителя теперь два, и выбирает между ними `JOB_EXECUTOR`:

- **`worker`** (по умолчанию) — задание забирает отдельный процесс `python -m app.worker`.
  Планировщик здесь только логирует: строка уже в очереди, и брать её — не его дело.
  Тяжёлый импорт больше не занимает рабочий поток API (ADR-0015);
- **`inline`** — прежнее поведение Stage 1: фоновая задача внутри процесса API. Оставлен
  для запуска без воркера и потому, что тесты выполняют задание явно, а не гоняются
  за асинхронной задачей.

Тело задания — `execute_legacy_import` — не знает ни о том, ни о другом. Оно принимает
сессию, хранилище и настройки аргументами, и ровно это позволило вынести исполнение,
не тронув ни строчки в самой работе.

Что не изменилось и не должно:

- состояние задания живёт в базе, а не в памяти процесса, и переживает перезапуск;
- у работы своя сессия: сессия HTTP-запроса закрывается раньше, чем она заканчивается;
- любая ошибка превращается в безопасный код, а не в потерянное «выполняется» навсегда.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.domain import JobStatus, ProcessingStatus
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, Job, Project
from app.services import documents as documents_service
from app.services import jobs as jobs_service
from app.services.legacy import importer
from app.storage import get_object_storage
from app.storage.base import ObjectStorage

log = get_logger(__name__)

# Ссылки на запущенные задачи: без них сборщик мусора вправе убить задачу на середине.
_running: Final[set[asyncio.Task[None]]] = set()


# Планировщик передаётся зависимостью, чтобы тесты не поднимали фоновые задачи,
# а выполняли импорт явно и проверяли результат.
JobScheduler = Callable[[uuid.UUID], None]


def get_job_scheduler() -> JobScheduler:
    """Планировщик по настройке окружения.

    Зависимость сохранена намеренно: тесты подменяют именно её, и вынос исполнения
    не должен был этого коснуться.
    """
    if get_settings().job_executor == "inline":
        return schedule_legacy_import
    return _leave_to_worker


def _leave_to_worker(job_id: uuid.UUID) -> None:
    """Ничего не делает — и это правильно.

    Задание уже в очереди со статусом `queued`; отдельный процесс заберёт его сам.
    Опрос идёт раз в секунду, что на фоне полутора секунд импорта незаметно.
    """
    log.info("job_enqueued", job_id=str(job_id), executor="worker")


def schedule_legacy_import(job_id: uuid.UUID) -> None:
    """Ставит импорт на исполнение и сразу возвращает управление."""
    task = asyncio.create_task(_run_legacy_import(job_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def wait_for_pending(limit_seconds: float = 30.0) -> None:
    """Ждёт завершения запущенных задач. Нужно тестам и корректной остановке приложения."""
    if not _running:
        return
    await asyncio.wait(set(_running), timeout=limit_seconds)


async def _run_legacy_import(job_id: uuid.UUID) -> None:
    """Выполняет импорт пакета в отдельной сессии."""
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            log.error("job_missing", job_id=str(job_id))
            return
        if job.status is not JobStatus.QUEUED:
            # Повторный запуск того же задания — не ошибка: задача могла быть поставлена дважды.
            log.info("job_not_queued", job_id=str(job_id), status=job.status.value)
            return

        await execute_legacy_import(
            session, job, storage=get_object_storage(), settings=get_settings()
        )
        await session.commit()


async def execute_legacy_import(
    session: AsyncSession, job: Job, *, storage: ObjectStorage, settings: Settings
) -> Job:
    """Тело задания.

    Хранилище и настройки приходят аргументами, а не берутся из модуля: так тест выполняет
    импорт синхронно, с хранилищем в памяти и без борьбы с фоновой задачей.
    """
    revision_id = job.payload.get("revision_id")
    project_id = job.project_id
    if not isinstance(revision_id, str) or project_id is None:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=ErrorCode.IMPORT_FAILED.value,
            error_message="в задании нет ссылки на ревизию пакета",
        )

    revision = await session.get(DocumentRevision, uuid.UUID(revision_id))
    project = await session.get(Project, project_id)
    if revision is None or project is None:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=ErrorCode.IMPORT_FAILED.value,
            error_message="пакет или проект не найден",
        )

    await jobs_service.start(session, job=job, stage="unpack")
    await documents_service.set_processing_status(
        session, revision=revision, status=ProcessingStatus.IMPORTING
    )
    await session.flush()

    job_id = job.id
    revision_uuid = revision.id
    try:
        result = await importer.import_package(
            session,
            storage,
            package_revision=revision,
            project=project,
            settings=settings,
        )
    except DomainError as error:
        code, detail = error.code, error.detail
        await session.rollback()
        return await _mark_failed(session, job_id, revision_uuid, code, detail)
    except Exception as error:
        log.exception("legacy_import_crashed", job_id=str(job_id))
        await session.rollback()
        return await _mark_failed(
            session,
            job_id,
            revision_uuid,
            ErrorCode.IMPORT_FAILED,
            type(error).__name__,
        )

    log.info(
        "legacy_import_finished",
        job_id=str(job.id),
        sheets=result.sheet_count,
        regions=result.region_count,
        already_imported=result.already_imported,
    )
    return await jobs_service.succeed(
        session,
        job=job,
        payload={
            "document_id": str(result.document_id),
            "imported_revision_id": str(result.revision_id),
            "sheet_count": result.sheet_count,
            "region_count": result.region_count,
            "artifact_count": result.artifact_count,
        },
    )


async def _mark_failed(
    session: AsyncSession,
    job_id: uuid.UUID,
    revision_id: uuid.UUID,
    code: ErrorCode,
    message: str,
) -> Job:
    """Записывает отказ после отката транзакции.

    Объекты сессии после rollback недействительны, поэтому задание и ревизия читаются
    заново — иначе состояние отказа просто не сохранится.
    """
    job = await session.get(Job, job_id)
    if job is None:  # pragma: no cover — задание не может исчезнуть
        raise RuntimeError(f"задание {job_id} исчезло во время импорта")

    revision = await session.get(DocumentRevision, revision_id)
    if revision is not None:
        await documents_service.set_processing_status(
            session, revision=revision, status=ProcessingStatus.FAILED, error_code=code.value
        )

    log.warning("legacy_import_failed", job_id=str(job_id), code=code.value)
    return await jobs_service.fail(session, job=job, error_code=code.value, error_message=message)
