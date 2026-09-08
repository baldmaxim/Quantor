"""Захват заданий и аренда.

Ни одного `sleep`. Истечение аренды имитируется сдвигом отметки времени прямо в базе:
тест, который ждёт секунды, либо медленный, либо ненадёжный, а чаще и то и другое.

Все времена ставит база. У API и воркера свои часы, и мерить аренду часами процесса
значит получить два разных ответа на вопрос «жив ли исполнитель».
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import Job
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.services import workers as workers_service

LEASE = 60
TYPES = [JobType.LEGACY_IMPORT.value]


async def _queued(session: AsyncSession, workspace_id: uuid.UUID, name: str = "Проект") -> Job:
    project = await projects_service.create_project(session, workspace_id=workspace_id, name=name)
    job = await jobs_service.enqueue(session, job_type=JobType.LEGACY_IMPORT, project_id=project.id)
    await session.commit()
    return job


async def _expire_lease(session: AsyncSession, job_id: uuid.UUID) -> None:
    """Сдвигает срок аренды в прошлое. Так проверяется истечение без ожидания."""
    await session.execute(
        text("update jobs set lease_expires_at = now() - interval '1 minute' where id = :id"),
        {"id": job_id},
    )
    await session.commit()


# ------------------------------------------------------------------------ захват


async def test_claim_takes_a_queued_job(db_session: AsyncSession, workspace_id: uuid.UUID) -> None:
    job = await _queued(db_session, workspace_id)

    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    await db_session.commit()

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status is JobStatus.RUNNING
    assert claimed.worker_id == "w-1"
    assert claimed.attempt == 1
    assert claimed.lease_expires_at is not None
    assert claimed.started_at is not None


async def test_empty_queue_returns_nothing(db_session: AsyncSession) -> None:
    """Пустая очередь — обычное состояние, а не ошибка."""
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    assert claimed is None


async def test_two_workers_never_take_the_same_job(
    db_engine: AsyncEngine, db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Главное свойство захвата: одно задание достаётся ровно одному исполнителю.

    Два соединения, а не две сессии на одном: `for update skip locked` работает между
    транзакциями, и на общем соединении второй запрос просто ждал бы первого.

    Гонки в тесте нет: первый забирает и держит блокировку до фиксации, второй эту
    строку пропускает. Оба порядка выполнения дают один и тот же ответ.
    """
    job = await _queued(db_session, workspace_id)

    factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
    async with factory() as first, factory() as second:
        taken_first = await jobs_service.claim(
            first, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
        )
        taken_second = await jobs_service.claim(
            second, worker_id="w-2", job_types=TYPES, lease_seconds=LEASE
        )
        await first.commit()
        await second.commit()

    winners = [item for item in (taken_first, taken_second) if item is not None]
    assert len(winners) == 1, "задание не должно достаться двоим"
    assert winners[0].id == job.id


async def test_claim_respects_the_backoff(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Отложенное задание не берут раньше срока.

    Иначе отсрочка повтора не работает: упавшее из-за недоступного хранилища задание
    брали бы снова немедленно и клали бы на него ту же нагрузку.
    """
    job = await _queued(db_session, workspace_id)
    await db_session.execute(
        text("update jobs set available_at = now() + interval '1 hour' where id = :id"),
        {"id": job.id},
    )
    await db_session.commit()

    assert (
        await jobs_service.claim(db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE)
        is None
    )


async def test_claim_ignores_foreign_job_types(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Исполнитель берёт только то, что умеет: чужой тип он повесил бы навсегда."""
    await _queued(db_session, workspace_id)

    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=["something_else"], lease_seconds=LEASE
    )
    assert claimed is None


# ------------------------------------------------------------------------ аренда


