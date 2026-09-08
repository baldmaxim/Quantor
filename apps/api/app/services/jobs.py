"""Сервис заданий: переходы состояний с инвариантами.

Состояния меняются только здесь. Смысл в том, что «выполняется» нельзя поставить задаче,
которая уже упала, а повтор с тем же ключом идемпотентности не порождает второе задание —
иначе один и тот же архив импортировался бы дважды (ADR-0005).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import Job, Project

# Разрешённые переходы.
#
# Два возврата в очередь появились вместе с отдельным исполнителем, и оба узкие:
#
# - `running → queued` — только через `release_expired()`: исполнитель умер, аренда
#   истекла, и задание надо отдать другому. Иначе оно висело бы «выполняется» вечно;
# - `failed → queued` — только через `retry()`: администратор повторяет отказ, который
#   действительно можно повторить.
#
# Успех и отмена остаются окончательными: у них выхода нет и не будет.
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset(
        {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.QUEUED}
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.CANCELLED: frozenset(),
}

# Отказы, которые имеет смысл повторить: они про обстоятельства, а не про сам вход.
# Битый архив останется битым сколько его ни повторяй, и предлагать кнопку «повторить»
# для него значит обещать невозможное.
RETRYABLE_ERROR_CODES: frozenset[str] = frozenset(
    {
        ErrorCode.STORAGE_UNAVAILABLE.value,
        ErrorCode.DATABASE_UNAVAILABLE.value,
        ErrorCode.TENDERHUB_UNAVAILABLE.value,
        ErrorCode.TENDERHUB_RATE_LIMITED.value,
        ErrorCode.JOB_LEASE_LOST.value,
        ErrorCode.JOB_TIMEOUT.value,
    }
)


def is_retryable(job: Job) -> bool:
    """Можно ли повторить это задание.

    Исчерпанные попытки не мешают повтору вручную: администратор видит причину и решает
    сам — на то он и администратор. Мешает только природа ошибки.
    """
    return job.status is JobStatus.FAILED and (job.error_code or "") in RETRYABLE_ERROR_CODES


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    session: AsyncSession,
    *,
    job_type: JobType,
    workspace_id: uuid.UUID | None,
    project_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> Job:
    """Ставит задание в очередь. При повторе с тем же ключом возвращает существующее.

    `workspace_id` — именованный аргумент **без умолчания**. Умолчание `None` означало бы,
    что общесистемное задание создаётся забывчивостью: пропустил параметр — получил задание,
    невидимое пространству. Для намеренного случая есть `enqueue_system`.
    """
    if project_id is not None:
        project = await session.get(Project, project_id)
        if project is None or project.workspace_id != workspace_id:
            # База поймала бы это составным ключом, но сообщением драйвера, а не по делу.
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "Проект не принадлежит указанному рабочему пространству",
            )

    if idempotency_key:
        existing = await find_by_idempotency_key(session, idempotency_key=idempotency_key)
        if existing is not None:
            if existing.workspace_id != workspace_id:
                # Ключ уникален на всю установку. Сегодня он содержит project_id и потому
                # не сталкивается, но это соглашение вызывающего, а не инвариант схемы:
                # без этой проверки чужое задание вернулось бы как своё.
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    "Ключ идемпотентности занят заданием другого рабочего пространства",
                )
            return existing

    job = Job(
        project_id=project_id,
        workspace_id=workspace_id,
        job_type=job_type,
        status=JobStatus.QUEUED,
        idempotency_key=idempotency_key,
        payload=dict(payload or {}),
        # Явное время: server now() внутри одной транзакции одинаков, и два задания
        # получают один created_at — DISTINCT ON тогда выбирает произвольно.
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(job)
    await session.flush()
    await session.refresh(job)
    return job


async def enqueue_system(
    session: AsyncSession,
    *,
    job_type: JobType,
    idempotency_key: str | None = None,
    payload: dict[str, object] | None = None,
) -> Job:
    """Задание вне арендаторов: обслуживание установки.

    Ни одному рабочему пространству оно не видно; читается только административным контуром
    через `get_system_job`. Вызовов пока нет — обёртка заводится вместе с механизмом, чтобы
    общесистемное задание нельзя было создать, просто забыв аргумент.
    """
    return await enqueue(
        session,
        job_type=job_type,
        workspace_id=None,
        idempotency_key=idempotency_key,
        payload=payload,
    )


async def find_by_idempotency_key(session: AsyncSession, *, idempotency_key: str) -> Job | None:
    result = await session.execute(select(Job).where(Job.idempotency_key == idempotency_key))
    return result.scalar_one_or_none()


async def get_job(
    session: AsyncSession, *, workspace_id: uuid.UUID, job_id: uuid.UUID
) -> Job | None:
    """Задание видно только внутри своего рабочего пространства.

    Общесистемные задания (`workspace_id is null`) отсюда не видны никогда и никому:
    сравнение с NULL в SQL не истинно, и отдельной ветки для них здесь нет — именно её
    отсутствие и есть гарантия. Прежде такая ветка была, и задание без проекта попадало
    в любое пространство.
    """
    query = select(Job).where(Job.id == job_id, Job.workspace_id == workspace_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_system_job(session: AsyncSession, *, job_id: uuid.UUID) -> Job | None:
    """Общесистемное задание: обслуживание установки, вне арендаторов.

    Отдельная функция, а не флаг `include_system=True` у `get_job`: такой флаг рано или
    поздно оказывается прокинут из параметра запроса.
    """
    query = select(Job).where(Job.id == job_id, Job.workspace_id.is_(None))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_jobs(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int,
    offset: int,
) -> list[Job]:
    """Задания проекта. Пространство спрашивается отдельно — защита в глубину.

    Вызывающий уже проверил принадлежность проекта, но именно этот предикат делает выборку
    безопасной в отрыве от вызывающего.
    """
    query = (
        select(Job)
        .where(Job.workspace_id == workspace_id, Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_jobs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.workspace_id == workspace_id, Job.project_id == project_id)
    )
    return int(result.scalar_one())


def _ensure_transition(job: Job, target: JobStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[job.status]:
        raise DomainError(
            ErrorCode.JOB_TRANSITION_INVALID,
            # ASCII-стрелка: сообщение может попасть в лог Windows (cp1251),
            # где «→» роняет весь процесс исполнителя при job_crashed.
            f"Переход {job.status.value} -> {target.value} недопустим",
        )


async def start(session: AsyncSession, *, job: Job, stage: str | None = None) -> Job:
    """Отмечает начало работы.

    Идемпотентно для уже `running`: `claim()` переводит в running до тела задания,
    а `execute_*` всё ещё вызывает `start` со стадией — повторный переход запрещён
    автоматом состояний, но стадию выставить нужно.
    """
    if job.status is JobStatus.RUNNING:
        if stage is not None:
            job.stage = stage
        await session.flush()
        return job

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


# --------------------------------------------------------------- захват и аренда
#
# Всё ниже работает на часах базы (`now()`), а не приложения. `created_at` задания ставит
# процесс API — осознанно, см. ограничения этапа, — но аренду так мерить нельзя: два
# процесса с разошедшимися часами начнут отбирать задания друг у друга.


CLAIM_SQL = text(
    """
    update jobs set
        status = 'running',
        worker_id = :worker_id,
        attempt = attempt + 1,
        started_at = coalesce(started_at, now()),
        heartbeat_at = now(),
        lease_expires_at = now() + make_interval(secs => :lease_seconds),
        progress = 0.0,
        stage = null,
        updated_at = now()
    where id = (
        select id from jobs
         where status = 'queued'
           and job_type = any(:job_types)
           and available_at <= now()
         order by available_at, created_at
         limit 1
         for update skip locked
    )
    returning id
    """
)


async def claim(
    session: AsyncSession,
    *,
    worker_id: str,
    job_types: list[str],
    lease_seconds: int,
) -> Job | None:
    """Забирает одно задание из очереди или возвращает None, если брать нечего.

    `for update skip locked` — то, ради чего здесь сырой SQL: два исполнителя, пришедшие
    одновременно, не встают в очередь друг за другом и не берут одно и то же. Второй
    просто пропускает занятую строку и смотрит следующую.

    Порядок `available_at, created_at`, а не только `created_at`: иначе отсрочка повтора
    игнорируется и упавшее задание берут снова немедленно.
    """
    claimed = await session.scalar(
        CLAIM_SQL,
        {"worker_id": worker_id, "job_types": job_types, "lease_seconds": lease_seconds},
    )
    if claimed is None:
        return None
    # UPDATE шёл сырым SQL: если задание уже в identity map (типичный случай тестов
    # и иногда одного запроса API), session.get вернёт устаревший статус без перечитывания.
    return await session.get(Job, claimed, populate_existing=True)


HEARTBEAT_SQL = text(
    """
    update jobs set
        heartbeat_at = now(),
        lease_expires_at = now() + make_interval(secs => :lease_seconds),
        progress = coalesce(:progress, progress),
        stage = coalesce(:stage, stage),
        updated_at = now()
    where id = :job_id and worker_id = :worker_id and status = 'running'
    returning id
    """
)


async def heartbeat(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    progress: float | None = None,
    stage: str | None = None,
) -> bool:
    """Продлевает аренду. False означает, что задание больше не наше.

    Ответ важен: аренду мог отобрать сборщик брошенных, решив, что исполнитель умер.
    Продолжать работу в этом случае нельзя — её уже делает кто-то другой.
    """
    # `returning id` вместо rowcount: у результата в типах SQLAlchemy его нет, а
    # подавлять проверку типов правилами проекта запрещено. Заодно нагляднее.
    updated = await session.scalar(
        HEARTBEAT_SQL,
        {
            "job_id": job_id,
            "worker_id": worker_id,
            "lease_seconds": lease_seconds,
            "progress": progress,
            "stage": stage,
        },
    )
    return updated is not None


RELEASE_EXPIRED_SQL = text(
    """
    update jobs set
        status = case
            when attempt < max_attempts then 'queued'
            else 'failed'
        end,
        worker_id = null,
        lease_expires_at = null,
        available_at = case
            when attempt < max_attempts
            then now() + make_interval(
                secs => least(:base_seconds * power(2, attempt), :max_seconds)
            )
            else available_at
        end,
        error_code = case when attempt < max_attempts then error_code else :lost_code end,
        error_message = case
            when attempt < max_attempts then error_message
            else 'исполнитель перестал отвечать'
        end,
        finished_at = case when attempt < max_attempts then null else now() end,
        updated_at = now()
    where status = 'running'
      and lease_expires_at is not null
      and lease_expires_at < now()
    returning id
    """
)


async def release_expired(session: AsyncSession, *, base_seconds: int, max_seconds: int) -> int:
    """Возвращает в очередь задания, чья аренда истекла.

    Отсрочка растёт вдвое с каждой попыткой: если причина отказа не в самом задании,
    а в недоступной зависимости, немедленный повтор её не починит, а нагрузку добавит.

    Исчерпав попытки, задание становится отказом с отдельным кодом. Молча висеть
    «выполняется» оно не должно: по этому состоянию судят о работоспособности установки.
    """
    result = await session.execute(
        RELEASE_EXPIRED_SQL,
        {
            "base_seconds": base_seconds,
            "max_seconds": max_seconds,
            "lost_code": ErrorCode.JOB_LEASE_LOST.value,
        },
    )
    return len(result.fetchall())


async def retry(session: AsyncSession, *, job: Job) -> Job:
    """Повторяет отказавшее задание.

    Не создаёт второе, а возвращает то же самое в очередь: ключ идемпотентности уникален,
    а импорт пакета и так идемпотентен — второе задание с тем же ключом просто не
    вставится, и повтор превратился бы в непонятную ошибку.
    """
    if not is_retryable(job):
        raise DomainError(
            ErrorCode.JOB_NOT_RETRYABLE,
            f"Отказ {job.error_code or 'без кода'} повтором не чинится",
        )

    _ensure_transition(job, JobStatus.QUEUED)
    job.status = JobStatus.QUEUED
    job.max_attempts = job.attempt + 1
    job.worker_id = None
    job.lease_expires_at = None
    job.error_code = None
    job.error_message = None
    job.finished_at = None
    job.progress = None
    job.stage = None
    await session.flush()
    return job
