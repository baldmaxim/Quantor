"""Пульс выполняющегося задания.

Своя сессия, а не сессия задания. Сессия задания занята длинной транзакцией импорта:
пульс, отправленный в ней, дошёл бы до базы только после фиксации — то есть тогда,
когда он уже не нужен.

Пульс не только продлевает аренду, но и проверяет, наша ли она ещё. Ответ «нет»
означает, что сборщик брошенных решил, будто исполнитель умер, и отдал задание другому.
Продолжать в этом случае нельзя: ту же работу уже делает кто-то ещё.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from app.core.logging import get_logger
from app.services import jobs as jobs_service
from app.worker.db import get_worker_session_factory

log = get_logger(__name__)


@asynccontextmanager
async def keep_alive(
    *,
    job_id: uuid.UUID,
    worker_id: str,
    lease_seconds: int,
    interval_seconds: float,
    on_lost: Callable[[], None],
) -> AsyncIterator[None]:
    """Держит аренду, пока выполняется тело задания."""

    async def beat() -> None:
        factory = get_worker_session_factory()
        while True:
            await asyncio.sleep(interval_seconds)
            async with factory() as session:
                held = await jobs_service.heartbeat(
                    session, job_id=job_id, worker_id=worker_id, lease_seconds=lease_seconds
                )
                await session.commit()
            if not held:
                log.warning("job_lease_lost", job_id=str(job_id), worker_id=worker_id)
                on_lost()
                return

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        # Ожидание обязательно: без него отменённая задача остаётся висеть, и её
        # исключение всплывёт в чужом месте, где его никто не ждёт.
        await asyncio.gather(task, return_exceptions=True)