async def test_heartbeat_extends_the_lease(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    await db_session.commit()
    assert claimed is not None

    await _expire_lease(db_session, claimed.id)
    held = await jobs_service.heartbeat(
        db_session, job_id=claimed.id, worker_id="w-1", lease_seconds=LEASE
    )
    await db_session.commit()
    await db_session.refresh(claimed)

    assert held is True
    assert claimed.lease_expires_at is not None
    # Аренда снова в будущем: пульс её продлил.
    row = await db_session.execute(
        text("select lease_expires_at > now() as ok from jobs where id = :id"), {"id": claimed.id}
    )
    assert row.scalar_one() is True


async def test_heartbeat_from_a_stranger_changes_nothing(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Чужой пульс не продлевает аренду.

    Ответ «нет» — это сигнал исполнителю остановиться: задание уже отдали другому,
    и продолжать работу значит делать её дважды.
    """
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    await db_session.commit()
    assert claimed is not None

    held = await jobs_service.heartbeat(
        db_session, job_id=claimed.id, worker_id="w-2", lease_seconds=LEASE
    )
    assert held is False


async def test_abandoned_job_returns_to_the_queue(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Задание с истёкшей арендой возвращается в очередь с отсрочкой."""
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    await db_session.commit()
    assert claimed is not None

    # Попыток больше одной: иначе задание сразу станет отказом.
    await db_session.execute(
        text("update jobs set max_attempts = 3 where id = :id"), {"id": claimed.id}
    )
    await db_session.commit()
    await _expire_lease(db_session, claimed.id)

    released = await jobs_service.release_expired(db_session, base_seconds=15, max_seconds=900)
    await db_session.commit()
    await db_session.refresh(claimed)

    assert released == 1
    assert claimed.status is JobStatus.QUEUED
    assert claimed.worker_id is None
    assert claimed.lease_expires_at is None
    # Отсрочка выставлена в будущее: немедленный повтор не починит недоступную зависимость.
    row = await db_session.execute(
        text("select available_at > now() as ok from jobs where id = :id"), {"id": claimed.id}
    )
    assert row.scalar_one() is True


async def test_exhausted_attempts_become_a_failure(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Исчерпав попытки, брошенное задание становится отказом, а не висит «выполняется».

    По этому состоянию судят о работоспособности установки: вечное «выполняется»
    выглядит как работа, которой на самом деле нет.
    """
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    await db_session.commit()
    assert claimed is not None
    await _expire_lease(db_session, claimed.id)

    released = await jobs_service.release_expired(db_session, base_seconds=15, max_seconds=900)
    await db_session.commit()
    await db_session.refresh(claimed)

    assert released == 1
    assert claimed.status is JobStatus.FAILED
    assert claimed.error_code == ErrorCode.JOB_LEASE_LOST.value
    assert claimed.finished_at is not None


async def test_live_lease_is_left_alone(db_session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Сборщик не трогает задание с действующей арендой."""
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    await db_session.commit()
    assert claimed is not None

    released = await jobs_service.release_expired(db_session, base_seconds=15, max_seconds=900)
    assert released == 0


# ------------------------------------------------------------------------ повтор


async def test_retry_returns_the_same_job_to_the_queue(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Повтор не создаёт второе задание: ключ идемпотентности уникален."""
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    assert claimed is not None
    await jobs_service.fail(db_session, job=claimed, error_code=ErrorCode.STORAGE_UNAVAILABLE.value)
    await db_session.commit()

    retried = await jobs_service.retry(db_session, job=claimed)
    await db_session.commit()

    assert retried.id == claimed.id
    assert retried.status is JobStatus.QUEUED
    assert retried.error_code is None
    assert retried.max_attempts > retried.attempt


async def test_broken_input_is_not_retryable(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Битый архив останется битым: предлагать повтор — обещать невозможное."""
    await _queued(db_session, workspace_id)
    claimed = await jobs_service.claim(
        db_session, worker_id="w-1", job_types=TYPES, lease_seconds=LEASE
    )
    assert claimed is not None
    await jobs_service.fail(db_session, job=claimed, error_code=ErrorCode.ARCHIVE_UNSAFE_PATH.value)
    await db_session.commit()

    assert jobs_service.is_retryable(claimed) is False
    with pytest.raises(DomainError) as error:
        await jobs_service.retry(db_session, job=claimed)
    assert error.value.code is ErrorCode.JOB_NOT_RETRYABLE


# ------------------------------------------------------------------- исполнители


async def test_worker_health_tells_absent_from_dead(db_session: AsyncSession) -> None:
    """«Не запускали» и «умер» — разные состояния установки."""
    empty = await workers_service.health(db_session, stale_after_seconds=180)
    assert empty.is_present is False
    assert empty.is_healthy is False

    await workers_service.register(
        db_session, worker_id="w-1", host="host", pid=1, version="v1", job_types=TYPES
    )
    await db_session.commit()

    alive = await workers_service.health(db_session, stale_after_seconds=180)
    assert alive.is_present is True
    assert alive.is_healthy is True
    assert alive.alive == 1

    # Пульс в прошлом — исполнитель молчит.
    await db_session.execute(
        text("update workers set heartbeat_at = now() - interval '1 hour' where id = 'w-1'")
    )
    await db_session.commit()

    silent = await workers_service.health(db_session, stale_after_seconds=180)
    assert silent.is_present is True
    assert silent.is_healthy is False
    assert silent.stale == 1


async def test_stopped_worker_is_not_counted_as_dead(db_session: AsyncSession) -> None:
    """Корректно остановленный исполнитель убирает себя сам.

    Иначе плановое выключение выглядело бы в диагностике как поломка.
    """
    await workers_service.register(
        db_session, worker_id="w-1", host="host", pid=1, version="v1", job_types=TYPES
    )
    await db_session.commit()

    await workers_service.unregister(db_session, worker_id="w-1")
    await db_session.commit()

    assert (await workers_service.health(db_session, stale_after_seconds=180)).is_present is False
