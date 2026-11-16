"""Миграция 0041 (профили оформления): откат убирает таблицы и триггер, подъём возвращает."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]


async def _state(engine: AsyncEngine) -> tuple[int, int]:
    async with engine.connect() as connection:
        tables = await connection.scalar(
            text(
                "select count(*) from information_schema.tables"
                " where table_schema = 'public'"
                " and table_name in ('cad_style_profiles', 'cad_style_profile_versions')"
            )
        )
        functions = await connection.scalar(
            text(
                "select count(*) from pg_proc"
                " where proname = 'cad_style_profile_versions_immutable'"
            )
        )
        return int(tables or 0), int(functions or 0)


async def test_downgrade_and_upgrade_of_the_style_profiles_migration(
    migrated_engine: AsyncEngine,
) -> None:
    assert await _state(migrated_engine) == (2, 1)

    await _alembic("downgrade", "0040_cad_facade_views")
    assert await _state(migrated_engine) == (0, 0)

    await _alembic("upgrade", "0041_cad_style_profiles")
    assert await _state(migrated_engine) == (2, 1)
