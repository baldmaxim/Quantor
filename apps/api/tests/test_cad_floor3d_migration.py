"""Миграция 0027 (3D-вид этажа): откат убирает колонку и обе таблицы, подъём возвращает их."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]

TABLES = ("cad_project_levels", "cad_slab_hole_decisions")


async def _state(engine: AsyncEngine) -> tuple[set[str], bool]:
    async with engine.connect() as connection:
        tables = await connection.scalars(
            text(
                "select table_name from information_schema.tables"
                " where table_schema = 'public' and table_name = any(:names)"
            ),
            {"names": list(TABLES)},
        )
        column = await connection.scalar(
            text(
                "select count(*) from information_schema.columns where table_schema = 'public'"
                " and table_name = 'cad_sheet_levels' and column_name = 'floor_elevation_mm'"
            )
        )
        return set(tables.all()), column == 1


async def test_downgrade_and_upgrade_of_the_floor3d_migration(migrated_engine: AsyncEngine) -> None:
    assert await _state(migrated_engine) == (set(TABLES), True)

    await _alembic("downgrade", "0026_cad_vor")
    assert await _state(migrated_engine) == (set(), False)

    await _alembic("upgrade", "0027_cad_floor3d")
    assert await _state(migrated_engine) == (set(TABLES), True)

    # После повторного подъёма ограничения на месте.
    async with migrated_engine.connect() as connection:
        checks = await connection.scalars(
            text(
                "select conname from pg_constraint where conname in"
                " ('ck_cad_sheet_levels_floor_elevation_range',"
                " 'ck_cad_project_levels_slab_thickness_range',"
                " 'ck_cad_project_levels_slab_source_ref_required')"
            )
        )
        assert len(checks.all()) == 3
