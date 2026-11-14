"""Постановка по ядрам: поворот и сдвиг по совпадению монолита (чистые функции, синтетика)."""

from __future__ import annotations

import math

import pytest

from app.services import cad_site_cores as cores

Ring = list[tuple[float, float]]


def wall(x: float, y: float, length: float, thick: float, angle: float = 0.0) -> Ring:
    """Прямоугольник стены: начало (x, y), длина вдоль `angle` градусов, толщина поперёк."""
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    vx, vy = -uy, ux
    return [
        (x, y),
        (x + ux * length, y + uy * length),
        (x + ux * length + vx * thick, y + uy * length + vy * thick),
        (x + vx * thick, y + vy * thick),
    ]


# Ядро секции: несимметричный набор стен и пилонов (лестница, лифты, шахты).
CORE: list[Ring] = [
    wall(0, 0, 7200, 400),
    wall(0, 400, 5000, 400, 90),
    wall(2600, 400, 3100, 300, 90),
    wall(4100, 2600, 3100, 400),
    wall(6800, 400, 5800, 400, 90),
    wall(1000, 5400, 2400, 400),
    wall(9000, 1500, 1200, 1200),
    wall(-3000, 8000, 4000, 400, 90),
    wall(12000, 9000, 4500, 400, 35),
    wall(-7000, -4000, 3000, 400),
    wall(15000, -3000, 1500, 600),
    wall(3000, 11000, 600, 2500),
]


def moved(rings: list[Ring], deg: float, tx: float, ty: float) -> list[Ring]:
    return [[cores.transform_point(x, y, deg, tx, ty) for x, y in ring] for ring in rings]


def parking(extra_cores_at: list[tuple[float, float]] | None = None) -> list[Ring]:
    """План подземки: ядро секции повёрнуто на 27° и сдвинуто, плюс чужие стены и пилоны."""
    rings = moved(CORE, 27.0, 120000.0, 45000.0)
    rings += [wall(20000 + 9000 * i, 15000 + 4000 * (i % 3), 6000, 300) for i in range(6)]
    rings += [wall(60000, 70000 + 5000 * i, 300, 3000, 90) for i in range(4)]
    for x, y in extra_cores_at or []:
        rings += moved(CORE, 27.0, x, y)
    return rings


def test_dominant_angle_is_wall_direction_modulo_90() -> None:
    assert cores.dominant_angle(CORE) == pytest.approx(0.25, abs=0.3)
    assert cores.dominant_angle(moved(CORE, 27.0, 0, 0)) == pytest.approx(27.0, abs=0.5)
    assert cores.dominant_angle(moved(CORE, 117.0, 0, 0)) == pytest.approx(27.0, abs=0.5)


def test_core_set_is_found_with_rotation_and_shift() -> None:
    found = cores.register(parking(), CORE)
    assert found is not None and found.accepted
    assert found.rotation_deg == pytest.approx(27.0, abs=0.3)
    x, y = cores.transform_point(0.0, 0.0, found.rotation_deg, found.tx, found.ty)
    assert (x, y) == pytest.approx((120000.0, 45000.0), abs=300.0)
    assert found.share >= cores.MIN_SHARE
    assert found.share >= cores.MIN_RATIO * found.second_share


def test_identical_core_in_two_places_is_ambiguous() -> None:
    """Типовая секция: то же ядро ещё в одном месте - совмещение не принимается."""
    found = cores.register(parking(extra_cores_at=[(40000.0, 90000.0)]), CORE)
    assert found is not None and not found.accepted
    assert found.share >= cores.MIN_SHARE


def test_wrong_scale_does_not_match() -> None:
    """Лист с неверным масштабом: ядра меньше - совпадения нет (масштаб не подбирается)."""
    small = [[(x * 0.72, y * 0.72) for x, y in ring] for ring in CORE]
    found = cores.register(parking(), small)
    assert found is None or not found.accepted


def test_too_little_monolith_gives_no_result() -> None:
    assert cores.register(parking(), [wall(0, 0, 1000, 200)]) is None
    assert cores.register([], CORE) is None
