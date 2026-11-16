"""Ручная привязка корпуса к площадке по двум парам точек (ADR-0052): математика и посадка."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts.cad_building3d import CadBuilding3dFloorRead
from app.services import cad_building3d as b3d
from app.services import cad_site_pins_math as pm
from app.services.cad_building3d_assembly import build_stack
from tests.test_cad_building3d import axes_block, built, section_axes, with_cores
from tests.test_cad_floor3d import BASE
from tests.test_cad_site_cores import CORE, parking

EPOCH = datetime(2026, 11, 16, tzinfo=UTC)
Point = tuple[float, float]


def _points(origin: Point, degrees: float, length: float = 20000.0) -> tuple[Point, Point]:
    radians = math.radians(degrees)
    return origin, (origin[0] + length * math.cos(radians), origin[1] + length * math.sin(radians))


# ------------------------------------------------------------------ математика


@pytest.mark.parametrize("degrees", [0.0, 25.9, 90.0, 205.0])
def test_solved_transform_maps_source_points_onto_target_points(degrees: float) -> None:
    source = ((1200.0, -300.0), (21200.0, 9000.0))
    p_len = math.dist(*source)
    q1 = (150000.0, 70000.0)
    base_angle = math.degrees(math.atan2(9300.0, 20000.0))
    target = _points(q1, base_angle + degrees, p_len)
    solved = pm.solve_pin(source, target)
    for p, q in zip(source, target, strict=True):
        x, y = pm.apply_transform(solved.rotation_deg, solved.offset_mm, p)
        assert (x, y) == pytest.approx(q, abs=1.0)
    assert solved.baseline_mm == pytest.approx(p_len)
    assert solved.residual_mm == pytest.approx(0.0, abs=1e-6)
    assert -180.0 < solved.rotation_deg <= 180.0


def test_short_baseline_is_refused() -> None:
    with pytest.raises(pm.SitePinError, match="слишком близко"):
        pm.solve_pin(((0.0, 0.0), (3000.0, 0.0)), ((10000.0, 0.0), (13000.0, 0.0)))


def test_lengths_that_differ_more_than_a_percent_are_refused() -> None:
    with pytest.raises(pm.SitePinError, match="не совпадают"):
        pm.solve_pin(((0.0, 0.0), (20000.0, 0.0)), ((0.0, 0.0), (20400.0, 0.0)))
    solved = pm.solve_pin(((0.0, 0.0), (20000.0, 0.0)), ((0.0, 0.0), (20150.0, 0.0)))
    assert solved.residual_mm == pytest.approx(150.0)


# ------------------------------------------------------------------ посадка


def _key(floor: CadBuilding3dFloorRead) -> pm.SheetKey:
    return floor.revision_id, floor.page_index, floor.view


def pin_for(
    source: b3d.BuiltFloor,
    target: b3d.BuiltFloor,
    p: tuple[Point, Point],
    q: tuple[Point, Point],
    minutes: int = 0,
) -> pm.SitePin:
    solved = pm.solve_pin(p, q)
    return pm.SitePin(
        id=uuid.uuid4(),
        source=_key(source.floor),
        target=_key(target.floor),
        rotation_deg=solved.rotation_deg,
        offset_mm=solved.offset_mm,
        baseline_mm=solved.baseline_mm,
        residual_mm=solved.residual_mm,
        created_at=EPOCH + timedelta(minutes=minutes),
    )


def underground() -> b3d.BuiltFloor:
    return with_cores(
        built(corps=None, section=None, elevation=BASE - 5000),
        parking(),
        bbox=[0.0, 0.0, 220000.0, 180000.0],
    )


def site(
    items: list[b3d.BuiltFloor], pins: list[pm.SitePin]
) -> tuple[b3d.SiteResult, list[CadBuilding3dFloorRead]]:
    aligned = b3d.align_floors(items)
    result = b3d.place_site_report(items, aligned, pins)
    return result, b3d.apply_placements(aligned, result.placements)


def floor_of_group(floors: list[CadBuilding3dFloorRead], key: str) -> CadBuilding3dFloorRead:
    return next(f for f in floors if f.group_key == key)


def test_group_without_axes_and_cores_is_placed_by_the_pin() -> None:
    under = underground()
    tower = built(corps="5", section=None, order=1)
    # Плита тестового этажа: прямоугольник 6000 x 4000, точки базы - его углы по диагонали
    # растянуты до базы 20 м не нужны: база - любые две точки кадра вида.
    p = ((0.0, 0.0), (20000.0, 0.0))
    q = _points((100000.0, 50000.0), 25.9)
    pin = pin_for(tower, under, p, q)
    result, floors = site([under, tower], [pin])
    group = result.placements["k5"]
    assert (group.placement, group.pin_id, group.anchor_key) == ("manual", pin.id, "none")
    assert group.message == "привязано вручную: невязка 0 мм, база 20,0 м"
    assert result.ignored == ()
    moved = floor_of_group(floors, "k5")
    # Вершина плиты (0, 0) вида - точка p1, она встаёт в q1.
    assert moved.outline[0] == pytest.approx(q[0], abs=1.0)
    # Вершина (6000, 0) лежит на оси базы: на луче q1 -> q2 на расстоянии 6000.
    expected = (
        q[0][0] + 6000.0 * math.cos(math.radians(25.9)),
        q[0][1] + 6000.0 * math.sin(math.radians(25.9)),
    )
    assert moved.outline[1] == pytest.approx(expected, abs=1.0)
    groups = {g.key: g for g in b3d.build_groups(floors, result.placements)}
    assert groups["k5"].placement == "manual" and groups["k5"].site_pin_id == pin.id


def test_neighbour_by_axes_follows_the_pinned_group() -> None:
    under = underground()
    tower = built(corps="5", section=None, order=1, axes=axes_block(*section_axes("5")))
    neighbour = built(
        corps="7",
        section=None,
        order=2,
        axes=axes_block(*section_axes("5", 3000.0, 0.0)),
        shift=(3000.0, 0.0),
    )
    p = ((0.0, 0.0), (20000.0, 0.0))
    q = _points((100000.0, 50000.0), 90.0)
    result, floors = site([under, tower, neighbour], [pin_for(tower, under, p, q)])
    assert result.placements["k5"].placement == "manual"
    follower = result.placements["k7"]
    assert (follower.placement, follower.anchor_key) == ("axes", "k5")
    assert follower.rotation_deg == pytest.approx(90.0)
    # Сосед встал за корпусом 5: не в системе паркинга, а повёрнутым вместе с ним.
    assert floor_of_group(floors, "k7").rotation_deg == pytest.approx(90.0, abs=0.01)


def test_pin_beats_the_placement_by_cores() -> None:
    under = underground()
    tower = with_cores(built(corps="1", section="1", order=1), CORE)
    auto, _ = site([under, tower], [])
    assert auto.placements["k1-s1"].placement == "cores"
    p = ((0.0, 0.0), (20000.0, 0.0))
    q = _points((30000.0, 20000.0), 90.0)
    result, floors = site([under, tower], [pin_for(tower, under, p, q)])
    group = result.placements["k1-s1"]
    assert group.placement == "manual" and group.rotation_deg == pytest.approx(90.0)
    assert floor_of_group(floors, "k1-s1").outline[0] == pytest.approx(q[0], abs=1.0)
    assert result.ignored == ()


def test_pin_can_target_a_group_placed_by_another_pin() -> None:
    under = underground()
    first = built(corps="5", section=None, order=1)
    second = built(corps="6", section=None, order=2)
    to_under = pin_for(
        first, under, ((0.0, 0.0), (20000.0, 0.0)), _points((100000.0, 50000.0), 25.9)
    )
    # Второй корпус привязан к листу первого: точки цели - в кадре вида первого корпуса.
    q = ((8000.0, 1000.0), (8000.0, 21000.0))
    to_first = pin_for(second, first, ((0.0, 0.0), (0.0, 20000.0)), q, minutes=1)
    result, floors = site([under, first, second], [to_first, to_under])
    assert result.placements["k6"].anchor_key == "k5"
    placed_first = floor_of_group(floors, "k5")
    expected = pm.apply_transform(placed_first.rotation_deg, placed_first.offset_mm, q[0])
    assert floor_of_group(floors, "k6").outline[0] == pytest.approx(expected, abs=1.0)


def test_pin_with_unknown_sheet_is_ignored_with_reason() -> None:
    under = underground()
    tower = built(corps="5", section=None, order=1)
    pin = pin_for(tower, under, ((0.0, 0.0), (20000.0, 0.0)), _points((0.0, 0.0), 0.0))
    stranger = built(corps="5", section=None, order=9)
    lost = pin_for(stranger, under, ((0.0, 0.0), (20000.0, 0.0)), _points((0.0, 0.0), 0.0))
    result, _ = site([under, tower], [lost])
    assert [i.pin_id for i in result.ignored] == [lost.id]
    assert "не найден" in result.ignored[0].message
    assert result.placements["k5"].placement == "none"
    assert pin.id not in [i.pin_id for i in result.ignored]


def test_pin_on_the_base_group_is_ignored() -> None:
    under = underground()
    tower = with_cores(built(corps="1", section="1", order=1), CORE)
    pin = pin_for(under, tower, ((0.0, 0.0), (20000.0, 0.0)), _points((0.0, 0.0), 0.0))
    result, _ = site([under, tower], [pin])
    assert "основа площадки" in result.ignored[0].message
    assert result.placements["k1-s1"].placement == "cores"


def test_pin_to_a_group_that_is_not_placed_is_ignored_and_source_is_released() -> None:
    under = underground()
    tower = built(corps="5", section=None, order=1)
    loose = built(corps="8", section=None, order=2)
    pin = pin_for(tower, loose, ((0.0, 0.0), (20000.0, 0.0)), _points((0.0, 0.0), 0.0))
    result, _ = site([under, tower, loose], [pin])
    assert [i.pin_id for i in result.ignored] == [pin.id]
    assert "не поставлено" in result.ignored[0].message
    assert result.placements["k5"].placement == "none"


def test_disagreeing_pins_of_one_group_are_not_applied_and_agreeing_use_the_latest() -> None:
    under = underground()
    first_floor = built(corps="5", section=None, order=1)
    second_floor = built(corps="5", section=None, elevation=BASE + 3000, order=2)
    p = ((0.0, 0.0), (20000.0, 0.0))
    one = pin_for(first_floor, under, p, _points((100000.0, 50000.0), 25.9), minutes=0)
    same = pin_for(second_floor, under, p, _points((100000.0, 50300.0), 25.9), minutes=1)
    other = pin_for(second_floor, under, p, _points((100000.0, 50000.0), 140.0), minutes=2)
    result, _ = site([under, first_floor, second_floor], [one, same])
    assert result.placements["k5"].pin_id == same.id and result.ignored == ()
    result, _ = site([under, first_floor, second_floor], [one, other])
    assert result.placements["k5"].placement == "none"
    assert {i.pin_id for i in result.ignored} == {one.id, other.id}
    assert "расходятся" in result.ignored[0].message


def test_without_pins_the_result_is_the_same() -> None:
    items = [underground(), with_cores(built(corps="1", section="1", order=1), CORE)]
    aligned = b3d.align_floors(items)
    assert b3d.place_site(items, aligned) == b3d.place_site(items, aligned, ())
    assert b3d.place_site_report(items, aligned).ignored == ()


def test_pin_works_when_the_site_has_no_cores_to_choose_a_base() -> None:
    # Ни одного листа с ядрами: основы нет, постановка - запасная; привязка ставит только
    # здания, которые автоматика не поставила, и называет остальные.
    one = built(corps="5", section=None, order=1)
    two = built(corps="6", section=None, order=2)
    pin = pin_for(two, one, ((0.0, 0.0), (20000.0, 0.0)), _points((50000.0, 0.0), 0.0))
    aligned = b3d.align_floors([one, two])
    result = b3d.place_site_report([one, two], aligned, [pin])
    assert result.placements["k6"].placement in {"manual", "axes", "cores", "reference", "none"}
    assert all(i.pin_id == pin.id for i in result.ignored)


def test_build_stack_reports_ignored_pins() -> None:
    under = underground()
    tower = built(corps="5", section=None, order=1)
    pin = pin_for(tower, under, ((0.0, 0.0), (20000.0, 0.0)), _points((100000.0, 50000.0), 25.9))
    stack = build_stack([under, tower], [pin])
    assert [g.placement for g in stack.groups if g.key == "k5"] == ["manual"]
    assert stack.ignored_pins == ()
    lost = pin_for(
        built(corps="5", section=None, order=9),
        under,
        ((0.0, 0.0), (20000.0, 0.0)),
        _points((0.0, 0.0), 0.0),
    )
    assert [i.pin_id for i in build_stack([under, tower], [lost]).ignored_pins] == [lost.id]
