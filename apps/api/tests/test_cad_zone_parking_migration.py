"""Миграция 0029 (машино-места в зонах): откат убирает колонку, подъём возвращает её."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]


async def _has_column(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        found = await connection.scalar(
            text(
                "select count(*) from information_schema.columns"
                " where table_schema = 'public' and table_name = 'cad_zones'"
                " and column_name = 'parking_type'"
            )
        )
        return found == 1


async def test_downgrade_and_upgrade_of_the_parking_migration(migrated_engine: AsyncEngine) -> None:
    assert await _has_column(migrated_engine)

    await _alembic("downgrade", "0028_cad_sheet_risers")
    assert not await _has_column(migrated_engine)

    await _alembic("upgrade", "0029_cad_zone_parking")
    assert await _has_column(migrated_engine)
