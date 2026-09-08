"""Соответствие типа задания и того, кто его выполняет.

Отдельный реестр, а не цепочка `if job_type == ...` в цикле: тип заданий станет больше
на Stage 2, и разрастаться должен словарь, а не ветвление посреди исполнения.

Тела заданий сюда не переезжают. `execute_legacy_import` остаётся там же, где был, —
он принимает сессию, хранилище и настройки аргументами, и это ровно то, что нужно
и воркеру, и тесту, выполняющему импорт явно.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import JobType
from app.models import Job
from app.services.job_runner import execute_legacy_import
from app.storage.base import ObjectStorage

JobHandler = Callable[[AsyncSession, Job, ObjectStorage, Settings], Awaitable[Job]]


async def _legacy_import(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    return await execute_legacy_import(session, job, storage=storage, settings=settings)


HANDLERS: dict[JobType, JobHandler] = {
    JobType.LEGACY_IMPORT: _legacy_import,
}


def supported_types() -> list[str]:
    """Типы, которые этот процесс берётся исполнять."""
    return [job_type.value for job_type in HANDLERS]


def handler_for(job_type: JobType) -> JobHandler | None:
    return HANDLERS.get(job_type)
