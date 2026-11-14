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


def test_floor_base_is_the_slab_top_of_walls_json_v19_and_old_files_keep_the_sheet_elevation() -> (
    None
):
    new = floor_of(
        raw_document(floor_elevation_mm=50900, slab_top_elevation_mm=50800, floor_finish_mm=100),
        raw_extras(),
    )
    assert (new.elevation_known, new.base_z_mm) == (True, 50800)
    assert floor_of(raw_document(), raw_extras()).base_z_mm == BASE
    # Ручная отметка этажа не уменьшается на пирог пола.
    document = WallsDocument.model_validate(
        raw_document(floor_elevation_mm=50900, slab_top_elevation_mm=50800)
    )
    levels = CadSheetLevelsRead(
        floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None, floor_elevation_mm=9000
    )
    floor, _ = b3d.build_floor(
        sheet(overrides=levels), document, WallsFloorExtras.model_validate(raw_extras()), None
    )
    assert floor.base_z_mm == 9000


def test_floors_stack_on_the_slab_top_base() -> None:
    def make(elevation: int, slab_top: int, order: int) -> CadBuilding3dFloorRead:
        raw = raw_document(
            floor_elevation_mm=elevation, slab_top_elevation_mm=slab_top, floor_height_mm=3300
        )
        floor, _ = b3d.build_floor(
            sheet(order=(0.0, 0.0, order, 1)),
            WallsDocument.model_validate(raw),
            WallsFloorExtras.model_validate(raw_extras()),
            None,
        )
        return floor

    upper, lower = make(54200, 54100, 1), make(50900, 50800, 0)
    ordered = b3d.sort_floors([(upper, (0.0, 0.0, 1, 1)), (lower, (0.0, 0.0, 0, 1))])
    assert [f.base_z_mm for f in ordered] == [50800, 54100]
    # Верх стен нижнего этажа (база + высота этажа - плита) = низ плиты верхнего (база - 200 + ...).
    assert lower.base_z_mm + lower.floor_height_mm - lower.slab_thickness_mm == 53900
    assert upper.base_z_mm - upper.slab_thickness_mm == 53900


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
    elevation: int | None = BASE,
    order: int = 0,
    axes: dict[str, Any] | None = None,
    frame: CadFrameRead = FRAME,
    shift: tuple[float, float] = (0.0, 0.0),
    include_walls: bool = False,
) -> b3d.BuiltFloor:
    """Этаж из walls.json с заголовком плана и (необязательно) осями; `shift` сдвигает DXF.

    `elevation=None` - отметка этажа не определена.
    """
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
        sheet(order=(0.0, 0.0, order, 1)),
        document,
        WallsFloorExtras.model_validate(extras),
        None,
        include_walls=include_walls,
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


def test_one_shifted_bubble_is_outvoted_by_agreeing_axes() -> None:
    reference = built(axes=ref_axes())
    # Кружок 3.3 на выноске сдвинут на 400 мм от сдвига остальных (100 мм): совмещение по 3.1, 3.2.
    skewed = {"3.1": 1100.0, "3.2": 5100.0, "3.3": 9500.0}
    other = built(elevation=BASE + 3000, order=1, axes=axes_block(skewed, REF_Y))
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "axes"
    assert floor.alignment_axes == ["3.1", "3.2", "А", "Б"]
    assert floor.offset_mm == pytest.approx((-100.0, 0.0))


def test_ambiguous_axes_are_not_aligned_and_named() -> None:
    reference = built(axes=axes_block({**REF_X, "3.4": 13000.0}, REF_Y))
    # Две марки дают сдвиг 100 мм, две другие - 600 мм: неоднозначность, а не выноска.
    split = {"3.1": 1100.0, "3.2": 5100.0, "3.3": 9600.0, "3.4": 13600.0}
    other = built(elevation=BASE + 3000, order=1, axes=axes_block(split, REF_Y))
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "none"
    assert floor.alignment_message == "вертикальных оси расходятся с эталоном: 3.1, 3.2, 3.3, 3.4"


