"""Команды обслуживания установки: `python -m app.cli <команда>`.

`create-admin` — администратор платформы для локального входа (ADR-0031). Пароль читается
из терминала без эха или из стандартного ввода, но никогда из аргументов: аргументы
остаются в истории оболочки и видны в списке процессов.

`ensure-bucket` — бакет файлов в хранилище, если его ещё нет. Выполняется при каждой
выкладке и ничего не меняет, когда бакет на месте.

    docker compose -p quantor run --rm api python -m app.cli create-admin --email owner@example.ru
    docker compose -p quantor run --rm api python -m app.cli ensure-bucket

Сопровождение пилота CAD (`app/services/cad_ops.py`; с рабочей машины — `pnpm prod`):

`cad-remarks` — замечания проверяющего к результатам CAD, JSON в стандартный вывод.
`cad-bundle` — выгрузка задания (`in/`, `out/`, `job.json`, `remarks.json`) архивом tar.gz в
стандартный вывод или в файл: входы и выходы попытки со сверкой sha256, для разбора на стенде.
`cad-remark-status` — перевести замечание в `resolved` или вернуть в `open`; единственная запись.

    ./compose.sh exec -T api python -m app.cli cad-remarks --status open
    ./compose.sh exec -T api python -m app.cli cad-bundle <job_id> > bundle.tar.gz
    ./compose.sh exec -T api python -m app.cli cad-remark-status <remark_id> resolved
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import shutil
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory
from app.errors import DomainError
from app.services import cad_ops, local_auth
from app.storage.base import ObjectNotFoundError, StorageUnavailableError
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


def _print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


async def _cad_remarks(
    status: str | None, project_id: uuid.UUID | None, job_id: uuid.UUID | None, limit: int
) -> None:
    try:
        async with get_session_factory()() as session:
            remarks = await cad_ops.list_remarks(
                session, status=status, project_id=project_id, job_id=job_id, limit=limit
            )
        _print_json({"schema": cad_ops.REMARKS_SCHEMA, "remarks": remarks})
    finally:
        await dispose_engine()


async def _cad_remark_status(remark_id: uuid.UUID, status: str) -> None:
    try:
        async with get_session_factory()() as session:
            remark = await cad_ops.set_remark_status(session, remark_id=remark_id, status=status)
            await session.commit()
        _print_json(remark)
    finally:
        await dispose_engine()


async def _cad_bundle(job_id: uuid.UUID, attempt: int | None, include_pdf: bool, out: str) -> None:
    """Каталог выгрузки собирается во временной папке и пакуется целиком в конце.

    Пока идёт сборка, стандартный вывод не трогается: архив в него пишется одним куском
    после проверки всех sha256, и частичный архив на рабочую машину не уходит.
    """
    with tempfile.TemporaryDirectory(prefix="quantor-cad-bundle-") as tmp:
        root = Path(tmp) / "bundle"
        root.mkdir()
        try:
            async with get_session_factory()() as session:
                manifest = await cad_ops.build_bundle(
                    session,
                    S3ObjectStorage(get_settings()),
                    job_id=job_id,
                    attempt=attempt,
                    include_pdf=include_pdf,
                    target=root,
                )
        finally:
            await dispose_engine()
        archive = Path(tmp) / "bundle.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(root.rglob("*")):
                tar.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
        if out == "-":
            with archive.open("rb") as source:
                shutil.copyfileobj(source, sys.stdout.buffer)
            sys.stdout.buffer.flush()
        else:
            shutil.copyfile(archive, out)
        job = manifest["job"]
        print(
            f"Выгрузка задания {job['id']} попытки {job['bundle_attempt']}: "
            f"файлов {len(manifest['files'])}, замечаний {manifest['remarks']}",
            file=sys.stderr,
        )


def _add_ops_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    remarks = commands.add_parser("cad-remarks", help="Замечания к результатам CAD (JSON)")
    remarks.add_argument(
        "--status",
        choices=(*cad_ops.REMARK_STATUSES, "all"),
        default="open",
        help="Статус замечаний; по умолчанию open",
    )
    remarks.add_argument("--project", type=uuid.UUID, default=None, help="Только этот проект")
    remarks.add_argument("--job", type=uuid.UUID, default=None, help="Только это задание")
    remarks.add_argument("--limit", type=int, default=100, help="Сколько замечаний, новые сверху")

    bundle = commands.add_parser("cad-bundle", help="Выгрузка задания CAD архивом tar.gz")
    bundle.add_argument("job_id", type=uuid.UUID)
    bundle.add_argument("--attempt", type=int, default=None, help="Попытка; по умолчанию текущая")
    bundle.add_argument("--no-pdf", action="store_true", help="Без исходного PDF ревизии")
    bundle.add_argument("--out", default="-", help="Файл архива; по умолчанию стандартный вывод")

    status = commands.add_parser("cad-remark-status", help="Статус замечания: open или resolved")
    status.add_argument("remark_id", type=uuid.UUID)
    status.add_argument("status", choices=cad_ops.REMARK_STATUSES)


def _run_ops(args: argparse.Namespace) -> int:
    try:
        if args.command == "cad-remarks":
            status = None if args.status == "all" else args.status
            asyncio.run(_cad_remarks(status, args.project, args.job, args.limit))
        elif args.command == "cad-bundle":
            asyncio.run(_cad_bundle(args.job_id, args.attempt, not args.no_pdf, args.out))
        else:
            asyncio.run(_cad_remark_status(args.remark_id, args.status))
    except cad_ops.CadOpsError as error:
        print(f"Отказ: {error}", file=sys.stderr)
        return 1
    except ObjectNotFoundError as error:
        print(f"В хранилище нет файла: {error}", file=sys.stderr)
        return 1
    except StorageUnavailableError as error:
        print(f"Хранилище недоступно: {error}", file=sys.stderr)
        return 1
    return 0


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
    _add_ops_commands(commands)

    args = parser.parse_args(argv)
    if args.command in ("cad-remarks", "cad-bundle", "cad-remark-status"):
        return _run_ops(args)
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
