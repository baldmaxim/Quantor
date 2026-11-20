"""«Здание» по утверждённой модели здания: подгонка этажа к сетке осей, постановка, отметки."""

from __future__ import annotations

import dataclasses
import math
import uuid
from types import SimpleNamespace

import pytest

from app.contracts.cad_building3d import CadBuilding3dFloorRead
from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly as assembly
from app.services import cad_building3d_grid as grid
from app.services import cad_project_levels
from app.services.model_sheets import ModelAxis
from tests.test_cad_building3d import axes_block, built

# Корпус 1 стоит в модели как на своём листе, сдвинут на (500, 700). Корпус 2 повёрнут на 90°
# (листы башни повёрнуты к стилобату): вид → модель = R(90°)·p + (30000, 50000).
K1_VIEW_V = {"1/1": 500.0, "1/2": 6500.0, "1/3": 12500.0}
K1_VIEW_H = {"1/А": 1300.0, "1/Б": 7300.0}
K2_VIEW_V = {"2/1": 0.0, "2/2": 6000.0, "2/3": 12000.0}
K2_VIEW_H = {"2/А": 0.0, "2/Б": 6000.0}


def _model() -> list[ModelAxis]:
    axes = [ModelAxis(k, (x + 500, -5000.0), (x + 500, 20000.0)) for k, x in K1_VIEW_V.items()]
    axes += [ModelAxis(k, (-5000.0, y + 700), (20000.0, y + 700)) for k, y in K1_VIEW_H.items()]
    # вертикальная ось вида x = c → в модели горизонталь y = 50000 + c
    axes += [ModelAxis(k, (0.0, 50000 + c), (40000.0, 50000 + c)) for k, c in K2_VIEW_V.items()]
    # горизонтальная ось вида y = c → в модели вертикаль x = 30000 - c
    axes += [ModelAxis(k, (30000 - c, 40000.0), (30000 - c, 70000.0)) for k, c in K2_VIEW_H.items()]
    return axes


def _floor(corps: str, order: int, v: dict[str, float], h: dict[str, float]) -> b3d.BuiltFloor:
    item = built(
        corps=corps, section=None, order=order, elevation=3000 * order, axes=axes_block(v, h)
    )
    return dataclasses.replace(item, grid=grid.floor_fit(item.axes, _model()))


def test_floor_fit_recovers_rotation_and_offset() -> None:
    k1 = _floor("1", 0, K1_VIEW_V, K1_VIEW_H)
    k2 = _floor("2", 1, K2_VIEW_V, K2_VIEW_H)
    assert k1.grid is not None and k2.grid is not None
    assert k1.grid.rotation_deg == pytest.approx(0.0, abs=1e-6)
    assert k1.grid.apply(0.0, 0.0) == pytest.approx((500.0, 700.0), abs=0.5)
    assert k2.grid.rotation_deg % 360 == pytest.approx(90.0, abs=1e-6)
    assert k2.grid.apply(1000.0, 0.0) == pytest.approx((30000.0, 51000.0), abs=0.5)
    assert set(k2.grid.used) == set(K2_VIEW_V) | set(K2_VIEW_H)


def test_floor_without_axes_of_the_model_has_no_fit() -> None:
    item = built(
        corps="3", section=None, axes=axes_block({"3/1": 0.0, "3/2": 6000.0}, {"3/А": 0.0})
    )
    assert grid.floor_fit(item.axes, _model()) is None
    assert grid.floor_fit(item.axes, []) is None


def _placements(
    aligned: list[CadBuilding3dFloorRead], placed: str, reference: b3d.GroupPlacement
) -> dict[str, b3d.GroupPlacement]:
    out: dict[str, b3d.GroupPlacement] = {}
    for floor in aligned:
        out[floor.group_key] = (
            reference
            if floor.group_key == placed
            else b3d.GroupPlacement("none", (0.0, 0.0), (), None, "нет общих осей")
        )
    return out


