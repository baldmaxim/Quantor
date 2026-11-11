"""Модель этажа для 3D-вида (ADR-0039): чистая сборка без базы и хранилища.

Ожидаемые числа выписаны руками из правил модуля `cad_floor3d`: отметка этажа — верх плиты,
плита — `отметка - t`, стена — до `отметка + (высота этажа - t)`, перемычка — от
`отметка + высота двери` до верха стены.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.cad_constructions import CadConstructionProps, CadSheetLevelsRead, WallsDocument
from app.contracts.cad_floor3d import CadProjectLevelsWrite, WallsFloorExtras
from app.services import cad_floor3d as f3d
from app.services.cad_constructions import ProjectSlab

BASE = 47600
SQUARE_1M2 = [[1000.0, 1000.0], [2000.0, 1000.0], [2000.0, 2000.0], [1000.0, 2000.0]]
SQUARE_2M2 = [[3000.0, 1000.0], [4000.0, 1000.0], [4000.0, 3000.0], [3000.0, 3000.0]]
LINTEL = [[500.0, 0.0], [1500.0, 0.0], [1500.0, 200.0], [500.0, 200.0]]  # центроид (1000, 100)
NO_LEVELS = CadSheetLevelsRead(
    floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None, floor_elevation_mm=None
)


def heights(**patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "floor_elevation_mm": BASE,
        "floor_height_mm": 3000,
        "elevation_status": "observed",
        "height_status": "derived",
        "evidence": "стр. 1",
        "message": None,
        "slab_thickness_mm": 200,
        "slab_status": "assumption",
        "door_height_mm": 2100,
        "door_height_status": "assumption",
    }
    body.update(patch)
    return body


def raw_document(**heights_patch: Any) -> dict[str, Any]:
    wall = {
        "id": "aaaaaaaaaaaa",
        "kind": "masonry",
        "source_layers": ["01"],
        "polygon": {
            "shell": [[0.0, 0.0], [5000.0, 0.0], [5000.0, 200.0], [0.0, 200.0]],
            "holes": [],
        },
        "area_plan_mm2": 1_000_000.0,
        "thickness_measured_mm": 200.0,
        "thickness_nominal_mm": 200.0,
        "thickness_status": "matched",
        "length_axis_mm": 5000.0,
        "centroid": [2500.0, 100.0],
        "bbox": [0.0, 0.0, 5000.0, 200.0],
    }
    pylon = {**wall, "id": "bbbbbbbbbbbb", "kind": "monolith_pylon", "thickness_nominal_mm": None}
    door = {
        "id": "door00000001",
        "kind": "door",
        "status": "ok",
        "host_id": "aaaaaaaaaaaa",
        "adjacent_ids": ["aaaaaaaaaaaa"],
        "width_mm": 1000.0,
        "width_source": "block",
        "thickness_mm": 200.0,
        "block_name": None,
        "handle": None,
        "center": [1000.0, 100.0],
    }
    return {
        "schema": "quantor.cad_walls.v1",
        "generator": "cad_walls.v1.1",
        "params_version": "v1",
        "params_sha256": "a" * 64,
        "dxf_sha256": "b" * 64,
        "units": "mm",
        "heights": heights(**heights_patch),
        "constructions": [wall, pylon],
        "openings": [door],
        "checks": {"warnings": []},
    }


def raw_extras(*, lintel: list[list[float]] | None = LINTEL) -> dict[str, Any]:
    return {
        "slab": {
            "shell": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]],
            "area_mm2": 24_000_000.0,
            "close_radius_mm": 600.0,
        },
        "slab_holes": [
            {
                "id": "h1",
                "shell": SQUARE_1M2,
                "area_mm2": 1_000_000.0,
                "status": "candidate",
                "reason": "enclosed_no_door",
            },
            {
                "id": "h2",
                "shell": SQUARE_2M2,
                "area_mm2": 2_000_000.0,
                "status": "candidate",
                "reason": "enclosed_no_door",
            },
        ],
        "openings": [{"id": "door00000001", "direction": [1.0, 0.0], "lintel": lintel}],
    }


def build(
    *,
    heights_patch: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
    overrides: CadSheetLevelsRead = NO_LEVELS,
    project_slab: ProjectSlab | None = None,
    decisions: dict[str, bool] | None = None,
    zones: list[f3d.DoorZoneMm] | None = None,
    props: dict[str, tuple[CadConstructionProps, bool]] | None = None,
    outdated: bool = False,
) -> Any:
    document = WallsDocument.model_validate(raw_document(**(heights_patch or {})))
    parsed = WallsFloorExtras.model_validate({} if outdated else (extras or raw_extras()))
    return f3d.build_floor3d(
        document,
        parsed,
        props_by_key=props or {},
        overrides=overrides,
        project_slab=project_slab,
        hole_decisions=decisions or {},
        door_zones=zones or [],
    )


def codes(model: Any) -> list[str]:
    return [w.code for w in model.warnings]


# ------------------------------------------------------------------ база и отметка


def test_base_is_the_floor_elevation_and_slab_hangs_below_it() -> None:
    model = build()
    assert model.units == "mm" and model.generator == "cad_walls.v1.1"
    assert model.base_z_mm == BASE and model.elevation_known is True
    assert model.heights.floor_elevation_source == "observed"
    assert model.slab is not None
    assert (model.slab.z_top_mm, model.slab.z_bottom_mm) == (BASE, BASE - 200)
    assert model.slab.area_m2 == 24.0
    assert model.bbox == [0.0, 0.0, 6000.0, 4000.0]
    assert codes(model) == []


def test_missing_elevation_builds_from_zero_and_says_so() -> None:
    model = build(heights_patch={"floor_elevation_mm": None, "elevation_status": "missing"})
    assert model.base_z_mm == 0 and model.elevation_known is False
    assert model.heights.floor_elevation_mm is None
    assert model.slab is not None and (model.slab.z_top_mm, model.slab.z_bottom_mm) == (0, -200)
    assert all(w.z_bottom_mm == 0 for w in model.walls)


def test_sheet_elevation_override_beats_walls_json() -> None:
    levels = CadSheetLevelsRead(
        floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None, floor_elevation_mm=50000
    )
    model = build(overrides=levels)
    assert model.base_z_mm == 50000 and model.elevation_known is True
    assert model.heights.floor_elevation_source == "manual"
    assert model.heights.floor_elevation_mm == 50000


# ------------------------------------------------------------------ толщина плиты


def test_slab_thickness_priority_sheet_then_project_then_walls_json() -> None:
    walls_json = build()
    assert walls_json.slab is not None and walls_json.slab.z_bottom_mm == BASE - 200
    assert walls_json.heights.slab_thickness.source == "assumption"
    assert walls_json.heights.slab_thickness_sheet_ref is None

    project = build(project_slab=ProjectSlab(250, "АР1.1 л. 45, разрез 4-4"))
    assert project.slab is not None and project.slab.z_bottom_mm == BASE - 250
    assert project.heights.slab_thickness.source == "manual"
    assert project.heights.slab_thickness.default_mm == 200
    assert project.heights.slab_thickness_sheet_ref == "АР1.1 л. 45, разрез 4-4"
    # Высота стены = высота этажа - толщина плиты проекта.
    assert project.heights.wall_height_mm == 3000 - 250
    assert all(w.z_top_mm == BASE + 2750 for w in project.walls)

    sheet = build(
        project_slab=ProjectSlab(250, "АР1.1"),
        overrides=CadSheetLevelsRead(
            floor_height_mm=None,
            slab_thickness_mm=300,
            door_height_mm=None,
            floor_elevation_mm=None,
        ),
    )
    assert sheet.slab is not None and sheet.slab.z_bottom_mm == BASE - 300
    assert sheet.heights.slab_thickness_sheet_ref is None


def test_missing_slab_thickness_leaves_the_bottom_undefined() -> None:
    model = build(heights_patch={"slab_thickness_mm": None, "slab_status": "missing"})
    assert model.slab is not None and model.slab.z_bottom_mm is None
    assert "slab_thickness_missing" in codes(model)


# ------------------------------------------------------------------ стены и перемычки


def test_walls_rise_from_base_by_floor_height_minus_slab() -> None:
    model = build()
    assert [w.construction_key for w in model.walls] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    first, second = model.walls
    assert (first.kind, first.family, first.thickness_nominal_mm) == ("masonry", "masonry", 200.0)
    assert (second.kind, second.family, second.thickness_nominal_mm) == (
        "monolith_pylon",
        "monolith",
        None,
    )
    assert (first.z_bottom_mm, first.z_top_mm) == (BASE, BASE + 2800)
    assert first.shell[0] == [0.0, 0.0] and first.holes == []


def test_wall_height_override_of_a_construction_is_honoured() -> None:
    props = {"aaaaaaaaaaaa": (CadConstructionProps(height_override_mm=2500), True)}
    model = build(props=props)
    assert model.walls[0].z_top_mm == BASE + 2500 and model.walls[1].z_top_mm == BASE + 2800
    # Перемычка над дверью стены aaaa кончается под её верхом.
    assert model.lintels[0].z_top_mm == BASE + 2500


def test_missing_floor_height_gives_null_top_and_warning_not_zero() -> None:
    model = build(heights_patch={"floor_height_mm": None, "height_status": "missing"})
    assert all(w.z_top_mm is None for w in model.walls)
    assert model.lintels == []
    assert codes(model).count("wall_height_missing") == 1


def test_lintel_runs_from_door_height_to_wall_top_with_default_source() -> None:
    model = build()
    assert len(model.lintels) == 1
    lintel = model.lintels[0]
    assert (lintel.opening_id, lintel.kind, lintel.shell) == ("door00000001", "door", LINTEL)
    assert (lintel.z_bottom_mm, lintel.z_top_mm) == (BASE + 2100, BASE + 2800)
    assert (lintel.door_height_mm, lintel.door_height_source) == (2100, "assumption")


def test_door_height_from_the_zone_that_contains_the_lintel_midpoint() -> None:
    near = f3d.DoorZoneMm((500.0, 100.0), (1500.0, 100.0), 2300)
    far = f3d.DoorZoneMm((9000.0, 9000.0), (10000.0, 9000.0), 1800)
    model = build(zones=[far, near])
    lintel = model.lintels[0]
    assert (lintel.door_height_mm, lintel.door_height_source) == (2300, "manual")
    assert (lintel.z_bottom_mm, lintel.z_top_mm) == (BASE + 2300, BASE + 2800)
    # Зона вдали от середины перемычки не подходит: действует высота двери листа.
    unmatched = build(zones=[far])
    assert unmatched.lintels[0].door_height_mm == 2100
    assert unmatched.lintels[0].door_height_source == "assumption"


def test_nearest_zone_wins_when_two_are_in_tolerance() -> None:
    close = f3d.DoorZoneMm((500.0, 120.0), (1500.0, 120.0), 2200)
    farther = f3d.DoorZoneMm((500.0, 350.0), (1500.0, 350.0), 2400)
    assert build(zones=[farther, close]).lintels[0].door_height_mm == 2200


def test_lintel_is_dropped_when_door_reaches_or_exceeds_wall_top() -> None:
    reaching = f3d.DoorZoneMm((500.0, 100.0), (1500.0, 100.0), 2800)
    assert build(zones=[reaching]).lintels == []
    levels = CadSheetLevelsRead(
        floor_height_mm=None, slab_thickness_mm=None, door_height_mm=3200, floor_elevation_mm=None
    )
    assert build(overrides=levels).lintels == []


def test_missing_door_height_skips_lintels_with_warning() -> None:
    model = build(heights_patch={"door_height_mm": None, "door_height_status": "missing"})
    assert model.lintels == []
    assert "door_height_missing" in codes(model)


def test_opening_without_lintel_contour_is_reported() -> None:
    model = build(extras=raw_extras(lintel=None))
    assert model.lintels == [] and "lintel_missing" in codes(model)


# ------------------------------------------------------------------ старый walls.json


def test_old_walls_json_has_no_slab_or_lintels_and_warns() -> None:
    model = build(outdated=True)
    assert model.slab is None and model.slab_holes == [] and model.lintels == []
    assert codes(model) == ["walls_outdated"]
    # Стены из прежнего формата по-прежнему показываются.
    assert len(model.walls) == 2 and model.walls[0].z_top_mm == BASE + 2800
    assert model.bbox == [0.0, 0.0, 5000.0, 200.0]


def test_new_walls_json_without_a_slab_is_not_outdated() -> None:
    extras = {"slab": None, "slab_holes": [], "openings": []}
    model = build(extras=extras)
    assert "walls_outdated" not in codes(model) and "slab_missing" in codes(model)


# ------------------------------------------------------------------ отверстия


def test_hole_key_is_stable_and_follows_geometry_not_order_or_id() -> None:
    key = f3d.hole_key(SQUARE_1M2, 1_000_000.0)
    assert len(key) == 12 and all(c in "0123456789abcdef" for c in key)
    # Другое начало обхода кольца и дрожание в пределах шага 10 мм и 0,01 м2 ключ не меняют.
    shifted = SQUARE_1M2[2:] + SQUARE_1M2[:2]
    assert f3d.hole_key(shifted, 1_000_000.0) == key
    jitter = [[x + 2.0, y - 3.0] for x, y in SQUARE_1M2]
    assert f3d.hole_key(jitter, 1_000_004.0) == key
    # Другое место или другая площадь — другой ключ.
    assert f3d.hole_key(SQUARE_2M2, 1_000_000.0) != key
    assert f3d.hole_key(SQUARE_1M2, 1_100_000.0) != key

    swapped = raw_extras()
    swapped["slab_holes"] = list(reversed(swapped["slab_holes"]))
    swapped["slab_holes"][0]["id"], swapped["slab_holes"][1]["id"] = "h9", "h8"
    keys = {h.key for h in build(extras=swapped).slab_holes}
    assert keys == {h.key for h in build().slab_holes}


def test_ring_centroid_is_area_weighted() -> None:
    assert f3d.ring_centroid(SQUARE_1M2) == pytest.approx((1500.0, 1500.0))
    # Г-образная фигура: вершинное среднее лежало бы иначе.
    ell = [[0, 0], [3000, 0], [3000, 1000], [1000, 1000], [1000, 3000], [0, 3000]]
    assert f3d.ring_centroid(ell) == pytest.approx((1100.0, 1100.0))


def test_hole_state_follows_the_human_decision() -> None:
    first, second = (h.key for h in build().slab_holes)
    model = build(decisions={first: True, second: False})
    states = {h.key: h.state for h in model.slab_holes}
    assert states == {first: "enabled", second: "disabled"}
    undecided = build()
    assert {h.state for h in undecided.slab_holes} == {"candidate"}
    assert [h.area_m2 for h in undecided.slab_holes] == [1.0, 2.0]
    assert f3d.hole_keys(WallsFloorExtras.model_validate(raw_extras())) == [
        h.key for h in undecided.slab_holes
    ]


# ------------------------------------------------------------------ зоны двери


def test_zone_points_are_converted_through_the_view_frame() -> None:
    # Кадр: pt = origin + (x_mm, -y_mm) / mm_per_pt; нормализация — по размеру страницы в pt.
    factor, origin = 35.0, (10.0, 20.0)
    width, height = 1000.0, 800.0
    x_mm, y_mm = 700.0, 1400.0
    pt = (origin[0] + x_mm / factor, origin[1] - y_mm / factor)
    point = [pt[0] / width, pt[1] / height]
    zones = f3d.door_zones_to_mm(
        [f3d.DoorZoneNormalized([point, point], 2050), f3d.DoorZoneNormalized([point], 2000)],
        page_width_pt=width,
        page_height_pt=height,
        origin_pt=origin,
        mm_per_pdf_point=factor,
    )
    assert len(zones) == 1  # зона не из двух точек пропущена
    assert zones[0].a == pytest.approx((x_mm, y_mm)) and zones[0].height_mm == 2050


# ------------------------------------------------------------------ ввод уровня проекта


def test_project_levels_write_requires_the_section_sheet() -> None:
    assert CadProjectLevelsWrite(slab_thickness_mm=None).slab_source_ref is None
    ok = CadProjectLevelsWrite(slab_thickness_mm=220, slab_source_ref=" АР1.1 л. 45 ")
    assert ok.slab_source_ref == "АР1.1 л. 45"
    for bad in (
        {"slab_thickness_mm": 220},
        {"slab_thickness_mm": 220, "slab_source_ref": "   "},
        {"slab_thickness_mm": 99, "slab_source_ref": "x"},
        {"slab_thickness_mm": 1001, "slab_source_ref": "x"},
        {"slab_source_ref": "x" * 201},
        {"slab_thickness_mm": 220, "slab_source_ref": "x", "extra": 1},
    ):
        with pytest.raises(ValidationError):
            CadProjectLevelsWrite.model_validate(bad)


# ------------------------------------------------------------------ полотна дверей (cad_walls v1.4)

LEAF = [[500.0, 80.0], [1500.0, 80.0], [1500.0, 120.0], [500.0, 120.0]]


def test_door_leaf_runs_from_floor_to_door_height() -> None:
    extras = raw_extras()
    extras["openings"][0]["leaf"] = LEAF
    model = build(extras=extras)
    (door,) = model.doors
    assert (door.opening_id, door.shell) == ("door00000001", LEAF)
    assert (door.z_bottom_mm, door.z_top_mm) == (BASE, BASE + 2100)
    assert (door.door_height_mm, door.door_height_source) == (2100, "assumption")
    # Перемычка начинается там, где кончается полотно.
    assert model.lintels[0].z_bottom_mm == door.z_top_mm


def test_door_leaf_follows_zone_height() -> None:
    extras = raw_extras()
    extras["openings"][0]["leaf"] = LEAF
    near = f3d.DoorZoneMm((500.0, 100.0), (1500.0, 100.0), 2300)
    model = build(extras=extras, zones=[near])
    assert model.doors[0].z_top_mm == BASE + 2300
    assert model.doors[0].door_height_source == "manual"


def test_no_leaf_in_walls_gives_no_doors() -> None:
    assert build().doors == []


def test_door_without_gap_has_no_lintel_or_leaf_and_warning_is_passed() -> None:
    raw = raw_document()
    raw["openings"][0]["status"] = "no_data"
    raw["checks"]["warnings"] = [
        {"code": "door_without_gap", "message": "дверь door00000001: разрыв стены не найден"},
        {"code": "slab_missing", "message": "посторонний код не переносится"},
    ]
    extras = raw_extras(lintel=None)
    model = f3d.build_floor3d(
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(extras),
        props_by_key={},
        overrides=NO_LEVELS,
        project_slab=None,
        hole_decisions={},
        door_zones=[],
    )
    assert model.lintels == [] and model.doors == []
    assert codes(model) == ["door_without_gap"]


def test_room_zones_use_the_same_frame_as_door_zones() -> None:
    frame = {
        "page_width_pt": 1000.0,
        "page_height_pt": 500.0,
        "origin_pt": (100.0, 50.0),
        "mm_per_pdf_point": 10.0,
    }
    (room,) = f3d.room_zones_to_mm(
        [f3d.RoomZoneNormalized("room_apartment", [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4]])], **frame
    )
    (door,) = f3d.door_zones_to_mm(
        [f3d.DoorZoneNormalized([[0.2, 0.2], [0.4, 0.2]], 2100)], **frame
    )
    assert room.kind == "room_apartment"
    assert room.shell[:2] == [door.a, door.b] == [(1000.0, -500.0), (3000.0, -500.0)]
    # Контур короче трёх точек зоной помещения не считается.
    assert (
        f3d.room_zones_to_mm(
            [f3d.RoomZoneNormalized("room_mop", [[0.1, 0.1], [0.2, 0.2]])], **frame
        )
        == []
    )


# ------------------------------------------------------------------ заголовок плана v1.5


def test_model_carries_plan_title_from_walls_json() -> None:
    title = {"corps": "9", "section": "3", "floors": [15], "text": "Корпус 9. Секция 3. План 15"}
    model = build(heights_patch={"title": title})
    assert model.title is not None
    assert (model.title.corps, model.title.section, model.title.floors) == ("9", "3", ["15"])


def test_model_without_plan_title_has_none() -> None:
    assert build().title is None
    assert build(heights_patch={"title": None}).title is None
