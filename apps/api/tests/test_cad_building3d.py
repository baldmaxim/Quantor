"""Общий вид здания для 3D: чистая сборка этажей без базы и хранилища."""

from __future__ import annotations

import math
import uuid
from typing import Any

import pytest

from app.contracts.cad import CadFrameRead
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


# ------------------------------------------------------------------ здания и совмещение по осям

# Кадр: начало в (100, 500) pt, 2 мм на точку.
FRAME = CadFrameRead(
    confirmed=True, reason=None, units="mm", origin_pt=(100.0, 500.0), mm_per_pdf_point=2.0
)
REF_X = {"3.1": 1000.0, "3.2": 5000.0, "3.3": 9000.0}
REF_Y = {"А": 2000.0, "Б": 4000.0}


def axes_block(
    vertical: dict[str, float], horizontal: dict[str, float], frame: CadFrameRead = FRAME
) -> dict[str, Any]:
    """Блок `axes` walls.json: координаты мм DXF переводятся в pt по кадру."""
    assert frame.origin_pt is not None and frame.mm_per_pdf_point is not None
    ox, oy = frame.origin_pt
    s = frame.mm_per_pdf_point
    items = [
        {"label": k, "orient": "vertical", "pos_pt": ox + v / s, "bubbles_pt": []}
        for k, v in vertical.items()
    ] + [
        {"label": k, "orient": "horizontal", "pos_pt": oy - v / s, "bubbles_pt": []}
        for k, v in horizontal.items()
    ]
    return {
        "status": "found",
        "message": None,
        "diameter_pt": 12.0,
        "items": items,
        "conflicts": [],
        "rejected": 0,
    }


def built(
    *,
    corps: str | None = "9",
    section: str | None = "3",
    elevation: int = BASE,
    order: int = 0,
    axes: dict[str, Any] | None = None,
    frame: CadFrameRead = FRAME,
    shift: tuple[float, float] = (0.0, 0.0),
) -> b3d.BuiltFloor:
    """Этаж из walls.json с заголовком плана и (необязательно) осями; `shift` сдвигает DXF."""
    title = {"corps": corps, "section": section, "floors": [1], "text": None}
    raw = raw_document(title=title, floor_elevation_mm=elevation)
    raw["heights"] = heights(title=title, floor_elevation_mm=elevation)
    if axes is not None:
        raw["axes"] = axes
    extras = raw_extras()
    dx, dy = shift
    extras["slab"]["shell"] = [[x + dx, y + dy] for x, y in extras["slab"]["shell"]]
    for construction in raw["constructions"]:
        shell = construction["polygon"]["shell"]
        construction["polygon"] = {
            "shell": [[x + dx, y + dy] for x, y in shell],
            "holes": [],
        }
    document = WallsDocument.model_validate(raw)
    floor, _ = b3d.build_floor(
        sheet(order=(0.0, 0.0, order, 1)), document, WallsFloorExtras.model_validate(extras), None
    )
    return b3d.BuiltFloor(floor, (0.0, 0.0, order, 1), b3d.axes_in_mm(raw, frame))


def ref_axes() -> dict[str, Any]:
    return axes_block(REF_X, REF_Y)


def test_group_key_and_label_come_from_corps_and_section() -> None:
    assert b3d.group_of("9", "3") == ("k9-s3", "Корп. 9 · сек. 3")
    assert b3d.group_of(" 9 ", None) == ("k9", "Корп. 9")
    assert b3d.group_of(None, "3") == ("s3", "Корпус не указан · сек. 3")
    assert b3d.group_of(None, None) == ("none", "Корпус не указан")
    assert b3d.group_of("", "  ") == ("none", "Корпус не указан")


def test_floors_are_grouped_and_groups_sorted_naturally() -> None:
    items = [
        built(corps="10", section=None, axes=ref_axes()),
        built(corps="2", section="1", axes=ref_axes(), order=1),
        built(corps="2", section="1", elevation=BASE + 3000, axes=ref_axes(), order=2),
        built(corps=None, section=None, order=3),
    ]
    floors = b3d.align_floors(items)
    assert [f.group_key for f in floors] == ["k10", "k2-s1", "k2-s1", "none"]
    groups = b3d.build_groups(floors)
    assert [(g.key, g.label, g.floor_count, g.aligned_count) for g in groups] == [
        ("k2-s1", "Корп. 2 · сек. 1", 2, 2),
        ("k10", "Корп. 10", 1, 1),
        ("none", "Корпус не указан", 1, 0),
    ]


