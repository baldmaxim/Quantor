"""Общий вид здания для 3D: чистая сборка этажей без базы и хранилища."""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest

from app.contracts.cad_building3d import CadBuilding3dFloorRead
from app.contracts.cad_constructions import CadSheetLevelsRead, WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import cad_building3d as b3d
from app.services.cad_constructions import ProjectSlab
from tests.test_cad_floor3d import BASE, NO_LEVELS, heights, raw_document, raw_extras


def sheet(
    *, overrides: CadSheetLevelsRead = NO_LEVELS, order: tuple[float, float, int, int] | None = None
) -> b3d.SheetRef:
    return b3d.SheetRef(
        job_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page_index=(order or (0.0, 0.0, 0, 1))[2],
        view=1,
        label="АР · лист 1",
        order=order or (0.0, 0.0, 0, 1),
        overrides=overrides,
        walls_key="k",
    )


def circle(count: int, radius: float = 10000.0) -> list[list[float]]:
    return [
        [radius * math.cos(2 * math.pi * i / count), radius * math.sin(2 * math.pi * i / count)]
        for i in range(count)
    ]


def floor_of(raw: dict[str, Any], extras: dict[str, Any] | None) -> CadBuilding3dFloorRead:
    document = WallsDocument.model_validate(raw)
    parsed = WallsFloorExtras.model_validate({} if extras is None else extras)
    floor, _warnings = b3d.build_floor(sheet(), document, parsed, None)
    return floor


# ------------------------------------------------------------------ упрощение контура


def test_small_ring_is_kept_and_closing_point_is_dropped() -> None:
    ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0], [0.0, 0.0]]
    assert b3d.simplify_ring(ring) == [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]


def test_big_ring_is_simplified_to_at_most_200_points_within_original_points() -> None:
    ring = circle(5000)
    simplified = b3d.simplify_ring(ring)
    assert 3 <= len(simplified) <= b3d.MAX_OUTLINE_POINTS
    originals = {(x, y) for x, y in ring}
    assert all((x, y) in originals for x, y in simplified)
    box = b3d.bbox_of([simplified])
    assert box is not None and box[2] == pytest.approx(10000.0, abs=50.0)


def test_noisy_ring_still_fits_the_limit() -> None:
    ring = [[x + (i % 7) * 3.0, y + (i % 5) * 3.0] for i, (x, y) in enumerate(circle(3000))]
    assert len(b3d.simplify_ring(ring, 50)) <= 50


def test_collinear_points_collapse_to_corners() -> None:
    ring: list[list[float]] = []
    for i in range(300):
        ring.append([float(i * 10), 0.0])
    for i in range(300):
        ring.append([2990.0, float(i * 10)])
    for i in range(300):
        ring.append([2990.0 - i * 10, 2990.0])
    for i in range(300):
        ring.append([0.0, 2990.0 - i * 10])
    simplified = b3d.simplify_ring(ring)
    assert len(simplified) <= b3d.MAX_OUTLINE_POINTS
    assert b3d.bbox_of([simplified]) == [0.0, 0.0, 2990.0, 2990.0]


# ------------------------------------------------------------------ этаж


def test_floor_takes_slab_outline_and_heights() -> None:
    floor = floor_of(raw_document(), raw_extras())
    assert floor.outline_source == "slab"
    assert floor.outline == [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]
    assert (floor.elevation_known, floor.base_z_mm) == (True, BASE)
    assert (floor.floor_height_mm, floor.floor_height_known) == (3000, True)
    assert (floor.slab_thickness_mm, floor.slab_thickness_known) == (200, True)
    assert floor.bbox == [0.0, 0.0, 6000.0, 4000.0]


def test_floor_without_slab_uses_wall_bbox_rectangle() -> None:
    floor = floor_of(raw_document(), {"slab": None, "slab_holes": [], "openings": []})
    assert floor.outline_source == "bbox"
    assert floor.outline == [[0.0, 0.0], [5000.0, 0.0], [5000.0, 200.0], [0.0, 200.0]]


def test_outdated_walls_file_also_falls_back_to_bbox() -> None:
    assert floor_of(raw_document(), None).outline_source == "bbox"


def test_empty_sheet_without_slab_and_walls_is_rejected() -> None:
    raw = raw_document()
    raw["constructions"] = []
    with pytest.raises(ValueError, match="нет ни плиты"):
        floor_of(raw, None)


def test_unknown_heights_use_drawing_defaults_and_are_flagged() -> None:
    raw = raw_document(floor_elevation_mm=None, floor_height_mm=None, slab_thickness_mm=None)
    document = WallsDocument.model_validate(raw)
    floor, warnings = b3d.build_floor(
        sheet(), document, WallsFloorExtras.model_validate(raw_extras()), None
    )
    assert (floor.elevation_known, floor.base_z_mm) == (False, 0)
    assert (floor.floor_height_mm, floor.floor_height_known) == (3000, False)
    assert (floor.slab_thickness_mm, floor.slab_thickness_known) == (200, False)
    assert {w.code for w in warnings} == {"floor_height_default", "slab_thickness_default"}


def test_overrides_and_project_slab_follow_effective_levels() -> None:
    document = WallsDocument.model_validate(raw_document())
    extras = WallsFloorExtras.model_validate(raw_extras())
    floor, _ = b3d.build_floor(sheet(), document, extras, ProjectSlab(250, "АР1.1 л. 45"))
    assert floor.slab_thickness_mm == 250
    levels = CadSheetLevelsRead(
        floor_height_mm=3300, slab_thickness_mm=300, door_height_mm=None, floor_elevation_mm=9000
    )
    floor, _ = b3d.build_floor(sheet(overrides=levels), document, extras, ProjectSlab(250, None))
    assert (floor.floor_height_mm, floor.slab_thickness_mm, floor.base_z_mm) == (3300, 300, 9000)


def test_floors_are_sorted_known_by_elevation_then_unknown_by_order() -> None:
    def make(elevation: int | None, order: tuple[float, float, int, int]) -> Any:
        raw = raw_document(**({} if elevation is not None else {"floor_elevation_mm": None}))
        if elevation is not None:
            raw["heights"] = heights(floor_elevation_mm=elevation)
        document = WallsDocument.model_validate(raw)
        floor, _ = b3d.build_floor(
            sheet(order=order), document, WallsFloorExtras.model_validate(raw_extras()), None
        )
        return floor, order

    items = [
        make(None, (0.0, 0.0, 5, 1)),
        make(9000, (0.0, 0.0, 2, 1)),
        make(None, (0.0, 0.0, 3, 1)),
        make(3000, (0.0, 0.0, 4, 1)),
    ]
    ordered = b3d.sort_floors(items)
    assert [(f.elevation_known, f.base_z_mm) for f in ordered] == [
        (True, 3000),
        (True, 9000),
        (False, 0),
        (False, 0),
    ]
    assert [f.page_index for f in ordered] == [4, 2, 3, 5]


def test_floor_label_is_floor_title_when_plan_title_is_known() -> None:
    title = {"corps": "9", "section": "3", "floors": [14], "text": "План 14 этажа"}
    with_title = floor_of(raw_document(title=title), None)
    assert with_title.label == "К9 · С3 · 14 эт."
    assert floor_of(raw_document(), None).label == "АР · лист 1"