def test_single_common_labels_with_far_shift_do_not_overlap_reference() -> None:
    reference = built(axes=ref_axes())
    # Одноимённые метки 3.1 и «А» - на деле другие оси: сдвиг уводит этаж далеко от эталона.
    other = built(
        elevation=BASE + 3000,
        order=1,
        axes=axes_block({"3.1": 1000.0 + 50000.0}, {"А": 2000.0 + 30000.0}),
    )
    _ref, floor = b3d.align_floors([reference, other])
    assert floor.alignment == "none" and floor.alignment_axes == []
    assert floor.alignment_message is not None
    assert "не перекрывает" in floor.alignment_message
    assert "3.1, А" in floor.alignment_message
    assert floor.bbox == pytest.approx([0.0, 0.0, 6000.0, 4000.0])


def test_overlap_share_is_zero_for_degenerate_or_disjoint_boxes() -> None:
    assert b3d._overlap_share([0, 0, 0, 10], [0, 0, 10, 10]) == 0.0
    assert b3d._overlap_share([0, 0, 10, 10], [20, 0, 30, 10]) == 0.0
    assert b3d._overlap_share([0, 0, 10, 10], [5, 0, 15, 10]) == pytest.approx(0.5)


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


# ------------------------------------------------------------------ контуры конструкций


def floor_with_walls(raw: dict[str, Any], *, include: bool = True) -> CadBuilding3dFloorRead:
    floor, _warnings = b3d.build_floor(
        sheet(),
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(raw_extras()),
        None,
        include_walls=include,
    )
    return floor


def test_walls_are_not_requested_by_default() -> None:
    assert floor_with_walls(raw_document(), include=False).walls is None
    assert floor_of(raw_document(), raw_extras()).walls is None


def test_walls_carry_kind_and_integer_open_rings() -> None:
    raw = raw_document()
    raw["constructions"][0]["polygon"]["shell"] = [
        [0.4, 0.0],
        [5000.0, 0.0],
        [5000.0, 0.0],
        [5000.0, 200.6],
        [0.4, 200.6],
        [0.4, 0.0],
    ]
    walls = floor_with_walls(raw).walls
    assert walls is not None
    assert [w.kind for w in walls] == ["masonry", "monolith_pylon"]
    assert walls[0].shell == [[0, 0], [5000, 0], [5000, 201], [0, 201]]
    assert all(isinstance(v, int) for w in walls for p in w.shell for v in p)


def test_walls_keep_construction_ids_from_walls_json() -> None:
    raw = raw_document()
    walls = floor_with_walls(raw).walls
    assert walls is not None
    assert [w.id for w in walls] == [c["id"] for c in raw["constructions"]]


def test_floor_slab_and_degenerate_rings_are_not_walls() -> None:
    raw = raw_document()
    slab = {**raw["constructions"][0], "id": "cccccccccccc", "kind": "floor_slab"}
    thin = {**raw["constructions"][0], "id": "dddddddddddd"}
    thin["polygon"] = {"shell": [[0.0, 0.0], [0.2, 0.1], [0.3, 0.2]], "holes": []}
    raw["constructions"] = [*raw["constructions"], slab, thin]
    walls = floor_with_walls(raw).walls
    assert walls is not None
    assert [w.kind for w in walls] == ["masonry", "monolith_pylon"]


def test_wall_with_many_points_is_simplified_to_the_limit() -> None:
    raw = raw_document()
    raw["constructions"][0]["polygon"]["shell"] = circle(3000)
    walls = floor_with_walls(raw).walls
    assert walls is not None
    assert 3 <= len(walls[0].shell) <= b3d.MAX_WALL_POINTS


def test_walls_over_limit_are_cut_with_warning() -> None:
    raw = raw_document()
    raw["constructions"] = [
        {**raw["constructions"][0], "id": f"{i:012d}"} for i in range(b3d.MAX_WALLS_PER_FLOOR + 5)
    ]
    floor, warnings = b3d.build_floor(
        sheet(),
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(raw_extras()),
        None,
        include_walls=True,
    )
    assert floor.walls is not None and len(floor.walls) == b3d.MAX_WALLS_PER_FLOOR
    assert [w.code for w in warnings] == ["walls_truncated"]


