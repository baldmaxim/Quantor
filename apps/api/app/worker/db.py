"""Подключение воркера к базе.

Свой движок, а не общий с API. Настройки API рассчитаны на короткий запрос: предел
времени на выражение — 15 секунд, и импорт пакета на 47 МБ в него не укладывается.
Менять их ради воркера значит ослабить защиту API от зависшего запроса.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

# Импорт эталонного пакета — полторы секунды, но документы бывают в разы больше.
# Пять минут с запасом; зависший навсегда запрос всё равно не остаётся незамеченным.
STATEMENT_TIMEOUT_SECONDS = 300


@lru_cache(maxsize=1)
def get_worker_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        # Соединений ровно столько, сколько заданий процесс исполняет одновременно,
        # плюс одно на пульс: он ходит своей сессией, потому что сессия задания занята
        # длинной транзакцией.
        pool_size=settings.worker_concurrency + 1,
        max_overflow=1,
        echo=False,
        connect_args={"command_timeout": STATEMENT_TIMEOUT_SECONDS},
    )


@lru_cache(maxsize=1)
def get_worker_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_worker_engine(), expire_on_commit=False, autoflush=False)


async def dispose_worker_engine() -> None:
    if get_worker_engine.cache_info().currsize:
        await get_worker_engine().dispose()
    get_worker_engine.cache_clear()
    get_worker_session_factory.cache_clear()
