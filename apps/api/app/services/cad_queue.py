"""Очередь CAD проекта: задания проекта, место в очереди исполнителя и общие счётчики.

Исполнитель CAD берёт задания по одному в порядке `(available_at, created_at)` (`CLAIM_SQL`),
поэтому «впереди» задания - всё, что сейчас выполняется, и всё, что стоит в очереди раньше.
Чужие пространства видны только числами: в `ahead` и общих счётчиках, но не в списке.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.contracts.cad_queue import CadQueueItemRead, CadQueueRead
from app.domain import JobStatus, JobType
from app.models import Document, DocumentRevision, Job

# Типы, которые берёт исполнитель CAD (ключи `app.cad_worker.HANDLERS`).
QUEUE_JOB_TYPES: Final = (
    JobType.CAD_PDF_CONVERT,
    JobType.CAD_MEP_ROUTE,
    JobType.CAD_WALLS,
    JobType.CAD_FLOOR3D_DXF,
    JobType.CAD_ZONES,
    JobType.CAD_SECTIONS,
    JobType.CAD_EOM_ROUTE,
)
RECENT_FINISHED_WINDOW: Final = timedelta(hours=1)
RECENT_FINISHED_LIMIT: Final = 10
_TERMINAL: Final = (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


def _ints(raw: object) -> list[int]:
    return [item for item in raw if type(item) is int] if isinstance(raw, list) else []


def pages_of(job: Job) -> list[int]:
    """Страницы задания (с 0): у конвертации - `params.pages`, у разрезов - `page_indexes`."""
    if job.job_type is JobType.CAD_PDF_CONVERT:
        params = job.payload.get("params")
        return _ints(params.get("pages")) if isinstance(params, dict) else []
    if job.job_type is JobType.CAD_SECTIONS:
        return _ints(job.payload.get("page_indexes"))
    page_index = job.payload.get("page_index")
    return [page_index] if type(page_index) is int else []


def _revision_id_of(job: Job) -> uuid.UUID | None:
    raw = job.payload.get("revision_id")
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def _totals(session: AsyncSession) -> tuple[int, int]:
    rows = await session.execute(
        select(Job.status, func.count())
        .where(
            Job.job_type.in_(QUEUE_JOB_TYPES),
            Job.status.in_((JobStatus.RUNNING, JobStatus.QUEUED)),
        )
        .group_by(Job.status)
    )
    counts = {status: int(count) for status, count in rows}
    return counts.get(JobStatus.RUNNING, 0), counts.get(JobStatus.QUEUED, 0)


async def _project_jobs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID, running_total: int
) -> list[tuple[Job, int | None]]:
    """Задания проекта в порядке показа; для `queued` - число заданий перед ним."""
    earlier = aliased(Job)
    queued_before = (
        select(func.count())
        .where(
            earlier.job_type.in_(QUEUE_JOB_TYPES),
            earlier.status == JobStatus.QUEUED,
            tuple_(earlier.available_at, earlier.created_at)
            < tuple_(Job.available_at, Job.created_at),
        )
        .correlate(Job)
        .scalar_subquery()
    )
    scope: tuple[Any, ...] = (
        Job.workspace_id == workspace_id,
        Job.project_id == project_id,
        Job.job_type.in_(QUEUE_JOB_TYPES),
    )
    active = await session.execute(
        select(Job, queued_before).where(
            *scope, Job.status.in_((JobStatus.RUNNING, JobStatus.QUEUED))
        )
    )
    running: list[tuple[Job, int | None]] = []
    queued: list[tuple[Job, int | None]] = []
    for job, before in active:
        if job.status is JobStatus.RUNNING:
            running.append((job, None))
        else:
            queued.append((job, running_total + int(before or 0)))
    running.sort(key=lambda row: (row[0].started_at is None, row[0].started_at, row[0].created_at))
    queued.sort(key=lambda row: (row[0].available_at, row[0].created_at))

    finished = await session.scalars(
        select(Job)
        .where(
            *scope,
            Job.status.in_(_TERMINAL),
            Job.finished_at >= func.now() - RECENT_FINISHED_WINDOW,
        )
        .order_by(Job.finished_at.desc(), Job.id)
        .limit(RECENT_FINISHED_LIMIT)
    )
    return [*running, *queued, *((job, None) for job in finished)]


async def _documents(
    session: AsyncSession, *, project_id: uuid.UUID, revision_ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
    if not revision_ids:
        return {}
    rows = await session.execute(
        select(DocumentRevision.id, Document.id, Document.display_name)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(DocumentRevision.id.in_(revision_ids), Document.project_id == project_id)
    )
    return {revision_id: (document_id, name) for revision_id, document_id, name in rows}


async def build_queue(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> CadQueueRead:
    running_total, queued_total = await _totals(session)
    rows = await _project_jobs(
        session, workspace_id=workspace_id, project_id=project_id, running_total=running_total
    )
    revisions = {rid for job, _ in rows if (rid := _revision_id_of(job)) is not None}
    documents = await _documents(session, project_id=project_id, revision_ids=revisions)
    items: list[CadQueueItemRead] = []
    for job, ahead in rows:
        revision_id = _revision_id_of(job)
        document = documents.get(revision_id) if revision_id is not None else None
        items.append(
            CadQueueItemRead(
                job_id=job.id,
                job_type=job.job_type,
                status=job.status,
                revision_id=revision_id if document is not None else None,
                document_id=document[0] if document is not None else None,
                document_name=document[1] if document is not None else None,
                pages=pages_of(job),
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
                ahead=ahead,
                error_code=job.error_code if job.status is JobStatus.FAILED else None,
            )
        )
    return CadQueueRead(items=items, running_total=running_total, queued_total=queued_total)
