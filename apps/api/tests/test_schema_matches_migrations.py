"""Схема из миграций совпадает со схемой из моделей.

Остальные тесты поднимают таблицы через `Base.metadata.create_all` — быстро, но это
означает, что расхождение модели и миграции они не заметят в принципе: проверяется
модель, а работает в бою миграция.

Работа «Миграции» в CI частично закрывает пробел (`alembic upgrade head` → `alembic check`
→ `downgrade base`), но `alembic check` сравнивает не всё. Он не видит:

- CHECK-констрейнты,
- `ondelete` / `onupdate` у внешних ключей,
- предикаты частичных индексов,
- `server_default`.

То есть ровно то, на чём держится инвариант области видимости задания: `ck_jobs_workspace_scope`
и составной ключ с каскадами. Поэтому здесь схема поднимается **миграциями** в отдельной базе и
сравнивается с моделями по системному каталогу PostgreSQL.

Alembic запускается подпроцессом, а не вызовом `command.upgrade` в этом же процессе:
`alembic/env.py` берёт DSN из `get_settings()`, а тот закэширован на весь прогон. Подменять
кэш ради теста значило бы чинить тест правкой того, что он проверяет.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
from tests.conftest import _test_database_url

API_ROOT = Path(__file__).resolve().parents[1]
MIGRATED_SUFFIX = "_migrations"

# Каталог PostgreSQL описывает то, что действительно построено, а не то, что задумано.
# `pg_get_constraintdef` разворачивает и выражение CHECK, и каскады внешнего ключа.
CONSTRAINTS_SQL = """
select t.relname, c.conname, pg_get_constraintdef(c.oid)
  from pg_constraint c
  join pg_class t on t.oid = c.conrelid
  join pg_namespace n on n.oid = t.relnamespace
 where n.nspname = 'public' and t.relname = any(:tables)
 order by t.relname, c.conname
"""

INDEXES_SQL = """
select tablename, indexname, indexdef
  from pg_indexes
 where schemaname = 'public' and tablename = any(:tables)
 order by tablename, indexname
"""

COLUMNS_SQL = """
select table_name, column_name, data_type, is_nullable, column_default
  from information_schema.columns
 where table_schema = 'public' and table_name = any(:tables)
 order by table_name, column_name
"""


def _migrated_name() -> str:
    _, _, name = _test_database_url()
    return f"{name}{MIGRATED_SUFFIX}"


def _migrated_url() -> str:
    target, _, name = _test_database_url()
    return target.replace(f"/{name}", f"/{_migrated_name()}")


async def _alembic(*args: str) -> None:
    """Запускает alembic против отдельной базы, переопределив её имя окружением."""
    env = {**os.environ, "POSTGRES_DB": _migrated_name()}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *args,
        cwd=str(API_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    if process.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} завершился с кодом {process.returncode}:\n"
            f"{output.decode('utf-8', errors='replace')}"
        )


async def _snapshot(engine: AsyncEngine, tables: list[str]) -> dict[str, list[tuple[str, ...]]]:
    async with engine.connect() as connection:
        snapshot: dict[str, list[tuple[str, ...]]] = {}
        for key, query in (
            ("constraints", CONSTRAINTS_SQL),
            ("indexes", INDEXES_SQL),
            ("columns", COLUMNS_SQL),
        ):
            rows = await connection.execute(text(query), {"tables": tables})
            snapshot[key] = [tuple(str(value) for value in row) for row in rows.all()]
        return snapshot


async def _recreate_database() -> bool:
    _, maintenance_url, _ = _test_database_url()
    name = _migrated_name()
    admin = create_async_engine(maintenance_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'drop database if exists "{name}" with (force)'))
            await connection.execute(text(f'create database "{name}"'))
    except Exception:
        return False
    finally:
        await admin.dispose()
    return True


async def _drop_database() -> None:
    _, maintenance_url, _ = _test_database_url()
    name = _migrated_name()
    admin = create_async_engine(maintenance_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'drop database if exists "{name}" with (force)'))
    finally:
        await admin.dispose()


@pytest.fixture
async def migrated_engine() -> AsyncIterator[AsyncEngine]:
    """База, поднятая миграциями с нуля. Отдельная от той, что строит `create_all`."""
    if not await _recreate_database():
        pytest.skip("PostgreSQL недоступен — поднимите инфраструктуру: pnpm infra:up")

    await _alembic("upgrade", "head")

    engine = create_async_engine(_migrated_url(), poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()
        await _drop_database()


async def test_migrations_build_the_same_schema_as_the_models(
    migrated_engine: AsyncEngine, db_engine: AsyncEngine
) -> None:
    """Миграции и модели дают одну и ту же схему.

    Расхождение здесь означает, что бой и тесты работают с разными таблицами — а это как раз
    тот класс дефектов, который не находят ни обычные тесты, ни `alembic check`.
    """
    tables = sorted(Base.metadata.tables)

    from_migrations = await _snapshot(migrated_engine, tables)
    from_models = await _snapshot(db_engine, tables)

    assert from_migrations["columns"] == from_models["columns"]
    assert from_migrations["constraints"] == from_models["constraints"]
    assert from_migrations["indexes"] == from_models["indexes"]


async def test_migration_backfills_the_workspace_of_existing_jobs(
    migrated_engine: AsyncEngine,
) -> None:
    """Ревизия 0007 переносит арендатора на задание, а не теряет его.

    Проверяется на настоящей смене ревизий: откат до 0006, вставка задания в том виде,
    в каком оно существовало тогда, и повторный подъём.
    """
    await _alembic("downgrade", "0006_job_worker_lease")

    async with migrated_engine.begin() as connection:
        workspace_id = await connection.scalar(
            text(
                "insert into workspaces (id, slug, name, is_active, created_at, updated_at)"
                " values (gen_random_uuid(), 'backfill', 'Backfill', true, now(), now())"
                " returning id"
            )
        )
        project_id = await connection.scalar(
            text(
                "insert into projects (id, workspace_id, name, status, source,"
                " created_at, updated_at)"
                " values (gen_random_uuid(), :ws, 'Проект', 'active', 'manual', now(), now())"
                " returning id"
            ),
            {"ws": workspace_id},
        )
        # Задание с проектом: арендатор восстановим.
        with_project = await connection.scalar(
            text(
                "insert into jobs (id, project_id, job_type, status, attempt, max_attempts,"
                " payload, created_at, updated_at)"
                " values (gen_random_uuid(), :p, 'legacy_import', 'succeeded', 1, 1,"
                " '{}', now(), now()) returning id"
            ),
            {"p": project_id},
        )
        # Задание без проекта: арендатор неизвестен, и угадывать его нельзя.
        orphan = await connection.scalar(
            text(
                "insert into jobs (id, project_id, job_type, status, attempt, max_attempts,"
                " payload, created_at, updated_at)"
                " values (gen_random_uuid(), null, 'legacy_import', 'succeeded', 1, 1,"
                " '{}', now(), now()) returning id"
            )
        )

    await _alembic("upgrade", "head")

    async with migrated_engine.connect() as connection:
        restored = await connection.scalar(
            text("select workspace_id from jobs where id = :id"), {"id": with_project}
        )
        stayed_system = await connection.scalar(
            text("select workspace_id from jobs where id = :id"), {"id": orphan}
        )

    assert restored == workspace_id, "арендатор задания восстановлен из его проекта"
    # Неизвестная принадлежность превращается в отказ в доступе, а не в доступ наугад.
    assert stayed_system is None