def test_second_floor_is_aligned_by_common_axes_and_geometry_is_shifted() -> None:
    reference = built(axes=ref_axes())
    moved = built(
        elevation=BASE + 3000,
        order=1,
        axes=axes_block(
            {k: v + 1234.0 for k, v in REF_X.items()}, {k: v - 567.0 for k, v in REF_Y.items()}
        ),
        shift=(1234.0, -567.0),
    )
    ref_floor, floor = b3d.align_floors([reference, moved])
    assert (ref_floor.alignment, ref_floor.offset_mm) == ("reference", (0.0, 0.0))
    assert floor.alignment == "axes" and floor.alignment_message is None
    assert floor.offset_mm == pytest.approx((-1234.0, 567.0))
    assert floor.alignment_axes == ["3.1", "3.2", "3.3", "А", "Б"]
    assert floor.bbox == pytest.approx(ref_floor.bbox)
    assert [p for xy in floor.outline for p in xy] == pytest.approx(
        [p for xy in ref_floor.outline for p in xy]
    )


def test_reference_is_the_lowest_floor_with_axes_in_both_directions() -> None:
    low_no_axes = built(elevation=BASE, order=0)
    low_axes = built(elevation=BASE + 3000, order=1, axes=ref_axes())
    high_axes = built(elevation=BASE + 6000, order=2, axes=ref_axes())
    floors = b3d.align_floors([low_no_axes, high_axes, low_axes])
    assert [f.alignment for f in floors] == ["none", "axes", "reference"]
    assert floors[0].alignment_message == "оси не распознаны: пересчитайте конструкции листа"


def test_reference_is_the_floor_sharing_most_axes_not_the_lowest_parking() -> None:
    # Подземный этаж с другой сеткой: общая с остальными только ось «А».
    parking = built(
        elevation=BASE - 3000,
        order=0,
        axes=axes_block({"П1": 1000.0, "П2": 2000.0}, {"А": REF_Y["А"], "П3": 9000.0}),
    )
    first = built(elevation=BASE, order=1, axes=ref_axes())
    second = built(elevation=BASE + 3000, order=2, axes=ref_axes())
    floors = b3d.align_floors([parking, first, second])
    # Эталон - самый нижний из двух верхних (ничья по числу общих осей), подземный не совмещён.
    assert [f.alignment for f in floors] == ["none", "reference", "axes"]
    assert floors[0].alignment_message is not None
    assert floors[2].alignment_axes == ["3.1", "3.2", "3.3", "А", "Б"]


def test_reference_tie_by_shared_axes_keeps_the_lowest_floor() -> None:
    low = built(elevation=BASE, order=0, axes=ref_axes())
    high = built(elevation=BASE + 3000, order=1, axes=ref_axes())
    assert [f.alignment for f in b3d.align_floors([high, low])] == ["axes", "reference"]


def test_single_floor_group_is_reference_only_with_axes() -> None:
    (with_axes,) = b3d.align_floors([built(axes=ref_axes())])
    assert with_axes.alignment == "reference"
    (without,) = b3d.align_floors([built()])
    assert (without.alignment, without.offset_mm) == ("none", (0.0, 0.0))
    assert without.alignment_message is not None


def test_floors_of_different_groups_do_not_align_to_each_other() -> None:
    a = built(corps="9", axes=ref_axes())
    b = built(corps="8", axes=axes_block({"X": 1.0}, {"Y": 2.0}), order=1)
    fa, fb = b3d.align_floors([a, b])
    assert (fa.alignment, fb.alignment) == ("reference", "reference")


