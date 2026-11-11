"""Плита перекрытия как конструкция листа: расчёт, итоги, сборка входа из walls.json (без базы)."""

from __future__ import annotations

from typing import Any

import pytest

from app.contracts.cad_constructions import CadConstructionProps, CadSheetLevelsRead
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import cad_constructions as calc
from app.services import cad_slab, cad_vor
from app.services.cad_floor3d import hole_keys
from tests.test_cad_constructions_calc import construction, document

NO_LEVELS = CadSheetLevelsRead(floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None)
H1 = [[1000.0, 1000.0], [2000.0, 1000.0], [2000.0, 2000.0], [1000.0, 2000.0]]
H2 = [[3000.0, 1000.0], [4000.0, 1000.0], [4000.0, 3000.0], [3000.0, 3000.0]]
SHELL = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]


def extras(*, with_id: bool = False, slab: bool = True) -> WallsFloorExtras:
    raw: dict[str, Any] = {"slab": None}
    if slab:
        raw["slab"] = {"shell": SHELL, "area_mm2": 24_000_000.0, "close_radius_mm": 600.0}
        if with_id:
            raw["slab"] |= {"id": "slab", "kind": "floor_slab"}
    raw["slab_holes"] = [
        {"id": "h1", "shell": H1, "area_mm2": 1_000_000.0, "status": "candidate"},
        {"id": "h2", "shell": H2, "area_mm2": 2_000_000.0, "status": "candidate"},
    ]
    return WallsFloorExtras.model_validate(raw)


def sheet_with_slab(
    decisions: dict[str, bool] | None = None,
    props: dict[str, tuple[CadConstructionProps, bool]] | None = None,
    *,
    levels: CadSheetLevelsRead = NO_LEVELS,
    slab_thickness: int | None = 200,
) -> calc.SheetResult:
    doc = document([construction()])
    doc.heights.slab_thickness_mm = slab_thickness
    doc.heights.slab_status = "assumption" if slab_thickness is not None else "missing"
    slab = cad_slab.slab_input(extras(), decisions or {})
    return calc.compute_sheet(doc, props or {}, levels, None, slab)


def test_slab_input_takes_enabled_holes_and_ignores_unknown_fields() -> None:
    plain, with_id = extras(), extras(with_id=True)
    assert plain.slab is not None and with_id.slab is not None
    assert plain.slab.shell == with_id.slab.shell
    keys = hole_keys(plain)
    slab = cad_slab.slab_input(with_id, {keys[1]: False})
    assert slab is not None and slab.id == "slab"
    assert [area for _shell, area in slab.holes] == [1_000_000.0]
    assert slab.net_area_mm2 == pytest.approx(23_000_000.0)
    # Явное «включено» ничем не отличается от отсутствия решения.
    both = cad_slab.slab_input(plain, {keys[0]: True})
    assert both is not None and len(both.holes) == 2


def test_no_slab_in_file_gives_no_slab_input() -> None:
    assert cad_slab.slab_input(extras(slab=False), {}) is None
    old = WallsFloorExtras.model_validate({})
    assert cad_slab.slab_input(old, {}) is None


def test_slab_is_last_with_net_area_and_volume() -> None:
    keys = hole_keys(extras())
    result = sheet_with_slab({keys[1]: False})
    assert [c.id for c in result.constructions] == ["c1", "slab"]
    slab = result.constructions[-1]
    assert slab.kind == "floor_slab" and slab.source_layers == []
    assert slab.polygon.shell == SHELL and slab.polygon.holes == [H1]
    assert slab.centroid == pytest.approx([3000.0, 2000.0])
    assert slab.bbox == [0.0, 0.0, 6000.0, 4000.0]
    # 24 - 1 (второе отверстие выключено решением) = 23 м2; толщина 200 -> 4,6 м3.
    assert slab.area_plan_m2 == 23.0
    computed = slab.computed
    assert computed.area_m2 == 23.0 and computed.volume_m3 == pytest.approx(4.6)
    assert computed.thickness_mm == 200.0 and computed.sources.thickness == "assumption"
    assert computed.length_m is None and computed.height_mm is None
    assert computed.wall_area_m2 is None and computed.status == "ok"
    assert slab.thickness_nominal_mm == 200.0 and slab.thickness_status == "matched"
    assert slab.material.value is None and slab.material.source is None
    assert result.constructions[0].computed.area_m2 is None
    assert result.summary.total_count == 2
    group = next(t for t in result.totals if t.kind == "floor_slab")
    assert (group.thickness_mm, group.material, group.count) == (200.0, None, 1)
    assert group.area_m2 == 23.0 and group.volume_m3 == pytest.approx(4.6)
    assert group.length_m == 0 and group.wall_area_m2 == 0
    assert next(t for t in result.totals if t.kind == "masonry").area_m2 is None
    assert [t.kind for t in result.totals] == ["masonry", "floor_slab"]


