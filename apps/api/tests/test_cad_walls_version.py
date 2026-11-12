"""Устаревший walls.json: версия генератора против закреплённой в pins.json."""

from __future__ import annotations

import pytest

from app.services.cad_walls_version import parse_walls_version, walls_outdated


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("cad_walls.v1.7", (1, 7, 0)),
        ("cad_walls.v1", (1, 0, 0)),
        ("cad_walls.v2.10.3", (2, 10, 3)),
        (None, None),
        ("", None),
        ("cad_mep.v1.7", None),
        ("cad_walls.v", None),
        ("cad_walls.v1.x", None),
        ("cad_walls.v1.2.3.4", None),
        ("cad_walls.v1." + "9" * 40, None),
    ],
)
def test_parse_walls_version(value: str | None, expected: tuple[int, int, int] | None) -> None:
    assert parse_walls_version(value) == expected


@pytest.mark.parametrize(
    ("generator", "has_slab", "current", "expected"),
    [
        ("cad_walls.v1.7", True, "cad_walls.v1.8", True),
        ("cad_walls.v1.8", True, "cad_walls.v1.8", False),
        ("cad_walls.v1.9", True, "cad_walls.v1.8", False),
        ("cad_walls.v1.10", True, "cad_walls.v1.9", False),
        ("cad_walls.v1.8", True, "cad_walls.v1.8.1", True),
        ("cad_walls.v2", True, "cad_walls.v1.8", False),
        ("garbage", True, "cad_walls.v1.8", True),
        (None, True, "cad_walls.v1.8", True),
        # Нет плиты - устарел при любой версии.
        ("cad_walls.v1.8", False, "cad_walls.v1.8", True),
        ("cad_walls.v9", False, None, True),
        # Закреплённая версия неизвестна или не читается - действует только правило плиты.
        ("cad_walls.v1.7", True, None, False),
        ("cad_walls.v1.7", True, "garbage", False),
        ("garbage", True, None, True),
    ],
)
def test_walls_outdated(
    generator: str | None, has_slab: bool, current: str | None, expected: bool
) -> None:
    assert walls_outdated(generator, has_slab, current) is expected
