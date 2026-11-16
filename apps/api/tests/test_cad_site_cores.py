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


# ------------------------------------------------------- места, отсев и согласие этажей


def test_register_returns_variants_best_first_with_the_second_share_of_other_places() -> None:
    found = cores.register(parking(extra_cores_at=[(40000.0, 90000.0)]), CORE)
    assert found is not None and found.variants
    best = found.variants[0]
    assert (best.rotation_deg, best.tx, best.ty, best.share) == (
        found.rotation_deg,
        found.tx,
        found.ty,
        found.share,
    )
    assert len(found.variants) <= cores.MAX_VARIANTS
    assert cores.second_share(best, found.variants) == pytest.approx(found.second_share)
    assert any(cores.distinct(best, v) for v in found.variants[1:])


def variant(
    share: float, rotation: float = 0.0, tx: float = 0.0, ty: float = 0.0
) -> cores.CoreVariant:
    return cores.CoreVariant(rotation, tx, ty, share)


def match_of(best: cores.CoreVariant, second: float) -> cores.CoreMatch:
    return cores.CoreMatch(best.rotation_deg, best.tx, best.ty, best.share, second, False, (best,))


def choice(floor: int, best: cores.CoreVariant, second: float, before: float) -> cores.FloorChoice:
    return cores.FloorChoice(floor, match_of(best, before), best, second, 0)


CENTRE = (30000.0, 20000.0)


def test_same_place_compares_the_building_centre_not_the_origin_shift() -> None:
    """Поворот на градус сдвигает точку отсчёта на метры, а здание - нет: сравнивается центр."""
    first = variant(0.5, 90.0, 100000.0, 50000.0)
    cx, cy = cores.transform_point(CENTRE[0], CENTRE[1], 90.0, 100000.0, 50000.0)
    # Тот же центр здания при повороте на 1,2°: сдвиг начала другой.
    rx, ry = cores.transform_point(CENTRE[0], CENTRE[1], 91.2, 0.0, 0.0)
    second = variant(0.4, 91.2, cx - rx + 400.0, cy - ry)
    assert math.hypot(first.tx - second.tx, first.ty - second.ty) > cores.AGREE_SHIFT_MM
    assert cores.same_place(first, second, CENTRE)
    assert not cores.same_place(first, variant(0.4, 93.0, first.tx, first.ty), CENTRE)
    assert not cores.same_place(first, variant(0.4, 90.0, first.tx + 3000.0, first.ty), CENTRE)


def test_two_floors_in_one_place_are_accepted_below_the_ratio_threshold() -> None:
    first = choice(0, variant(0.45, 90.0, 1000.0, 2000.0), 0.40, 0.40)
    second = choice(1, variant(0.40, 90.3, 1000.0, 2100.0), 0.35, 0.35)
    decision = cores.choose([first, second], CENTRE)
    assert decision is not None and decision.kind == "agreement"
    assert (decision.agreed, decision.floors) == (2, 2)
    # Положение - у лучшего по доле из согласных.
    assert decision.choice is first


def test_three_floors_agree_and_a_lonely_floor_does_not_matter() -> None:
    place = [choice(i, variant(0.4 + 0.01 * i, 90.0, 1000.0, 2000.0), 0.3, 0.3) for i in range(3)]
    other = choice(3, variant(0.6, 0.0, 90000.0, 10000.0), 0.5, 0.5)
    decision = cores.choose([*place, other], CENTRE)
    assert decision is not None and decision.kind == "agreement"
    assert (decision.agreed, decision.floors) == (3, 4)
    assert decision.choice is place[2]


def test_one_floor_is_never_accepted_by_agreement() -> None:
    assert cores.choose([choice(0, variant(0.6), 0.5, 0.5)], CENTRE) is None


def test_two_places_with_equal_numbers_of_agreeing_floors_are_refused() -> None:
    floors = [
        choice(0, variant(0.5, 90.0, 1000.0, 2000.0), 0.4, 0.4),
        choice(1, variant(0.5, 90.0, 1000.0, 2000.0), 0.4, 0.4),
        choice(2, variant(0.5, 0.0, 80000.0, 9000.0), 0.4, 0.4),
        choice(3, variant(0.5, 0.0, 80000.0, 9000.0), 0.4, 0.4),
    ]
    assert cores.choose(floors, CENTRE) is None


def test_the_place_with_more_agreeing_floors_wins_over_a_better_share() -> None:
    floors = [
        choice(0, variant(0.40, 90.0, 1000.0, 2000.0), 0.3, 0.3),
        choice(1, variant(0.38, 90.0, 1000.0, 2000.0), 0.3, 0.3),
        choice(2, variant(0.60, 0.0, 80000.0, 9000.0), 0.3, 0.3),
    ]
    decision = cores.choose(floors, CENTRE)
    assert decision is not None and decision.kind == "agreement"
    assert decision.choice is floors[0]


def test_agreement_below_the_reserve_share_is_not_accepted() -> None:
    floors = [
        choice(0, variant(0.30, 90.0, 1000.0, 2000.0), 0.1, 0.1),
        choice(1, variant(0.28, 90.0, 1000.0, 2000.0), 0.1, 0.1),
    ]
    assert cores.choose(floors, CENTRE) is None


def test_competitor_removal_accepts_the_best_floor_only_when_it_changes_the_outcome() -> None:
    # До отсева отрыв 1,3, после отсева второе место слабое: проходит обычный порог.
    after = choice(0, variant(0.58), 0.25, 0.45)
    decision = cores.choose([after], CENTRE)
    assert decision is not None and decision.kind == "filtered"
    # Проходило и до отсева (резерв или обычный порог): этим занимается обычная ветка резерва.
    assert cores.choose([choice(0, variant(0.58), 0.25, 0.25)], CENTRE) is None
    # После отсева порог всё равно не пройден.
    assert cores.choose([choice(0, variant(0.58), 0.40, 0.45)], CENTRE) is None


def test_weak_agreement_does_not_block_a_strong_floor_after_removal() -> None:
    floors = [
        choice(0, variant(0.58, 25.9, 1000.0, 2000.0), 0.2, 0.47),
        choice(1, variant(0.24, 0.0, 70000.0, 80000.0), 0.2, 0.38),
        choice(2, variant(0.23, 0.0, 70000.0, 80000.0), 0.2, 0.39),
    ]
    decision = cores.choose(floors, CENTRE)
    assert decision is not None and decision.kind == "filtered"
    assert decision.choice is floors[0]


def test_removal_is_refused_when_another_floor_passes_elsewhere() -> None:
    floors = [
        choice(0, variant(0.58, 25.9, 1000.0, 2000.0), 0.2, 0.47),
        choice(1, variant(0.52, 0.0, 70000.0, 80000.0), 0.2, 0.40),
    ]
    assert cores.choose(floors, CENTRE) is None


def test_area_samples_and_covered_share() -> None:
    square: Ring = [(0.0, 0.0), (10000.0, 0.0), (10000.0, 10000.0), (0.0, 10000.0)]
    samples = cores.area_samples(square)
    assert len(samples) == 100
    left: Ring = [(-5000.0, 0.0), (5000.0, 0.0), (5000.0, 10000.0), (-5000.0, 10000.0)]
    assert cores.covered_share(samples, [left]) == pytest.approx(0.5)
    assert cores.covered_share(samples, [left, square]) == pytest.approx(1.0)
    assert cores.covered_share(samples, []) == 0.0
    assert cores.covered_share([], [square]) == 0.0
