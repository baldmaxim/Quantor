"""Задания и исполнители: эксплуатационный вид.

Отдельно от пользовательского `/jobs/{id}`: там показывают ход работы, здесь разбирают,
почему она встала. Поэтому видно попытки, исполнителя, срок аренды и время, раньше
которого задание не возьмут.

Полезной нагрузки задания здесь нет и не будет. В ней лежат идентификаторы ревизий и
ключи в хранилище — показывать её целиком значит выносить в интерфейс то, что туда
не просили.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, and_, func, select

from app.api.v1.deps import DEFAULT_PAGE_SIZE, AuthDep, LimitDep, OffsetDep, SessionDep, require
from app.auth.permissions import Permission
from app.core.config import get_settings
from app.domain import AuditAction, JobScope, JobStatus, JobType
from app.errors import not_found
from app.models import Job
from app.schemas import AdminJobRead, JobStatsRead, Page, WorkerRead
from app.services import audit as audit_service
from app.services import jobs as jobs_service
from app.services import workers as workers_service

router = APIRouter(prefix="/jobs")

# За какой срок считать «недавние» отказы на панели. Сутки: короче — не видно ночных
# поломок, длиннее — счётчик перестаёт меняться и его перестают замечать.
RECENT_FAILURES_WINDOW = timedelta(days=1)


def _to_read(job: Job) -> AdminJobRead:
    return AdminJobRead(
        id=job.id,
        project_id=job.project_id,
        workspace_id=job.workspace_id,
        scope=job.scope,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
        error_message=job.error_message,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        worker_id=job.worker_id,
        lease_expires_at=job.lease_expires_at,
        heartbeat_at=job.heartbeat_at,
        available_at=job.available_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        is_retryable=jobs_service.is_retryable(job),
    )


def _visible_to(context: AuthDep) -> ColumnElement[bool] | None:
    """Ограничение видимости. `None` — администратор платформы, видит всю установку.

    Прежде здесь пропускались и задания с пустым `project_id`, то есть общесистемные:
    администратор пространства видел обслуживание всей установки. Теперь граница проходит
    по самому заданию, и сравнение с NULL общесистемные не пропускает.
    """
    if context.principal.is_platform_admin:
        return None
    return Job.workspace_id == context.workspace_id


def _scope_condition(scope: JobScope) -> ColumnElement[bool]:
    """Фильтр по области видимости. Область выводится из пары колонок, а не хранится."""
    if scope is JobScope.SYSTEM:
        return Job.workspace_id.is_(None)
    if scope is JobScope.WORKSPACE:
        return and_(Job.workspace_id.is_not(None), Job.project_id.is_(None))
    return Job.project_id.is_not(None)


@router.get(
    "",
    response_model=Page[AdminJobRead],
    summary="Задания",
    dependencies=[require(Permission.JOBS_READ)],
)
async def list_admin_jobs(
    session: SessionDep,
    context: AuthDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
    status: Annotated[JobStatus | None, Query(description="Фильтр по состоянию")] = None,
    job_type: Annotated[JobType | None, Query(description="Фильтр по типу")] = None,
    project_id: Annotated[uuid.UUID | None, Query(description="Фильтр по проекту")] = None,
    scope: Annotated[JobScope | None, Query(description="Фильтр по области видимости")] = None,
) -> Page[AdminJobRead]:
    """Страница списка заданий.

    Пагинация обязательна: задания копятся всё время работы установки.

    Умолчание для администратора платформы — все области, включая общесистемную: это
    эксплуатационный список, и прятать в нём обслуживание установки значило бы прятать
    её поломки.
    """
    conditions: list[ColumnElement[bool]] = []
    visible = _visible_to(context)
    if visible is not None:
        conditions.append(visible)
    if scope is not None:
        conditions.append(_scope_condition(scope))
    if status is not None:
        conditions.append(Job.status == status)
    if job_type is not None:
        conditions.append(Job.job_type == job_type)
    if project_id is not None:
        conditions.append(Job.project_id == project_id)

    # Соединение с `projects` больше не нужно: принадлежность лежит на самом задании.
    base = select(Job).where(*conditions)
    total = await session.scalar(select(func.count()).select_from(Job).where(*conditions))
    rows = (
        (await session.execute(base.order_by(Job.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )

    return Page(
        items=[_to_read(job) for job in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/stats",
    response_model=JobStatsRead,
    summary="Счётчики очереди",
    dependencies=[require(Permission.JOBS_READ)],
)
async def read_job_stats(session: SessionDep, context: AuthDep) -> JobStatsRead:
    """Сколько заданий ждёт, работает и отказало за сутки.

    Здесь ноль — это настоящий ноль, а не «не измеряли»: счётчики считаются запросом.
    """
    settings = get_settings()
    visible = _visible_to(context)
    conditions: list[ColumnElement[bool]] = [visible] if visible is not None else []

    async def count(*extra: ColumnElement[bool]) -> int:
        query = select(func.count()).select_from(Job).where(*conditions, *extra)
        return int(await session.scalar(query) or 0)

    since = datetime.now(UTC) - RECENT_FAILURES_WINDOW
    health = await workers_service.health(
        session, stale_after_seconds=settings.worker_stale_after_seconds
    )

    return JobStatsRead(
        queued=await count(Job.status == JobStatus.QUEUED),
        running=await count(Job.status == JobStatus.RUNNING),
        failed_recently=await count(Job.status == JobStatus.FAILED, Job.finished_at >= since),
        workers_alive=health.alive,
        workers_total=health.total,
    )


@router.get(
    "/workers",
    response_model=list[WorkerRead],
    summary="Исполнители заданий",
    dependencies=[require(Permission.JOBS_READ)],
)
async def list_job_workers(session: SessionDep) -> list[WorkerRead]:
    """Кто сейчас берёт задания и чем занят."""
    settings = get_settings()
    threshold = datetime.now(UTC) - timedelta(seconds=settings.worker_stale_after_seconds)

    return [
        WorkerRead(
            id=worker.id,
            host=worker.host,
            pid=worker.pid,
            version=worker.version,
            started_at=worker.started_at,
            heartbeat_at=worker.heartbeat_at,
            current_job_id=worker.current_job_id,
            # Считается сервером: у клиента свои часы, и «жив» по ним получилось бы разным.
            is_alive=worker.heartbeat_at > threshold,
        )
        for worker in await workers_service.list_workers(session)
    ]


async def _job_or_404(session: SessionDep, context: AuthDep, job_id: uuid.UUID) -> Job:
    query = select(Job).where(Job.id == job_id)
    visible = _visible_to(context)
    if visible is not None:
        # Общесистемные задания сюда не попадают: сравнение с NULL не истинно.
        query = query.where(visible)
    job = (await session.execute(query)).scalar_one_or_none()
    if job is None:
        raise not_found("Задание")
    return job


@router.get(
    "/{job_id}",
    response_model=AdminJobRead,
    summary="Задание",
    dependencies=[require(Permission.JOBS_READ)],
)
async def read_admin_job(job_id: uuid.UUID, session: SessionDep, context: AuthDep) -> AdminJobRead:
    return _to_read(await _job_or_404(session, context, job_id))


@router.post(
    "/{job_id}/retry",
    response_model=AdminJobRead,
    summary="Повторить задание",
    dependencies=[require(Permission.JOBS_MANAGE)],
)
async def retry_admin_job(job_id: uuid.UUID, session: SessionDep, context: AuthDep) -> AdminJobRead:
    """Возвращает отказавшее задание в очередь.

    Не создаёт второе, а возвращает то же: ключ идемпотентности уникален, и вставка
    дубликата превратилась бы в непонятную ошибку вместо повтора.

    Повторить можно только то, что имеет смысл повторять. Битый архив останется битым,
    и кнопка для него отключена — обещать починку тем, что её не даёт, хуже, чем отказать.
    """
    job = await _job_or_404(session, context, job_id)
    before = {"status": job.status.value, "attempt": job.attempt, "error_code": job.error_code}

    updated = await jobs_service.retry(session, job=job)
    await audit_service.record(
        session,
        context,
        action=AuditAction.JOB_RETRIED,
        resource_type="job",
        resource_id=str(job_id),
        before=before,
        after={"status": updated.status.value, "max_attempts": updated.max_attempts},
    )
    await session.commit()
    await session.refresh(updated)
    return _to_read(updated)


@router.post(
    "/{job_id}/cancel",
    response_model=AdminJobRead,
    summary="Отменить задание",
    dependencies=[require(Permission.JOBS_MANAGE)],
)
async def cancel_admin_job(
    job_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> AdminJobRead:
    """Отменяет задание, которое ещё не начали.

    Только ожидающее. Прерывать выполняющийся импорт на середине нечем: он оставит
    полуразобранный пакет, и разбираться с этим дороже, чем дождаться. Совместная
    отмена появится тогда, когда для неё будет настоящий механизм, а не раньше.
    """
    job = await _job_or_404(session, context, job_id)
    before = {"status": job.status.value}

    updated = await jobs_service.cancel(session, job=job)
    await audit_service.record(
        session,
        context,
        action=AuditAction.JOB_CANCELLED,
        resource_type="job",
        resource_id=str(job_id),
        before=before,
        after={"status": updated.status.value},
    )
    await session.commit()
    await session.refresh(updated)
    return _to_read(updated)
