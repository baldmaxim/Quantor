"""Учёт исполнителей заданий.

Нужен ради различия, которое иначе неразличимо: пустая очередь и отсутствующий
исполнитель выглядят в `jobs` одинаково. «Заданий нет» и «брать их некому» — разные
состояния установки, и диагностика обязана их разводить.

Отметки времени ставит база, а не процесс: у API и воркера свои часы, и расхождение
между ними превратило бы живого исполнителя в мёртвого.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Worker

_NOW = text("now()")


@dataclass(frozen=True, slots=True)
class WorkerHealth:
    """Сводка по исполнителям для диагностики."""

    total: int
    alive: int
    stale: int
    last_heartbeat_at: datetime | None

    @property
    def is_healthy(self) -> bool:
        return self.alive > 0

    @property
    def is_present(self) -> bool:
        """Хоть один исполнитель когда-либо регистрировался.

        Отличать это от «все умерли» важно: на свежей установке воркер просто ещё
        не запускали, и пугать администратора красным здесь не за что.
        """
        return self.total > 0


async def register(
    session: AsyncSession,
    *,
    worker_id: str,
    host: str,
    pid: int,
    version: str,
    job_types: list[str],
) -> None:
    """Отмечает исполнителя живым. Повторный запуск с тем же именем обновляет запись."""
    statement = insert(Worker).values(
        id=worker_id,
        host=host,
        pid=pid,
        version=version,
        started_at=_NOW,
        heartbeat_at=_NOW,
        job_types=job_types,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Worker.id],
            set_={"pid": pid, "version": version, "started_at": _NOW, "heartbeat_at": _NOW},
        )
    )


async def heartbeat(
    session: AsyncSession, *, worker_id: str, current_job_id: uuid.UUID | None
) -> None:
    """Отмечает исполнителя живым и показывает, чем он занят."""
    await session.execute(
        text("update workers set heartbeat_at = now(), current_job_id = :job_id where id = :id"),
        {"id": worker_id, "job_id": current_job_id},
    )


async def unregister(session: AsyncSession, *, worker_id: str) -> None:
    """Убирает запись при корректной остановке.

    Остановленный по-человечески исполнитель не должен потом числиться мёртвым:
    иначе диагностика показывает поломку там, где было плановое выключение.
    """
    await session.execute(delete(Worker).where(Worker.id == worker_id))


async def health(session: AsyncSession, *, stale_after_seconds: int) -> WorkerHealth:
    """Сколько исполнителей живо и когда последний раз давали о себе знать."""
    row = (
        await session.execute(
            text(
                """
                select
                    count(*) as total,
                    count(*) filter (
                        where heartbeat_at > now() - make_interval(secs => :stale)
                    ) as alive,
                    max(heartbeat_at) as last_heartbeat_at
                from workers
                """
            ),
            {"stale": stale_after_seconds},
        )
    ).one()

    total = int(row.total or 0)
    alive = int(row.alive or 0)
    return WorkerHealth(
        total=total,
        alive=alive,
        stale=total - alive,
        last_heartbeat_at=row.last_heartbeat_at,
    )


async def list_workers(session: AsyncSession) -> list[Worker]:
    query = select(Worker).order_by(Worker.heartbeat_at.desc())
    return list((await session.execute(query)).scalars().all())


async def prune_stale(session: AsyncSession, *, older_than_seconds: int) -> int:
    """Убирает давно замолчавших.

    Задания они уже отпустили — этим занимается сборщик брошенных, — и держать их
    записи значит копить мусор, по которому потом судят о состоянии установки.
    """
    result = await session.execute(
        text(
            "delete from workers"
            " where heartbeat_at < now() - make_interval(secs => :age)"
            " returning id"
        ),
        {"age": older_than_seconds},
    )
    return len(result.fetchall())