def test_walls_are_shifted_by_the_same_offset_as_outline() -> None:
    reference = built(axes=ref_axes(), include_walls=True)
    moved = built(
        elevation=BASE + 3000,
        order=1,
        axes=axes_block(
            {k: v + 1234.0 for k, v in REF_X.items()}, {k: v - 567.25 for k, v in REF_Y.items()}
        ),
        shift=(1234.0, -567.25),
        include_walls=True,
    )
    ref_floor, floor = b3d.align_floors([reference, moved])
    assert ref_floor.walls is not None and floor.walls is not None
    assert floor.offset_mm == pytest.approx((-1234.0, 567.25))
    assert [w.shell for w in floor.walls] == [w.shell for w in ref_floor.walls]
    # Сдвиг этажа не теряет идентификаторы конструкций.
    assert [w.id for w in floor.walls] == [w.id for w in ref_floor.walls]
    assert all(isinstance(v, int) for w in floor.walls for p in w.shell for v in p)


def test_fallback_shift_also_moves_walls_and_keeps_none_when_not_requested() -> None:
    reference = built(axes=ref_axes(), include_walls=True)
    partial = built(elevation=BASE + 3000, order=1, shift=(100.0, 0.0), include_walls=True)
    plain = built(elevation=BASE + 3000, order=1, shift=(100.0, 0.0))
    ref_floor, floor = b3d.align_floors([reference, partial])
    _ref, bare = b3d.align_floors([reference, plain])
    assert bare.walls is None
    assert ref_floor.walls is not None and floor.walls is not None
    assert floor.offset_mm == pytest.approx((-100.0, 0.0))
    assert [w.shell for w in floor.walls] == [w.shell for w in ref_floor.walls]


# ------------------------------------------------------------------ здания на объекте


def section_axes(
    prefix: str, dx: float = 0.0, dy: float = 0.0
) -> tuple[dict[str, float], dict[str, float]]:
    """Оси секции с номером в марке («1.1», «1.А»), сдвинутые на (dx, dy) мм."""
    return (
        {f"{prefix}.1": 1000.0 + dx, f"{prefix}.2": 5000.0 + dx},
        {f"{prefix}.А": 1000.0 + dy, f"{prefix}.Б": 3000.0 + dy},
    )


def parking_with_sections() -> list[b3d.BuiltFloor]:
    """Паркинг с осями двух секций и своими осями; секции - каждая в своей системе."""
    v1, h1 = section_axes("1", 20000.0, 10000.0)
    v2, h2 = section_axes("2", 40000.0, -5000.0)
    parking = built(
        corps=None,
        section=None,
        elevation=BASE - 4000,
        axes=axes_block({**v1, **v2, "П1": 0.0}, {**h1, **h2, "ПА": 0.0}),
    )
    first = built(corps="1", section=None, order=1, axes=axes_block(*section_axes("1")))
    second = built(corps="2", section=None, order=2, axes=axes_block(*section_axes("2")))
    return [first, second, parking]


def placed(
    items: list[b3d.BuiltFloor],
) -> tuple[dict[str, b3d.GroupPlacement], list[CadBuilding3dFloorRead]]:
    aligned = b3d.align_floors(items)
    placements = b3d.place_groups(items, aligned)
    return placements, b3d.apply_placements(aligned, placements)


def test_sections_are_placed_on_the_parking_by_section_axes() -> None:
    placements, floors = placed(parking_with_sections())
    assert placements["none"].placement == "reference"
    first, second = placements["k1"], placements["k2"]
    assert (first.placement, first.anchor_key, first.message) == ("axes", "none", None)
    assert first.offset_mm == pytest.approx((20000.0, 10000.0))
    assert first.axes == ("1.1", "1.2", "1.А", "1.Б")
    assert second.offset_mm == pytest.approx((40000.0, -5000.0))
    # Геометрия секций - в системе паркинга: сдвиг совмещения и постановки сложен.
    assert floors[0].offset_mm == pytest.approx((20000.0, 10000.0))
    assert floors[0].bbox is not None and floors[0].bbox[0] == pytest.approx(20000.0)
    assert floors[2].offset_mm == (0.0, 0.0)


