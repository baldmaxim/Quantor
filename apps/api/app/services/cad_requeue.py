"""Перепостановка задания, поставленного до смены пина генератора.

Задание `cad_walls` или `cad_zones` несёт версию генератора и sha256 параметров на момент
постановки. Между постановкой и запуском пин мог смениться (выкладка): раньше такое задание
отказывало `CAD_PARAMS_INVALID`. Теперь исполнитель ставит то же задание с действующими
параметрами, а исходное закрывает как заменённое. Перепостановка одна: задание, которое само
поставлено заменой, при новом расхождении отказывает, как раньше, - цикла нет.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.errors import ErrorCode
from app.models import Job
from app.services import cad_progress
from app.services import jobs as jobs_service

log = get_logger(__name__)

# Ключ в задании-замене: идентификатор исходного задания.
REQUEUED_FROM: Final = "requeued_from"
# Ключ в исходном задании: идентификатор задания-замены.
SUPERSEDED_BY: Final = "superseded_by"
RESULT_SUPERSEDED: Final = "superseded"
_MESSAGE: Final = "Задание заменено новым: сменилась версия генератора или его параметры"


def can_requeue(job: Job) -> bool:
    """Не более одной перепостановки на задание."""
    return job.payload.get(REQUEUED_FROM) is None


async def supersede(session: AsyncSession, job: Job, replacement: Job, attempt: int) -> Job:
    """Исходное задание закрывается как заменённое; строка задания уже под блокировкой."""
    code = ErrorCode.CAD_JOB_SUPERSEDED.value
    payload = cad_progress.finish_attempt(
        job.payload,
        attempt,
        cad_progress.now(),
        outcome=RESULT_SUPERSEDED,
        error_code=code,
        result_status=RESULT_SUPERSEDED,
    )
    job.payload = {
        **payload,
        SUPERSEDED_BY: str(replacement.id),
        "cad_result": {
            "result_status": RESULT_SUPERSEDED,
            "error_code": code,
            "attempt": attempt,
            SUPERSEDED_BY: str(replacement.id),
        },
    }
    job = await jobs_service.cancel(session, job=job)
    job.error_code = code
    job.error_message = _MESSAGE
    await session.flush()
    log.info("cad_job_superseded", job_id=str(job.id), replacement_id=str(replacement.id))
    return job
