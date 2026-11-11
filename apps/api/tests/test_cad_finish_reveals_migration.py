"""Миграция 0031 (откосы в шаблоне отделки): откат убирает колонку, подъём возвращает её."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.test_schema_matches_migrations import _alembic, migrated_engine

__all__ = ["migrated_engine"]


async def _column_default(engine: AsyncEngine) -> str | bool:
    """Умолчание колонки (`'false'`), `False` - колонки нет."""
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "select column_default, is_nullable from information_schema.columns"
                    " where table_schema = 'public' and table_name = 'cad_finish_templates'"
                    " and column_name = 'walls_include_reveals'"
                )
            )
        ).first()
    if row is None:
        return False
    assert row.is_nullable == "NO"
    return str(row.column_default)


async def test_downgrade_and_upgrade_of_the_finish_reveals_migration(
    migrated_engine: AsyncEngine,
) -> None:
    assert await _column_default(migrated_engine) == "false"

    await _alembic("downgrade", "0030_cad_finishes")
    assert await _column_default(migrated_engine) is False

    await _alembic("upgrade", "0031_cad_finish_reveals")
    assert await _column_default(migrated_engine) == "false"