def test_group_offsets_are_carried_to_groups_of_the_response() -> None:
    placements, floors = placed(parking_with_sections())
    groups = {g.key: g for g in b3d.build_groups(floors, placements)}
    assert groups["k1"].placement == "axes"
    assert groups["k1"].site_offset_mm == pytest.approx((20000.0, 10000.0))
    assert groups["k1"].placement_anchor == "none"
    assert groups["k1"].placement_axes == ["1.1", "1.2", "1.А", "1.Б"]
    assert groups["none"].placement == "reference" and groups["none"].placement_message is None


def test_section_axes_can_chain_through_a_placed_section() -> None:
    # Паркинг знает только секцию 1, секция 2 делит оси с секцией 1 (сквозная сетка).
    v1, h1 = section_axes("1", 20000.0, 10000.0)
    parking = built(corps=None, section=None, elevation=BASE - 4000, axes=axes_block(v1, h1))
    first = built(
        corps="1",
        section=None,
        order=1,
        axes=axes_block(
            {"1.1": 1000.0, "1.2": 5000.0, "1.3": 9000.0}, {"1.А": 1000.0, "1.Б": 3000.0}
        ),
    )
    second = built(
        corps="2",
        section=None,
        order=2,
        axes=axes_block({"1.3": 0.0, "2.1": 4000.0}, {"1.А": 500.0, "1.Б": 2500.0}),
    )
    placements, _ = placed([first, second, parking])
    # Опора - секция 1: у неё общие марки и с паркингом, и с секцией 2.
    assert placements["k1"].placement == "reference"
    assert placements["k2"].anchor_key == "k1" and placements["none"].anchor_key == "k1"
    k2, base = placements["k2"].offset_mm, placements["none"].offset_mm
    assert (k2[0] - base[0], k2[1] - base[1]) == pytest.approx((29000.0, 10500.0))


def test_typical_sections_with_local_axes_are_not_stacked() -> None:
    # Две типовые секции с одинаковой местной сеткой на одной отметке: марки совпали случайно.
    local = axes_block({"1": 1000.0, "2": 5000.0}, {"А": 1000.0, "Б": 3000.0})
    placements, floors = placed(
        [
            built(corps="1", section=None, axes=local),
            built(corps="2", section=None, order=1, axes=local),
        ]
    )
    assert placements["k1"].placement == "reference"
    assert placements["k2"].placement == "none"
    assert placements["k2"].message is not None and "той же отметке" in placements["k2"].message
    assert floors[1].offset_mm == (0.0, 0.0)


def test_local_axes_place_a_section_over_the_parking_on_another_level() -> None:
    parking = built(
        corps=None,
        section=None,
        elevation=BASE - 4000,
        axes=axes_block({"1": 11000.0, "2": 15000.0, "3": 19000.0}, {"А": 1000.0, "Б": 3000.0}),
    )
    section = built(
        corps="1",
        section=None,
        order=1,
        axes=axes_block({"1": 1000.0, "2": 5000.0}, {"А": 1000.0, "Б": 3000.0}),
    )
    placements, _ = placed([section, parking])
    assert placements["k1"].placement == "axes"
    assert placements["k1"].offset_mm == pytest.approx((10000.0, 0.0))


