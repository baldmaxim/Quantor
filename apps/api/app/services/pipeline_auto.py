"""Автопайплайн пилотных проектов: загрузка -> паспорта -> ответы на вопросы и CAD листов-планов.

Хуки вызываются из исполнителей в транзакции записи успеха родительского задания, как
`cad_walls.enqueue_after_convert`. Постановка идёт сервисом от системы (без пользователя), любая
ошибка постановки родителя не роняет. Масштаб листа определяет только движок (`auto_scale`,
ADR-0045): сервис масштаб не читает и не вычисляет. Дубли отсекают сами функции постановки
(активное задание проекта, ключ идемпотентности) и проверка существующих преобразований листа.
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.pipeline_auto import PipelineAutoPilot
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import DomainError
from app.models import DocumentRevision, Job, Project, SheetPassport
from app.services import cad as cad_service
from app.services import doc_questions
from app.services.consistency.dictionaries import SheetKind

log = get_logger(__name__)


def pilot(settings: Settings) -> PipelineAutoPilot | None:
    """Пилот из настройки; пусто - выключено, невалидный JSON - выключено и ошибка в журнале."""
    if not settings.pipeline_auto.strip():
        return None
    try:
        return PipelineAutoPilot.model_validate_json(settings.pipeline_auto)
    except ValidationError:
        log.error("pipeline_auto_pilot_invalid")
        return None


def enabled_for(project_id: uuid.UUID | None, settings: Settings) -> bool:
    if project_id is None:
        return False
    current = pilot(settings)
    return current is not None and project_id in current.project_ids


async def _project_of(session: AsyncSession, job: Job, settings: Settings) -> Project | None:
    if not enabled_for(job.project_id, settings) or job.project_id is None:
        return None
    return await session.get(Project, job.project_id)


async def after_revision_ready(session: AsyncSession, job: Job, settings: Settings) -> None:
    """Успех геометрии PDF или импорта пакета: ставит разбор паспортов листов проекта."""
    from app.services import sheet_passports  # позже верхнего уровня: цикл с sheet_passports

    project = await _project_of(session, job, settings)
    if project is None:
        return
    # Разбор паспортов один на пачку загрузок: ставит его последнее завершившееся задание загрузки.
    pending = await session.scalar(
        select(Job.id)
        .where(
            Job.project_id == job.project_id,
            Job.id != job.id,
            Job.job_type.in_((JobType.LEGACY_IMPORT, JobType.PDF_GEOMETRY_EXTRACT)),
            Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
        .limit(1)
    )
    if pending is not None:
        return
    try:
        async with session.begin_nested():
            await sheet_passports.schedule_extract(session, project=project)
    except (DomainError, SQLAlchemyError):
        log.warning("pipeline_auto_passports_failed", job_id=str(job.id))


async def after_passports(session: AsyncSession, job: Job, settings: Settings) -> None:
    """Успех паспортов: поиск ответов на вопросы и CAD листов-планов (в пределах лимита)."""
    project = await _project_of(session, job, settings)
    current = pilot(settings)
    if project is None or current is None:
        return
    try:
        async with session.begin_nested():
            await doc_questions.schedule_search(session, project=project)
    except (DomainError, SQLAlchemyError):
        log.warning("pipeline_auto_search_failed", job_id=str(job.id))
    try:
        await _schedule_cad(session, job, project, settings, current.max_cad_sheets_per_project)
    except (DomainError, SQLAlchemyError):
        log.warning("pipeline_auto_cad_failed", job_id=str(job.id))


def _pages_of(payload: dict[str, object]) -> list[int]:
    params = payload.get("params")
    pages = params.get("pages") if isinstance(params, dict) else None
    return [page for page in pages if type(page) is int] if isinstance(pages, list) else []


async def _schedule_cad(
    session: AsyncSession, job: Job, project: Project, settings: Settings, limit: int
) -> None:
    payloads = list(
        await session.scalars(
            select(Job.payload).where(
                Job.job_type == JobType.CAD_PDF_CONVERT, Job.project_id == project.id
            )
        )
    )
    budget = limit - len(payloads)
    if budget <= 0:
        return
    done = {
        (str(payload.get("revision_id")), page)
        for payload in payloads
        for page in _pages_of(payload)
    }
    from app.services import sheet_passports  # позже верхнего уровня: цикл с sheet_passports

    revisions = await sheet_passports.latest_pdf_revisions(session, project_id=project.id)
    for revision in revisions:
        if budget <= 0:
            return
        pages = await _plan_pages(session, revision)
        for page in pages:
            if budget <= 0:
                return
            if (str(revision.id), page) in done:
                continue
            try:
                async with session.begin_nested():
                    await cad_service.schedule_convert(
                        session,
                        project=project,
                        revision=revision,
                        pages=[page],
                        settings=settings,
                        auto_scale=True,
                    )
            except (DomainError, SQLAlchemyError):
                log.warning("pipeline_auto_convert_failed", job_id=str(job.id), page_index=page)
                continue
            budget -= 1


async def _plan_pages(session: AsyncSession, revision: DocumentRevision) -> list[int]:
    """Страницы с паспортом `floor_plan` (не отклонённым), по номеру."""
    rows = await session.scalars(
        select(SheetPassport.page_index)
        .where(
            SheetPassport.revision_id == revision.id,
            SheetPassport.sheet_kind == SheetKind.FLOOR_PLAN.value,
            SheetPassport.status != "rejected",
        )
        .order_by(SheetPassport.page_index)
    )
    return [int(page) for page in rows]
