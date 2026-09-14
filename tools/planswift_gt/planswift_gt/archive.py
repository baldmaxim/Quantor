"""Необязательная распаковка `.7z` системным 7-Zip.

Канон входа — распакованный каталог. Архив — удобство: библиотека разбора 7z ради этого не
добавляется, вызывается системный `7z`. Архив недоверенный, поэтому до распаковки проверяется
оглавление: без абсолютных путей, без `..`, суммарный размер под пределом.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path, PureWindowsPath

MAX_UNPACKED_BYTES = 4 * 1024 * 1024 * 1024


class ArchiveRejectedError(ValueError):
    pass


def _seven_zip() -> str:
    for name in ("7z", "7za", "7zz"):
        found = shutil.which(name)
        if found:
            return found
    raise ArchiveRejectedError("7-Zip не найден в PATH: распакуйте архив сами и передайте каталог")


def check_listing(paths: list[str], sizes: list[int], *, limit: int = MAX_UNPACKED_BYTES) -> None:
    for raw in paths:
        pure = PureWindowsPath(raw)
        if pure.is_absolute() or pure.drive or raw.startswith(("/", "\\")):
            raise ArchiveRejectedError(f"абсолютный путь в архиве: {raw}")
        if ".." in pure.parts:
            raise ArchiveRejectedError(f"выход за каталог распаковки: {raw}")
    total = sum(sizes)
    if total > limit:
        raise ArchiveRejectedError(f"распакованный размер {total} байт больше предела {limit}")


def _listing(executable: str, archive: Path) -> tuple[list[str], list[int]]:
    completed = subprocess.run(
        [executable, "l", "-slt", "-ba", "-sccUTF-8", str(archive)],
        check=True,
        capture_output=True,
    )
    paths: list[str] = []
    sizes: list[int] = []
    for line in completed.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("Path = "):
            paths.append(line[len("Path = ") :])
        elif line.startswith("Size = "):
            value = line[len("Size = ") :].strip()
            sizes.append(int(value) if value.isdigit() else 0)
    return paths, sizes


def extract(archive: Path, work_dir: Path) -> Path:
    executable = _seven_zip()
    paths, sizes = _listing(executable, archive)
    if not paths:
        raise ArchiveRejectedError(f"{archive}: пустое оглавление")
    check_listing(paths, sizes)
    target = work_dir / archive.stem
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [executable, "x", "-y", "-sccUTF-8", f"-o{target}", str(archive)],
        check=True,
        capture_output=True,
    )
    return target
