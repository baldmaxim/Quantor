"""Миграция 0045 (ручная привязка корпуса): откат убирает таблицу, подъём возвращает её."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]


async def _exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        found = await connection.scalar(
            text(
                "select count(*) from information_schema.tables"
                " where table_schema = 'public' and table_name = 'cad_site_pins'"
            )
        )
        return bool(found == 1)


async def test_downgrade_and_upgrade_of_the_site_pins_migration(
    migrated_engine: AsyncEngine,
) -> None:
    assert await _exists(migrated_engine)

    await _alembic("downgrade", "0044_cad_zone_quality")
    assert not await _exists(migrated_engine)

    await _alembic("upgrade", "0045_cad_site_pins")
    assert await _exists(migrated_engine)