def test_all_holes_enabled_by_default() -> None:
    slab = sheet_with_slab().constructions[-1]
    assert slab.polygon.holes == [H1, H2] and slab.computed.area_m2 == 21.0
    assert slab.computed.volume_m3 == pytest.approx(4.2)


def test_slab_without_thickness_is_checked_and_not_in_totals() -> None:
    result = sheet_with_slab(slab_thickness=None)
    slab = result.constructions[-1]
    assert slab.computed.status == "thickness_check" and slab.computed.warnings == [
        "thickness_check"
    ]
    assert slab.computed.volume_m3 is None and slab.computed.thickness_mm is None
    assert slab.thickness_status == "check" and slab.thickness_measured_mm == 0.0
    assert slab.computed.area_m2 == 21.0
    # Без толщины плиты высоты стен тоже нет (этаж минус плита): итогов нет совсем.
    assert all(t.kind != "floor_slab" for t in result.totals)
    assert result.summary.thickness_check_count == 1 and result.summary.total_count == 2


def test_manual_thickness_and_material_from_props() -> None:
    props = {
        "slab": (
            CadConstructionProps(thickness_override_mm=250, material="monolith_concrete"),
            True,
        )
    }
    result = sheet_with_slab(props=props, slab_thickness=None)
    slab = result.constructions[-1]
    assert slab.accepted is True and slab.props.thickness_override_mm == 250
    assert slab.computed.thickness_mm == 250.0 and slab.computed.sources.thickness == "manual"
    assert slab.computed.volume_m3 == pytest.approx(21.0 * 0.25)
    assert slab.material.value == "monolith_concrete" and slab.material.source == "manual"
    group = next(t for t in result.totals if t.kind == "floor_slab")
    assert (group.thickness_mm, group.material) == (250.0, "monolith_concrete")


def test_sheet_level_thickness_applies_to_the_slab() -> None:
    levels = CadSheetLevelsRead(floor_height_mm=None, slab_thickness_mm=300, door_height_mm=None)
    slab = sheet_with_slab(levels=levels).constructions[-1]
    assert slab.computed.thickness_mm == 300.0 and slab.computed.sources.thickness == "manual"


def test_without_slab_input_the_sheet_is_unchanged() -> None:
    doc = document([construction()])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    assert [c.id for c in result.constructions] == ["c1"] and result.summary.total_count == 1
    assert all(t.kind != "floor_slab" for t in result.totals)


def test_slab_group_key_is_accepted_by_vor() -> None:
    key = cad_vor.group_key("floor_slab", 200.0, "monolith_concrete")
    assert key == "floor_slab|200|monolith_concrete"
    parts = cad_vor.parse_group_key(key)
    assert parts is not None and parts.kind == "floor_slab" and parts.thickness_mm == 200.0
    assert cad_vor.parse_group_key("floor_slab|250|") is not None


def test_slab_group_is_covered_by_the_vor_report() -> None:
    result = sheet_with_slab()
    coverage = cad_vor.build_coverage(
        totals=result.totals,
        constructions=result.constructions,
        linked={},
        thicknesses=[200],
        has_vor=True,
    )
    slab_group = next(g for g in coverage.groups if g.kind == "floor_slab")
    assert slab_group.group_key == "floor_slab|200|" and slab_group.status == "not_in_vor"
    assert "slab" in coverage.not_in_vor_keys
