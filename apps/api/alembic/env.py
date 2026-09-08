"""Окружение Alembic: асинхронный движок и настройки приложения как единственный источник DSN."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

# Импорт пакета моделей обязателен: без него autogenerate не увидит таблицы и предложит
# удалить всё, что есть в базе.
import app.models  # noqa: F401
from app.core.config import get_settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata

# Порядок поиска схем на время сравнения. Главная часть решения, а не мелочь.
#
# `postgis_tiger_geocoder` дописывает в search_path базы схемы topology и tiger. После
# этого отражение без явной схемы приносит их таблицы (edges, addrfeat и ещё три десятка)
# так, будто они лежат в public: `schema` у них None, и отфильтровать их по схеме уже
# нельзя. Замерено на живой базе: 49 таблиц против 13 при явном schema="public".
#
# Поэтому search_path сужается до своих схем до начала сравнения.
OWN_SEARCH_PATH = '"$user", public'

# Схемы расширения. После сужения search_path сюда попадать нечему, но проверка остаётся
# на случай сравнения с явным перечислением схем.
EXTENSION_SCHEMAS = frozenset({"tiger", "tiger_data", "topology"})

# А эта таблица лежит именно в public: её создаёт само расширение postgis, и search_path
# от неё не спасает.
EXTENSION_TABLES = frozenset({"spatial_ref_sys"})

# Фильтры узкие намеренно: «пропускать всё, чего нет в моделях» убрало бы шум заодно
# с настоящим расхождением — забытой таблицей, которую как раз и надо заметить.


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Отсекает схемы расширения ещё до отражения — так дешевле и надёжнее."""
    if type_ == "schema":
        return name is None or name not in EXTENSION_SCHEMAS
    return True


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Отсекает то, что принадлежит расширению, а не порталу."""
    if type_ == "table":
        if getattr(obj, "schema", None) in EXTENSION_SCHEMAS:
            return False
        # Только у отражённой: если такая таблица однажды появится в моделях портала,
        # её надо будет увидеть, а не молча пропустить.
        if reflected and name in EXTENSION_TABLES:
            return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # До configure, а не после: отражение схемы происходит внутри него и уже пользуется
    # действующим порядком поиска. Офлайн-режим (`--sql`) этого не проверяет — там живого
    # отражения нет вовсе, и ошибка обнаруживается только на настоящей базе.
    connection.exec_driver_sql(f"SET search_path TO {OWN_SEARCH_PATH}")

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # SET search_path выше открывает транзакцию соединения; begin_transaction()
        # Alembic в этом случае коммитит только savepoint. Без commit на соединении
        # весь upgrade (включая alembic_version) откатывается при выходе из connect().
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
