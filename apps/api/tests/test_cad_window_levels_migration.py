"""Миграция 0042 (подоконник и высота окна листа): откат убирает столбцы, подъём возвращает."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]


async def _columns(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "select column_name from information_schema.columns"
                " where table_schema = 'public' and table_name = 'cad_sheet_levels'"
                " and column_name in ('window_sill_mm', 'window_head_mm')"
            )
        )
        return {row[0] for row in rows}


async def _check_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        found = await connection.scalar(
            text(
                "select count(*) from pg_constraint"
                " where conname = 'ck_cad_sheet_levels_window_levels_range'"
            )
        )
        return bool(found == 1)


async def test_downgrade_and_upgrade_of_the_window_levels_migration(
    migrated_engine: AsyncEngine,
) -> None:
    both = {"window_sill_mm", "window_head_mm"}
    assert await _columns(migrated_engine) == both
    assert await _check_exists(migrated_engine)

    await _alembic("downgrade", "0041_cad_style_profiles")
    assert await _columns(migrated_engine) == set()
    assert not await _check_exists(migrated_engine)

    await _alembic("upgrade", "0042_sheet_window_levels")
    assert await _columns(migrated_engine) == both
    assert await _check_exists(migrated_engine)
