"""Сверка схемы базы с миграциями кода.

Устаревшая схема — самая предсказуемая поломка этого репозитория: код обновили,
`alembic upgrade head` не выполнили, и любой запрос падает на несуществующей колонке.
Снаружи это выглядит как «сервис не отвечает», хотя и база жива, и приложение работает.

Поэтому состояние схемы — отдельный компонент готовности со своим сообщением: чинится
одной командой, и знать её надо до того, как начнётся поиск причины в логах.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db.session import get_engine

# app/db/schema_version.py -> app/db -> app -> apps/api
API_ROOT = Path(__file__).resolve().parents[2]


class SchemaOutdatedError(RuntimeError):
    """База отстала от миграций кода."""


@lru_cache(maxsize=1)
def expected_revision() -> str:
    """Голова миграций в коде.

    Читается с диска один раз: файлы миграций не меняются в работающем процессе.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:  # pragma: no cover — миграции есть всегда
        raise RuntimeError("в проекте нет ни одной миграции")
    return head


async def current_revision() -> str | None:
    """Ревизия, накатанная на базу. None — таблицы версий ещё нет."""
    async with get_engine().connect() as connection:
        result = await connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.first()
    return str(row[0]) if row else None


async def check_schema_current() -> None:
    """Бросает исключение, если база отстала. Годится как проба готовности.

    Ловится только отсутствие таблицы версий — значит, миграции не запускали ни разу.
    Отказ подключения не перехватывается намеренно: недоступная база — другая поломка,
    и выдавать её за устаревшую схему значит отправить чинить не то.
    """
    expected = expected_revision()

    try:
        actual = await current_revision()
    except ProgrammingError as error:
        raise SchemaOutdatedError("база не размечена миграциями") from error

    if actual != expected:
        raise SchemaOutdatedError(
            f"база на ревизии {actual or 'без версии'}, коду нужна {expected}"
        )
