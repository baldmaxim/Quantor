"""Команды обслуживания установки: `python -m app.cli <команда>`.

`create-admin` — администратор платформы для локального входа (ADR-0031). Пароль читается
из терминала без эха или из стандартного ввода, но никогда из аргументов: аргументы
остаются в истории оболочки и видны в списке процессов.

`ensure-bucket` — бакет файлов в хранилище, если его ещё нет. Выполняется при каждой
выкладке и ничего не меняет, когда бакет на месте.

    docker compose -p quantor run --rm api python -m app.cli create-admin --email owner@example.ru
    docker compose -p quantor run --rm api python -m app.cli ensure-bucket
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.errors import DomainError
from app.services import local_auth
from app.storage.base import StorageUnavailableError
from app.storage.s3 import S3ObjectStorage


def _read_password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("Пароль: ")
        second = getpass.getpass("Повторите пароль: ")
        if first != second:
            raise SystemExit("Пароли не совпадают")
        return first
    return sys.stdin.readline().rstrip("\n")


async def _create_admin(email: str, display_name: str | None, password: str) -> None:
    try:
        async with get_session_factory()() as session:
            user = await local_auth.create_platform_admin(
                session, email=email, password=password, display_name=display_name
            )
            await session.commit()
            print(f"Администратор платформы готов: {user.email}")
    finally:
        await dispose_engine()


async def _ensure_bucket() -> None:
    storage = S3ObjectStorage(get_settings())
    created = await storage.ensure_bucket()
    print(f"Бакет {storage.bucket}: {'создан' if created else 'уже есть'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create_admin = commands.add_parser(
        "create-admin",
        help="Создать администратора платформы или восстановить ему доступ",
    )
    create_admin.add_argument("--email", required=True, help="Почта — логин администратора")
    create_admin.add_argument("--name", default=None, help="Отображаемое имя")

    commands.add_parser("ensure-bucket", help="Создать бакет файлов, если его нет")

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        password = _read_password()
        try:
            asyncio.run(_create_admin(args.email, args.name, password))
        except DomainError as error:
            print(f"Отказ: {error.detail}", file=sys.stderr)
            return 1
    elif args.command == "ensure-bucket":
        try:
            asyncio.run(_ensure_bucket())
        except StorageUnavailableError as error:
            print(f"Хранилище недоступно: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
