"""Сервис заданий: переходы состояний с инвариантами.

Состояния меняются только здесь. Смысл в том, что «выполняется» нельзя поставить задаче,
которая уже упала, а повтор с тем же ключом идемпотентности не порождает второе задание —
иначе один и тот же архив импортировался бы дважды (ADR-0005).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import Job, Project

# Разрешённые переходы. Из завершённого состояния выхода нет: перезапуск — это новое задание.
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    session: AsyncSession,
    *,
    job_type: JobType,
    project_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> Job:
    """Ставит задание в очередь. При повторе с тем же ключом возвращает существующее."""
    if idempotency_key:
        existing = await find_by_idempotency_key(session, idempotency_key=idempotency_key)
        if existing is not None:
            return existing

    job = Job(
        project_id=project_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        idempotency_key=idempotency_key,
        payload=dict(payload or {}),
    )
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def find_by_idempotency_key(session: AsyncSession, *, idempotency_key: str) -> Job | None:
    result = await session.execute(select(Job).where(Job.idempotency_key == idempotency_key))
    return result.scalar_one_or_none()


async def get_job(
    session: AsyncSession, *, workspace_id: uuid.UUID, job_id: uuid.UUID
) -> Job | None:
    """Задание видно только внутри своего рабочего пространства.

    Задания без проекта (общесистемные) на Stage 1 не создаются, но контракт учитывает
    и такой случай: у них project_id пуст, и они доступны в dev-режиме.
    """
    query = (
        select(Job)
        .outerjoin(Project, Job.project_id == Project.id)
        .where(
            Job.id == job_id,
            (Job.project_id.is_(None)) | (Project.workspace_id == workspace_id),
        )
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_jobs(
    session: AsyncSession, *, project_id: uuid.UUID, limit: int, offset: int
) -> list[Job]:
    query = (
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_jobs(session: AsyncSession, *, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Job).where(Job.project_id == project_id)
    )
    return int(result.scalar_one())


def _ensure_transition(job: Job, target: JobStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[job.status]:
        raise DomainError(
            ErrorCode.JOB_TRANSITION_INVALID,
            f"Переход {job.status.value} → {target.value} недопустим",
        )


async def start(session: AsyncSession, *, job: Job, stage: str | None = None) -> Job:
    _ensure_transition(job, JobStatus.RUNNING)
    job.status = JobStatus.RUNNING
    job.started_at = _now()
    job.stage = stage
    job.progress = 0.0
    await session.flush()
    return job


async def report_progress(
    session: AsyncSession, *, job: Job, progress: float, stage: str | None = None
) -> Job:
    """Прогресс имеет смысл только у выполняющегося задания."""
    if job.status is not JobStatus.RUNNING:
        raise DomainError(
            ErrorCode.JOB_TRANSITION_INVALID,
            "Прогресс можно сообщать только выполняющемуся заданию",
        )
    job.progress = min(max(progress, 0.0), 1.0)
    if stage is not None:
        job.stage = stage
    await session.flush()
    return job


async def succeed(
    session: AsyncSession, *, job: Job, payload: dict[str, object] | None = None
) -> Job:
    _ensure_transition(job, JobStatus.SUCCEEDED)
    job.status = JobStatus.SUCCEEDED
    job.progress = 1.0
    job.finished_at = _now()
    job.error_code = None
    job.error_message = None
    if payload:
        job.payload = {**job.payload, **payload}
    await session.flush()
    return job


async def fail(
    session: AsyncSession, *, job: Job, error_code: str, error_message: str | None = None
) -> Job:
    """Наружу уходит код и короткое сообщение; трассировка остаётся в логах."""
    _ensure_transition(job, JobStatus.FAILED)
    job.status = JobStatus.FAILED
    job.finished_at = _now()
    job.error_code = error_code
    job.error_message = (error_message or "")[:500] or None
    await session.flush()
    return job


async def cancel(session: AsyncSession, *, job: Job) -> Job:
    _ensure_transition(job, JobStatus.CANCELLED)
    job.status = JobStatus.CANCELLED
    job.finished_at = _now()
    await session.flush()
    return job
