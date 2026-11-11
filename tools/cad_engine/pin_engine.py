"""Закрепление движка и генераторов CAD в pins.json по checkout репозитория CAD_engine.

    python tools/cad_engine/pin_engine.py --engine <checkout CAD_engine>          # записать
    python tools/cad_engine/pin_engine.py --engine <checkout CAD_engine> --check  # только сверить

Берёт коммит HEAD checkout (он должен быть чистым), читает версии генераторов из их исходников,
считает sha256 файлов параметров и пишет `engine.repo_ref` и раздел `generators` в pins.json.
Архив движка (`engine.archive_path`) пересчитывается и только сверяется: поля архива правятся
вручную по `engine/dist/<имя>.json`. `--check` ничего не пишет и выходит с кодом 1 при расхождении.

Только стандартная библиотека.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PINS_PATH = Path(__file__).resolve().with_name("pins.json")
GENERATORS_PATH = "generators"
GENERATOR_NAMES = ("cad_mep", "cad_walls")
PARAMS_RELPATH = "params/v1.json"
FLOOR3D_RELPATH = "floor3d_dxf.py"
VERSION_LINE = re.compile(r'^GENERATOR_VERSION\s*(?::[^=]+)?=\s*"([A-Za-z0-9._-]{1,48})"', re.M)
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class PinError(Exception):
    """Закрепление невозможно или расходится с checkout."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(raw: bytes) -> str:
    """sha256 канонического JSON: так считают параметры API и сами генераторы."""
    text = json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(text.encode("utf-8"))


def git(engine: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(engine), *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise PinError(f"git {' '.join(args)}: {done.stderr.strip() or 'ошибка'}")
    return done.stdout


def dirty_lines(engine: Path) -> list[str]:
    """Правки отслеживаемых файлов и новые файлы в generators/, engine/dist/ (без кэша Python)."""
    tracked = git(engine, "status", "--porcelain", "--untracked-files=no").splitlines()
    new_files = git(
        engine,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        GENERATORS_PATH,
        "engine/dist",
    ).splitlines()
    lines = dict.fromkeys(tracked + new_files)
    return [line for line in lines if "__pycache__/" not in line and not line.endswith(".pyc")]


def head_commit(engine: Path) -> str:
    """HEAD чистого checkout; грязный - ошибка: пин должен указывать на то, что запушено."""
    commit = git(engine, "rev-parse", "HEAD").strip()
    if COMMIT.match(commit) is None:
        raise PinError(f"git rev-parse HEAD вернул не коммит: {commit!r}")
    dirty = dirty_lines(engine)
    if dirty:
        raise PinError(
            "checkout движка не чистый: закоммитьте и запушьте правки в CAD_engine, "
            "затем повторите.\n" + "\n".join(dirty)
        )
    return commit


def read_version(path: Path) -> str:
    try:
        found = VERSION_LINE.search(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise PinError(f"не прочитан {path}: {error}") from error
    if found is None:
        raise PinError(f"в {path} нет GENERATOR_VERSION")
    return found.group(1)


def generators_section(engine: Path, current: dict[str, Any]) -> dict[str, Any]:
    """Раздел `generators` по checkout; порядок ключей сохраняется от прежнего раздела."""
    root_rel = str(current.get("path", GENERATORS_PATH))
    root = engine / root_rel
    section: dict[str, Any] = {"path": root_rel}
    for name in GENERATOR_NAMES:
        old = current.get(name, {})
        params_rel = f"{root_rel}/{name}/{PARAMS_RELPATH}"
        params = root / name / PARAMS_RELPATH
        try:
            raw = params.read_bytes()
        except OSError as error:
            raise PinError(f"не прочитан {params}: {error}") from error
        entry: dict[str, Any] = {
            "generator_version": read_version(root / name / name / "version.py"),
            "params_path": params_rel,
            "params_sha256": sha256_bytes(raw),
            "params_canonical_sha256": canonical_sha256(raw),
        }
        if name == "cad_walls" or "floor3d_dxf_version" in old:
            entry["floor3d_dxf_version"] = read_version(
                root / "cad_walls" / "cad_walls" / FLOOR3D_RELPATH
            )
        section[name] = entry
    return section


def verify_archive(engine: Path, pins: dict[str, Any]) -> None:
    info = pins["engine"]
    archive = engine / info["archive_path"]
    try:
        actual = sha256_file(archive)
    except OSError as error:
        raise PinError(f"не прочитан архив движка {archive}: {error}") from error
    if actual != info["archive_sha256"]:
        raise PinError(
            f"sha256 архива {info['archive_path']} не совпал с pins "
            f"(pins {info['archive_sha256'][:12]}..., checkout {actual[:12]}...). "
            "Обновите поля engine.archive_* вручную по engine/dist/<имя>.json."
        )


def differences(old: dict[str, Any], new: dict[str, Any], prefix: str = "") -> list[str]:
    found: list[str] = []
    for key in sorted(old.keys() | new.keys()):
        path = f"{prefix}{key}"
        before, after = old.get(key), new.get(key)
        if isinstance(before, dict) and isinstance(after, dict):
            found += differences(before, after, f"{path}.")
        elif before != after:
            found.append(f"{path}: {before!r} -> {after!r}")
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Закрепить движок и генераторы CAD в pins.json")
    parser.add_argument(
        "--engine", type=Path, required=True, help="checkout репозитория CAD_engine"
    )
    parser.add_argument("--check", action="store_true", help="только сверить, ничего не писать")
    args = parser.parse_args(argv)
    try:
        pins: dict[str, Any] = json.loads(PINS_PATH.read_bytes())
        engine: Path = args.engine.resolve()
        commit = head_commit(engine)
        verify_archive(engine, pins)
        updated: dict[str, Any] = json.loads(json.dumps(pins))
        updated["engine"]["repo_ref"] = commit
        updated["generators"] = generators_section(engine, pins.get("generators", {}))
    except (PinError, OSError, ValueError, KeyError) as error:
        print(f"ОШИБКА: {error}", file=sys.stderr)
        return 1
    changes = differences(pins, updated)
    if not changes:
        print("pins.json соответствует checkout движка.")
        return 0
    for line in changes:
        print(line)
    if args.check:
        print("ОШИБКА: pins.json расходится с checkout движка.", file=sys.stderr)
        return 1
    PINS_PATH.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"pins.json обновлён (коммит движка {commit[:12]}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