def test_partial_axes_floor_falls_back_to_bbox_center_of_reference() -> None:
    reference = built(axes=ref_axes())
    partial = built(
        elevation=BASE + 3000,
        order=1,
        axes=axes_block(REF_X, {}),
        shift=(20000.0, 5000.0),
    )
    assert partial.axes.message is not None and "только вертикальные" in partial.axes.message
    _ref, floor = b3d.align_floors([reference, partial])
    assert floor.alignment == "none" and floor.alignment_axes == []
    assert floor.alignment_message is not None and "только вертикальные" in floor.alignment_message
    assert floor.offset_mm == pytest.approx((-20000.0, -5000.0))
    assert floor.bbox == pytest.approx([0.0, 0.0, 6000.0, 4000.0])


def test_no_common_axes_in_one_direction_is_not_aligned() -> None:
    reference = built(axes=ref_axes())
    other = built(elevation=BASE + 3000, order=1, axes=axes_block(REF_X, {"В": 1000.0}))
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "none"
    assert floor.alignment_message == "нет общих горизонтальных осей с эталонным этажом"


def test_disagreeing_axes_are_not_aligned_and_named() -> None:
    reference = built(axes=ref_axes())
    # 3.3 отличается на 400 мм от смещения остальных (медиана 100 мм).
    skewed = {"3.1": 1100.0, "3.2": 5100.0, "3.3": 9500.0}
    other = built(elevation=BASE + 3000, order=1, axes=axes_block(skewed, REF_Y))
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "none"
    assert floor.alignment_message == "вертикальных оси расходятся с эталоном: 3.3"


def test_axes_within_tolerance_are_aligned_by_median() -> None:
    reference = built(axes=ref_axes())
    close = {"3.1": 1100.0, "3.2": 5100.0, "3.3": 9000.0 + b3d.AXIS_TOLERANCE_MM - 10.0 + 100.0}
    other = built(elevation=BASE + 3000, order=1, axes=axes_block(close, REF_Y))
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "axes"
    assert floor.offset_mm[0] == pytest.approx(-100.0)
    assert floor.offset_mm[1] == pytest.approx(0.0)


def test_old_walls_without_axes_block_is_marked_for_recalculation() -> None:
    axes = b3d.axes_in_mm(raw_document(), FRAME)
    assert not axes.usable
    assert axes.message == "оси не распознаны: пересчитайте конструкции листа"
    reference, old = built(axes=ref_axes()), built(elevation=BASE + 3000, order=1)
    _ref, floor = b3d.align_floors([reference, old])
    assert floor.alignment == "none"
    assert floor.alignment_message == axes.message


def test_group_without_reference_keeps_floors_in_place_with_group_message() -> None:
    floors = b3d.align_floors([built(), built(elevation=BASE + 3000, order=1)])
    assert [f.alignment for f in floors] == ["none", "none"]
    assert all(f.offset_mm == (0.0, 0.0) for f in floors)
    assert all(
        f.alignment_message is not None
        and f.alignment_message.startswith("в группе нет этажа с осями в обоих направлениях")
        for f in floors
    )


def test_unconfirmed_frame_makes_axes_unusable_with_frame_reason() -> None:
    frame = CadFrameRead(
        confirmed=False,
        reason="Масштаб не подтверждён размерной проверкой: кадр координат не установлен.",
        units=None,
        origin_pt=None,
        mm_per_pdf_point=None,
    )
    axes = b3d.axes_in_mm({"axes": ref_axes()}, frame)
    assert not axes.usable and axes.message == frame.reason
    (floor,) = b3d.align_floors([built(axes=ref_axes(), frame=frame)])
    assert floor.alignment == "none" and str(frame.reason) in (floor.alignment_message or "")


def test_axes_block_with_status_missing_reports_its_message() -> None:
    block = {"status": "missing", "message": "оси не найдены на листе", "items": []}
    axes = b3d.axes_in_mm({"axes": block}, FRAME)
    assert not axes.usable and axes.message == "оси не найдены на листе"


def test_duplicate_label_with_far_positions_is_dropped() -> None:
    block = axes_block({"3.1": 1000.0}, {"А": 2000.0})
    block["items"].append({"label": "3.1", "orient": "vertical", "pos_pt": 9999.0})
    axes = b3d.axes_in_mm({"axes": block}, FRAME)
    assert "3.1" not in axes.vertical and axes.message is not None