def test_one_misread_label_does_not_break_placement_but_disagreement_does() -> None:
    v1, h1 = section_axes("1", 20000.0, 10000.0)
    v1 = {**v1, "1.3": 29000.0, "1.4": 33000.0, "1.5": 99999.0}
    parking = built(corps=None, section=None, elevation=BASE - 4000, axes=axes_block(v1, h1))
    section = built(
        corps="1",
        section=None,
        order=1,
        axes=axes_block(
            {"1.1": 1000.0, "1.2": 5000.0, "1.3": 9000.0, "1.4": 13000.0, "1.5": 17000.0},
            {"1.А": 1000.0, "1.Б": 3000.0},
        ),
    )
    placements, _ = placed([section, parking])
    assert placements["k1"].placement == "axes"
    assert "1.5" not in placements["k1"].axes
    assert placements["k1"].offset_mm == pytest.approx((20000.0, 10000.0))
    # Две марки дают один сдвиг, две другие - другой общий сдвиг: неоднозначно, совпадения нет.
    wild = {**section_axes("1", 20000.0, 10000.0)[0], "1.3": 14000.0, "1.4": 18000.0}
    noisy = built(corps=None, section=None, elevation=BASE - 4000, axes=axes_block(wild, h1))
    placements, _ = placed([section, noisy])
    assert [p.placement for p in placements.values()].count("axes") == 0
    assert placements["none"].placement == "none"


def test_group_without_axes_or_single_group_placement() -> None:
    (only,) = b3d.place_groups(
        [built(axes=ref_axes())], b3d.align_floors([built(axes=ref_axes())])
    ).values()
    assert only.placement == "reference"
    items = [
        built(corps="1", section=None, axes=ref_axes()),
        built(corps="2", section=None, order=1),
    ]
    placements, _ = placed(items)
    assert placements["k1"].placement == "reference"
    assert placements["k2"].placement == "none"
    assert placements["k2"].message is not None and "осям" in placements["k2"].message


def test_unnamed_sheets_with_other_grids_become_separate_buildings() -> None:
    # Паркинг со своей сеткой и сводный план секций без отметки - оба «Корпус не указан».
    parking = built(
        corps=None,
        section=None,
        elevation=BASE - 4000,
        axes=axes_block({"01": 1000.0, "02": 9000.0}, {"0А": 1000.0, "0Б": 9000.0}),
    )
    v1, h1 = section_axes("1", 20000.0, 10000.0)
    v2, h2 = section_axes("2", 50000.0, 10000.0)
    summary = built(
        corps=None, section=None, elevation=None, order=1, axes=axes_block(v1 | v2, h1 | h2)
    )
    first = built(corps="1", section=None, order=2, axes=axes_block(*section_axes("1")))
    second = built(corps="2", section=None, order=3, axes=axes_block(*section_axes("2")))
    aligned = b3d.align_floors([parking, summary, first, second])
    keys = [floor.group_key for floor in aligned]
    assert keys[2:] == ["k1", "k2"]
    assert set(keys[:2]) == {"none", "none-2"}
    split = next(floor for floor in aligned[:2] if floor.group_key == "none-2")
    assert split.alignment == "reference"
    assert split.group_label.startswith("Корпус не указан · ")
    placements = b3d.place_groups([parking, summary, first, second], aligned)
    # План секций без отметки - связка: обе секции поставлены по маркам с номером секции.
    summary_key = keys[1]
    assert placements[summary_key].placement == "reference"
    assert placements["k1"].offset_mm == pytest.approx((20000.0, 10000.0))
    assert placements["k2"].offset_mm == pytest.approx((50000.0, 10000.0))
    # У паркинга с секциями нет общих марок - он не поставлен, с причиной.
    parking_key = keys[0]
    assert placements[parking_key].placement == "none"
    assert placements[parking_key].message is not None


def test_local_axes_without_levels_do_not_place_a_building() -> None:
    # Марки без номера секции повторяются, а без отметок наложение не проверить.
    local = axes_block({"1": 1000.0, "2": 5000.0, "3": 9000.0}, {"А": 1000.0, "Б": 3000.0})
    shifted = axes_block({"1": 3000.0, "2": 7000.0, "3": 11000.0}, {"А": 1000.0, "Б": 3000.0})
    placements, _ = placed(
        [
            built(corps="1", section=None, axes=local),
            built(corps="2", section=None, elevation=None, order=1, axes=shifted),
        ]
    )
    assert placements["k1"].placement == "reference"
    assert placements["k2"].placement == "none"
    assert placements["k2"].message is not None
    assert "без номера секции" in placements["k2"].message


# ------------------------------------------------------------------ уровни плиты (cad_walls v1.15)


