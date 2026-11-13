"""Закрепление генераторов CAD (`tools/cad_engine/pins.json`, раздел `generators`).

Код генераторов (`cad_mep`, `cad_walls`) живёт в репозитории движка; Quantor знает о нём только
закреплённые версии и sha256 параметров. Модуль стандартный: ни PyMuPDF, ни Shapely сюда не
импортируются, файлы генераторов (кроме файла параметров исполнителя) не читаются.

`params_sha256` в pins - sha256 байт файла параметров (по нему CI сверяет файл движка);
`params_canonical_sha256` - sha256 канонического JSON тех же параметров: именно он у API и
генератора идёт в ключи заданий и provenance (`cad.params_sha256`).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, Literal

from app.core.config import Settings
from app.errors import DomainError, ErrorCode

GeneratorName = Literal["cad_mep", "cad_walls", "cad_eom"]

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_VERSION: Final = re.compile(r"^[A-Za-z0-9._-]{1,48}$")
_PINS_SCHEMA: Final = "quantor.cad_engine.pins.v1"


@dataclass(frozen=True, slots=True)
class GeneratorPin:
    """Закреплённый генератор: версия, путь параметров в репозитории движка и их sha256."""

    generator_version: str
    # Путь файла параметров внутри каталога генераторов: `cad_mep/params/v1.json`.
    params_relpath: Path
    params_sha256: str
    params_canonical_sha256: str
    floor3d_dxf_version: str | None


def pins_path(settings: Settings) -> Path:
    if settings.cad_engine_pins.strip():
        return Path(settings.cad_engine_pins.strip())
    # .../<корень>/apps/api/app/services/cad_pins.py -> <корень>/tools/cad_engine/pins.json
    return Path(__file__).resolve().parents[4] / "tools" / "cad_engine" / "pins.json"


def _pin_error(detail: str) -> DomainError:
    return DomainError(ErrorCode.CAD_ENGINE_UNAVAILABLE, f"Закрепление генераторов CAD: {detail}")


def _text(entry: dict[str, Any], key: str, pattern: re.Pattern[str]) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or pattern.match(value) is None:
        raise _pin_error(f"поле {key} неверно")
    return value


def load_generator_pin(settings: Settings, name: GeneratorName) -> GeneratorPin:
    """Закрепление одного генератора из pins.json; нет файла или раздела - отказ, не умолчание."""
    try:
        pins = json.loads(pins_path(settings).read_bytes())
    except (OSError, ValueError) as error:
        raise _pin_error("pins.json не найден или не читается") from error
    if not isinstance(pins, dict) or pins.get("schema") != _PINS_SCHEMA:
        raise _pin_error("pins.json неизвестной схемы")
    generators = pins.get("generators")
    entry = generators.get(name) if isinstance(generators, dict) else None
    if not isinstance(generators, dict) or not isinstance(entry, dict):
        raise _pin_error(f"в pins.json нет generators.{name}")
    root, params_path = generators.get("path"), entry.get("params_path")
    if not isinstance(root, str) or not isinstance(params_path, str):
        raise _pin_error("не заданы generators.path и params_path")
    try:
        relpath = Path(PurePosixPath(params_path).relative_to(PurePosixPath(root)))
    except ValueError as error:
        raise _pin_error("params_path вне каталога generators.path") from error
    floor3d = entry.get("floor3d_dxf_version")
    return GeneratorPin(
        generator_version=_text(entry, "generator_version", _VERSION),
        params_relpath=relpath,
        params_sha256=_text(entry, "params_sha256", _SHA256),
        params_canonical_sha256=_text(entry, "params_canonical_sha256", _SHA256),
        floor3d_dxf_version=(
            _text(entry, "floor3d_dxf_version", _VERSION) if floor3d is not None else None
        ),
    )


def floor3d_dxf_version(settings: Settings) -> str:
    """Версия скрипта выгрузки 3D DXF (`cad_floor3d_dxf.vN`) из закрепления `cad_walls`."""
    version = load_generator_pin(settings, "cad_walls").floor3d_dxf_version
    if version is None:
        raise _pin_error("в generators.cad_walls нет floor3d_dxf_version")
    return version


def generators_root(settings: Settings) -> Path | None:
    configured = settings.cad_generators_root.strip()
    return Path(configured) if configured else None


def params_file(settings: Settings, explicit: str, pin: GeneratorPin) -> tuple[Path, bool]:
    """Файл параметров генератора и признак «настроен» (явно или каталогом генераторов).

    Ничего не настроено (процесс API без генератора) - путь внутри репозитория движка, файл
    не читается и не сверяется.
    """
    if explicit.strip():
        return Path(explicit.strip()), True
    root = generators_root(settings)
    if root is not None:
        return root / pin.params_relpath, True
    return pin.params_relpath, False


def verify_params_file(path: Path, pin: GeneratorPin, name: GeneratorName) -> None:
    """Файл параметров в образе исполнителя обязан совпасть с пином (sha256 байт)."""
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise DomainError(
            ErrorCode.CAD_ENGINE_UNAVAILABLE, f"Параметры генератора {name} не найдены"
        ) from error
    if actual != pin.params_sha256:
        raise DomainError(
            ErrorCode.CAD_ENGINE_UNAVAILABLE,
            f"Генератор {name} в образе не совпадает с пином (pins.json): параметры другие",
        )


def generator_runner(
    settings: Settings, *, explicit: str, package: GeneratorName, script: str
) -> Path | None:
    """Скрипт генератора: явный путь, иначе в `cad_generators_root`; не настроен - `None`."""
    if explicit.strip():
        return Path(explicit.strip())
    root = generators_root(settings)
    return root / package / script if root is not None else None
