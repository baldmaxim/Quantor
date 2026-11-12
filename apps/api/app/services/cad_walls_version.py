"""Устаревший walls.json: нет плиты либо файл построен более старой версией генератора.

Чистые функции без обращения к хранилищу. Версия генератора вида `cad_walls.v1.7` (или `v1`,
`v1.7.2`) разбирается в кортеж из трёх чисел; закреплённая версия берётся из `pins.json` через
`cad_pins` (сам файл здесь не читается).
"""

from __future__ import annotations

import re
from typing import Final

from app.core.config import Settings
from app.errors import DomainError
from app.services import cad_pins

_VERSION_RE: Final = re.compile(r"^cad_walls\.v(\d{1,6})(?:\.(\d{1,6}))?(?:\.(\d{1,6}))?$")

VersionTuple = tuple[int, int, int]


def parse_walls_version(value: str | None) -> VersionTuple | None:
    """`cad_walls.v1.7` -> (1, 7, 0); пусто или чужой формат - `None`."""
    if value is None:
        return None
    found = _VERSION_RE.match(value)
    if found is None:
        return None
    major, minor, patch = found.groups()
    return int(major), int(minor or 0), int(patch or 0)


def walls_outdated(generator: str | None, has_slab: bool, current: str | None) -> bool:
    """Файл конструкций устарел: нет плиты, версия генератора не читается или старше закреплённой.

    Закреплённая версия не читается или не задана - действует только правило плиты.
    """
    if not has_slab:
        return True
    parsed = parse_walls_version(generator)
    if parsed is None:
        return True
    pinned = parse_walls_version(current)
    if pinned is None:
        return False
    return parsed < pinned


def current_walls_generator(settings: Settings) -> str | None:
    """Закреплённая версия `cad_walls` из pins.json; закрепления нет - `None` (без отказа)."""
    try:
        return cad_pins.load_generator_pin(settings, "cad_walls").generator_version
    except DomainError:
        return None