def test_unplaced_group_is_placed_by_the_model_grid() -> None:
    items = [_floor("1", i, K1_VIEW_V, K1_VIEW_H) for i in range(3)]
    items.append(_floor("2", 3, K2_VIEW_V, K2_VIEW_H))
    aligned = b3d.align_floors(items)
    k1_key, k2_key = aligned[0].group_key, aligned[3].group_key
    assert k1_key != k2_key
    reference = b3d.GroupPlacement("reference", (0.0, 0.0), (), None, None)
    placements = grid.place_by_grid(items, aligned, _placements(aligned, k1_key, reference), 7)
    assert placements[k1_key] is reference
    k2 = placements[k2_key]
    assert k2.placement == "axes"
    assert "версия 7" in (k2.message or "")
    # объект = вид корпуса 1 = модель − (500, 700): корпус 2 - R(90°)·p + (29500, 49300)
    assert k2.rotation_deg == pytest.approx(90.0, abs=1e-6)
    assert k2.offset_mm == pytest.approx((29500.0, 49300.0), abs=1.0)
    placed = b3d.apply_placements(aligned, placements)
    corner = placed[3].offset_mm
    assert corner == pytest.approx((29500.0, 49300.0), abs=1.0)


def test_site_without_enough_placed_floors_on_the_grid_is_left_alone() -> None:
    items = [_floor("1", 0, K1_VIEW_V, K1_VIEW_H), _floor("2", 1, K2_VIEW_V, K2_VIEW_H)]
    aligned = b3d.align_floors(items)
    reference = b3d.GroupPlacement("reference", (0.0, 0.0), (), None, None)
    before = _placements(aligned, aligned[0].group_key, reference)
    after = grid.place_by_grid(items, aligned, before, 7)
    assert after[aligned[1].group_key].placement == "none"


def test_placed_floors_that_disagree_give_no_grid() -> None:
    items = [_floor("1", i, K1_VIEW_V, K1_VIEW_H) for i in range(2)]
    items.append(_floor("2", 2, K2_VIEW_V, K2_VIEW_H))
    aligned = b3d.align_floors(items)
    k1_key = aligned[0].group_key
    # корпус 1 поставлен «не туда» относительно сетки по одному этажу: второй этаж сдвинут на 5 м
    shifted = [
        f.model_copy(update={"offset_mm": (5000.0, 0.0)}) if i == 1 else f
        for i, f in enumerate(aligned)
    ]
    reference = b3d.GroupPlacement("reference", (0.0, 0.0), (), None, None)
    after = grid.place_by_grid(items, shifted, _placements(shifted, k1_key, reference), 7)
    assert after[aligned[2].group_key].placement == "none"


def test_no_fits_returns_placements_unchanged() -> None:
    items = [built(corps="1", section=None, order=0)]
    aligned = b3d.align_floors(items)
    placements = {aligned[0].group_key: b3d.GroupPlacement("reference", (0.0, 0.0), (), None, None)}
    assert grid.place_by_grid(items, aligned, placements, 7) is placements


def test_build_stack_without_model_is_unchanged() -> None:
    items = [_floor("1", 0, K1_VIEW_V, K1_VIEW_H), _floor("2", 1, K2_VIEW_V, K2_VIEW_H)]
    plain = [dataclasses.replace(i, grid=None) for i in items]
    assert assembly.build_stack(plain).groups == assembly.build_stack(items).groups


