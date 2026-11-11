"""Запуск разбора одного PDF паспорта листа в подпроцессе с пределом памяти и времени.

Тяжёлый или битый файл не должен убивать исполнителя (в бою он ограничен по памяти): разбор
идёт отдельным процессом в своей группе с RLIMIT_AS; по таймауту убивается вся группа.
Результат - файл JSON в каталоге рядом с PDF, а не stdout (родитель не держит его в памяти).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import resource
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

from app.services.consistency import passport_cli
from app.services.consistency.passport_codec import candidate_from_json
from app.services.consistency.sheet_passport import PassportCandidate

REASON_MEMORY: Final = "ParseMemoryLimit"
REASON_TIMEOUT: Final = "ParseTimeout"
REASON_FAILED: Final = "ParseFailed"

# apps/api/app/services/consistency/passport_process.py -> apps/api: корень для `import app`.
_API_ROOT: Final = Path(__file__).resolve().parents[3]
_OUT_NAME: Final = "candidates.json"


class PassportParseError(Exception):
    """Файл не разобран; `reason` - класс причины для итога задания (без содержимого документа)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _memory_limiter(limit_mb: int) -> Callable[[], None]:
    def apply() -> None:
        limit = limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

    return apply


def _command(pdf_path: Path, file_name: str, out_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "app.services.consistency.passport_cli",
        str(pdf_path),
        file_name,
        str(out_path),
    ]


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL)


async def parse_pdf_in_subprocess(
    path: Path, file_name: str, *, memory_limit_mb: int, timeout_seconds: float
) -> list[PassportCandidate]:
    """Кандидаты по страницам PDF; отказ - `PassportParseError` с классом причины.

    Окружение пустое, кроме PATH, LANG и PYTHONPATH на корень API (пакет читается из
    исходников, как в образе); рабочий каталог - каталог файла.
    """
    out_path = path.parent / _OUT_NAME
    process = await asyncio.create_subprocess_exec(
        *_command(path, file_name, out_path),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=path.parent,
        env={
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(_API_ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MALLOC_ARENA_MAX": "2",
        },
        start_new_session=True,
        preexec_fn=_memory_limiter(memory_limit_mb),
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            code = await process.wait()
    except (TimeoutError, asyncio.CancelledError) as error:
        _kill_group(process.pid)
        await process.wait()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise PassportParseError(REASON_TIMEOUT) from None
    _kill_group(process.pid)
    if code < 0 or code == passport_cli.EXIT_MEMORY:
        # Убит сигналом (в том числе SIGKILL/SIGSEGV при исчерпании предела) или MemoryError.
        raise PassportParseError(REASON_MEMORY)
    if code != 0:
        raise PassportParseError(REASON_FAILED)
    try:
        raw = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("ожидался список")
        return [candidate_from_json(item) for item in raw]
    except (OSError, ValueError):
        raise PassportParseError(REASON_FAILED) from None
