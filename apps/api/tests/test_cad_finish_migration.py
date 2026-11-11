"""Миграция 0030 (отделка помещений): откат убирает колонки и таблицу, подъём возвращает их."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]


async def _state(engine: AsyncEngine) -> tuple[bool, set[str]]:
    async with engine.connect() as connection:
        table = await connection.scalar(
            text(
                "select count(*) from information_schema.tables"
                " where table_schema = 'public' and table_name = 'cad_finish_templates'"
            )
        )
        columns = await connection.scalars(
            text(
                "select column_name from information_schema.columns"
                " where table_schema = 'public' and table_name = 'cad_zones'"
                " and column_name in ('room_type', 'finish_template_id')"
            )
        )
        return table == 1, set(columns)


async def test_downgrade_and_upgrade_of_the_finishes_migration(
    migrated_engine: AsyncEngine,
) -> None:
    assert await _state(migrated_engine) == (True, {"room_type", "finish_template_id"})

    await _alembic("downgrade", "0029_cad_zone_parking")
    assert await _state(migrated_engine) == (False, set())

    await _alembic("upgrade", "0030_cad_finishes")
    assert await _state(migrated_engine) == (True, {"room_type", "finish_template_id"})