def level_extras(**patch: Any) -> dict[str, Any]:
    """Кровля: основной скат на +99,300 и ниша на +91,750, парапет стены — по знаку +100,750."""
    levels: dict[str, Any] = {
        "status": "found",
        "base_mm": 99300,
        "base_source": "title",
        "zones": [
            {
                "shell": [[0, 0], [6000, 0], [6000, 4000], [0, 4000], [0, 0]],
                "holes": [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]],
                "mark_mm": 99050,
                "max_mm": 99300,
                "slab_top_mm": 99050,
                "source": "marks",
                "marks": 4,
            },
            {
                "shell": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]],
                "holes": [],
                "mark_mm": 91750,
                "max_mm": 91750,
                "slab_top_mm": 91750,
                "source": "marks",
                "marks": 1,
            },
            {
                "shell": [[0, 0], [1, 0]],
                "holes": [],
                "mark_mm": 99300,
                "slab_top_mm": 99300,
                "source": "base",
            },
        ],
        "construction_tops": [{"id": "aaaaaaaaaaaa", "top_mm": 100750, "marks": 1}],
    }
    levels.update(patch)
    return {**raw_extras(), "levels": levels}


def roof_document(**patch: Any) -> dict[str, Any]:
    title = {"corps": "9", "section": "3", "floors": [], "text": "План кровли", "kind": "roof"}
    body: dict[str, Any] = {
        "floor_elevation_mm": 99300,
        "slab_top_elevation_mm": 99300,
        "floor_elevation_basis": "roof_top",
        "title": title,
    }
    body.update(patch)
    return raw_document(**body)


def test_roof_floor_has_level_zones_label_and_parapet_top() -> None:
    floor = floor_of(roof_document(), level_extras())
    assert floor.label == "К9 · С3 · кровля"
    assert (floor.kind, floor.group_key, floor.base_z_mm) == ("roof", "k9-s3", 99300)
    # Вырожденный участок (две точки) отброшен; кольца без повтора первой точки.
    assert [(z.top_mm, z.mark_mm, z.max_mm, z.source) for z in floor.levels] == [
        (99050, 99050, 99300, "marks"),
        (91750, 91750, 91750, "marks"),
    ]
    assert floor.levels[0].shell == [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]
    assert floor.levels[0].holes == [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]]
    assert floor.walls is None
    document = WallsDocument.model_validate(roof_document())
    with_walls, _ = b3d.build_floor(
        sheet(),
        document,
        WallsFloorExtras.model_validate(level_extras()),
        None,
        include_walls=True,
    )
    assert with_walls.walls is not None
    assert [w.top_mm for w in with_walls.walls] == [100750, None]


def test_manual_elevation_moves_level_zones_and_tops_together() -> None:
    document = WallsDocument.model_validate(roof_document())
    overrides = CadSheetLevelsRead(
        floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None, floor_elevation_mm=99800
    )
    floor, _ = b3d.build_floor(
        sheet(overrides=overrides),
        document,
        WallsFloorExtras.model_validate(level_extras()),
        None,
        include_walls=True,
    )
    assert floor.base_z_mm == 99800
    assert [z.top_mm for z in floor.levels] == [99550, 92250]
    assert floor.walls is not None and floor.walls[0].top_mm == 101250


def test_old_walls_file_has_no_level_zones() -> None:
    floor = floor_of(raw_document(), raw_extras())
    assert (floor.levels, floor.kind) == ([], None)


def test_roof_without_slab_and_walls_takes_outline_from_level_zones() -> None:
    raw = roof_document()
    raw["constructions"] = []
    extras = level_extras()
    extras["slab"] = None
    floor = floor_of(raw, extras)
    assert floor.outline_source == "bbox"
    assert floor.outline == [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]
    assert len(floor.levels) == 2


def test_shift_moves_level_zones_with_the_floor() -> None:
    floor = floor_of(roof_document(), level_extras())
    moved = b3d._shifted(floor, 100.4, -50.0)
    assert moved.levels[0].shell[0] == [100, -50]
    assert moved.levels[0].holes[0][0] == [1100, 950]
    assert moved.levels[1].top_mm == 91750