def test_model_levels_by_corps_and_floor() -> None:
    storeys = [
        SimpleNamespace(building_name="Корпус 1", name="5 этаж", elevation_mm=21900.0),
        SimpleNamespace(
            building_name="Корпус 1", name="Техпространство +102.750", elevation_mm=102750.0
        ),
        SimpleNamespace(building_name="Стилобат", name="2 этаж", elevation_mm=7200.0),
        SimpleNamespace(building_name="Корпус 12", name="-1 этаж", elevation_mm=-3300.0),
        SimpleNamespace(building_name="Корпус 1", name="5 этаж", elevation_mm=99999.0),
    ]
    levels = grid.model_levels(storeys, 7)
    assert set(levels) == {("1", 5), ("12", -1)}
    assert levels[("1", 5)].z_mm == 21900
    assert levels[("1", 5)].source == "модели здания"
    kr = {("1", 5): cad_project_levels.ProjectLevel(21800, "КР2.ГЧ.К1 · лист 5")}
    ref = grid.ModelReference(version_id=uuid.uuid4(), number=7, axes=(), levels=levels)
    merged = grid.merged_levels(kr, ref)
    assert merged[("1", 5)].z_mm == 21800  # КР первыми
    assert merged[("12", -1)].z_mm == -3300
    assert grid.merged_levels(kr, None) is kr
    assert cad_project_levels.ProjectLevel(1, "x").source == "схеме КР"


def test_floor_fit_takes_oblique_axes() -> None:
    """Корпус повёрнут на плане (стилобат ЖД4): вертикалей и горизонталей нет, оси под углом."""
    model = _model()
    # вид = модель корпуса 1, повёрнутая на 7° вокруг начала и сдвинутая; оси вида - под углом
    th = math.radians(7.0)
    c, s = math.cos(th), math.sin(th)

    def to_view(p: tuple[float, float]) -> tuple[float, float]:
        x, y = p[0] - 500.0, p[1] - 700.0
        return (c * x + s * y, -s * x + c * y)

    oblique = []
    for m in model:
        if not m.tag.startswith("1/"):
            continue
        a, b = to_view(m.p0), to_view(m.p1)
        length = math.dist(a, b)
        oblique.append(b3d.ObliqueAxis(m.tag, a, ((b[0] - a[0]) / length, (b[1] - a[1]) / length)))
    axes = b3d.FloorAxes({}, {}, "найдены только оси под углом", tuple(oblique))
    fit = grid.floor_fit(axes, model)
    assert fit is not None
    assert fit.rotation_deg % 360 == pytest.approx(7.0, abs=1e-3)
    back = fit.apply(*to_view((1500.0, 2700.0)))
    assert back == pytest.approx((1500.0, 2700.0), abs=1.0)


def test_unaligned_floor_of_a_placed_group_is_put_by_the_grid() -> None:
    items = [_floor("1", i, K1_VIEW_V, K1_VIEW_H) for i in range(3)]
    aligned = b3d.align_floors(items)
    key = aligned[0].group_key
    reference = b3d.GroupPlacement("reference", (0.0, 0.0), (), None, None)
    placements = {key: reference}
    right = aligned[2]
    wrong = b3d._shifted(right, 5000.0, -3000.0).model_copy(update={"alignment": "none"})
    floors = [aligned[0], aligned[1], wrong]
    out_placements, out = grid.place_and_align_by_grid(items, floors, placements, 8)
    assert out_placements[key] is reference
    assert out[2].alignment == "axes"
    assert "версия 8" in (out[2].alignment_message or "")
    assert out[2].offset_mm == pytest.approx(right.offset_mm, abs=1.0)
    assert out[0] is aligned[0]


def test_unaligned_stylobate_floor_without_fit_gets_its_own_group() -> None:
    items = [_floor("1", i, K1_VIEW_V, K1_VIEW_H) for i in range(3)]
    stray = dataclasses.replace(built(corps=None, section=None, order=3), grid=None)
    items.append(stray)
    aligned = [f.model_copy(update={"group_key": "none"}) for f in b3d.align_floors(items)]
    aligned[3] = aligned[3].model_copy(update={"alignment": "none"})
    placements = {"none": b3d.GroupPlacement("reference", (0.0, 0.0), (), None, None)}
    out = grid.split_unaligned_unnamed(items, aligned)
    _placements, out2 = grid.place_and_align_by_grid(items, aligned, placements, 8)
    assert out2[3].group_key == "none"  # постановка по сетке этаж без подгонки не трогает
    assert out[3].group_key.startswith("none-free-")
    assert out[3].group_label.startswith("Корпус не указан · ")
    assert all(f.group_key == "none" for f in out[:3])
