"""Привязка рёбер зоны к конструкциям (ADR-0042, п. 6): геометрия без базы и ведомость со стенами.

Синтетика: комната 4 x 5 м (мм DXF), контур зоны по внутренним граням стен. Юг и север - монолит,
запад - кладка с дверью 900 мм (перемычка в кладке), восток - ГКЛ на 3 м, дальше линия разреза
без стены. Конец стены и угол соседней стены размывают класс на допуск 80 мм: отсчёты середин
отрезков по 50 мм дают ровно две лишние точки (100 мм) - тесты проверяют именно эти числа.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest

from app.contracts.cad_finishes import CadFinishLayer, CadFinishTemplateWrite
from app.contracts.cad_zones import CadZoneRead
from app.services.cad_finish_edges import (
    EDGE_TOLERANCE_MM,
    SAMPLE_STEP_MM,
    EdgeConstruction,
    EdgeIndex,
    EdgeOpening,
    Point,
    construction_base,
)
from app.services.cad_finishes import FinishFrame, FinishWallsInput, build_finish_sheet
from tests.test_cad_finishes import (
    PAINT,
    PRIMER,
    _template,
    _zone,
)

ROOM: list[Point] = [(0, 0), (4000, 0), (4000, 5000), (0, 5000)]


def rect(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def room_walls() -> list[EdgeConstruction]:
    return [
        EdgeConstruction("s", "monolith", [rect(-200, -200, 4200, 0)]),
        EdgeConstruction("n", "monolith", [rect(-200, 5000, 4200, 5200)]),
        EdgeConstruction("w1", "masonry", [rect(-200, 0, 0, 1000)]),
        EdgeConstruction("w2", "masonry", [rect(-200, 1900, 0, 5000)]),
        EdgeConstruction("e", "gkl", [rect(4000, 0, 4200, 3000)]),
    ]


def door(opening_id: str = "d1") -> EdgeOpening:
    return EdgeOpening(opening_id, "door", rect(-200, 1000, 0, 1900), 900, 200, "masonry")


# ------------------------------------------------------------------ геометрия рёбер


def test_construction_base_by_kind() -> None:
    assert construction_base("monolith_wall") == "monolith"
    assert construction_base("monolith_pylon") == "monolith"
    assert construction_base("monolith_column") == "monolith"
    assert construction_base("masonry") == "masonry"
    assert construction_base("frame_partition") == "gkl"
    assert construction_base("floor_slab") is None
    # Материал кладки на основание не влияет: ГКЛ в справочнике материалов нет.
    assert construction_base("masonry", "aerated_concrete") == "masonry"


def test_room_edges_on_faces_split_by_base_door_and_cut_line() -> None:
    edges = EdgeIndex(room_walls(), [door()]).link_ring(ROOM)
    # Конец стены размывает класс на допуск: ГКЛ тянется на 100 мм за свой торец (3000 -> 3100),
    # а у севера 100 мм восточного ребра отходят монолиту (угол).
    assert edges.base_mm == pytest.approx(
        {"monolith": 8100.0, "masonry": 4100.0, "gkl": 3100.0}, abs=1e-6
    )
    # Дверь ровно по перемычке: у торца перемычки ближе стена, а не её торец.
    assert edges.door_mm == pytest.approx({"d1": 900.0})
    assert edges.gap_mm == {}
    assert edges.open_mm == pytest.approx(1800.0)
    assert edges.perimeter_mm == pytest.approx(18000.0)
    assert [(span.kind, span.base, span.ref) for span in edges.spans] == [
        ("wall", "monolith", "s"),
        ("wall", "gkl", "e"),
        ("none", None, None),
        ("wall", "monolith", "n"),
        ("wall", "masonry", "w2"),
        ("door", None, "d1"),
        ("wall", "masonry", "w1"),
    ]


def test_ring_offset_by_forty_millimetres_is_still_linked() -> None:
    inner = [(40.0, 40.0), (3960.0, 40.0), (3960.0, 4960.0), (40.0, 4960.0)]
    edges = EdgeIndex(room_walls(), [door()]).link_ring(inner)
    assert edges.perimeter_mm == pytest.approx(2 * (3920 + 4920))
    assert edges.door_mm["d1"] == pytest.approx(900.0, abs=100.0)
    assert edges.base_mm["monolith"] == pytest.approx(2 * 3920.0 + 100.0, abs=150.0)
    assert edges.base_mm["masonry"] == pytest.approx(4100.0, abs=150.0)
    assert edges.base_mm["gkl"] == pytest.approx(3000.0, abs=150.0)
    # Стена не дальше допуска от контура: открытой границы только линия разреза.
    assert edges.open_mm == pytest.approx(1800.0, abs=200.0)


def test_ring_beyond_tolerance_is_all_open() -> None:
    inner = [(200.0, 200.0), (3800.0, 200.0), (3800.0, 4800.0), (200.0, 4800.0)]
    edges = EdgeIndex(room_walls(), [door()]).link_ring(inner)
    assert edges.open_mm == pytest.approx(edges.perimeter_mm)
    assert edges.base_mm == {"monolith": 0.0, "masonry": 0.0, "gkl": 0.0}
    assert edges.door_mm == {} and edges.gap_mm == {}


def test_lintel_wins_a_tie_with_the_wall_boundary() -> None:
    # Сплошная кладка без разрыва и перемычка на той же грани: расстояние равно, границей служит
    # перемычка; у торцов перемычки ближе стена.
    walls = [EdgeConstruction("w", "masonry", [rect(-200, 0, 0, 5000)])]
    edges = EdgeIndex(walls, [door()]).link_ring(ROOM)
    assert edges.door_mm == pytest.approx({"d1": 900.0})
    # Остальное ребро и по 100 мм у южного и северного углов (размытие на допуск).
    assert edges.base_mm["masonry"] == pytest.approx(5000.0 - 900.0 + 200.0)


def test_gap_opening_is_reported_separately() -> None:
    gap = EdgeOpening("g1", "gap", rect(4000, 3500, 4200, 4300), 800, 200, None)
    edges = EdgeIndex(room_walls(), [door(), gap]).link_ring(ROOM)
    # Без соседней стены торцы перемычки тоже размыты на допуск: 800 + 2 x 100 мм.
    assert edges.gap_mm == pytest.approx({"g1": 1000.0})
    assert edges.door_mm == pytest.approx({"d1": 900.0})
    assert edges.perimeter_mm == pytest.approx(18000.0)


def test_hole_boundary_of_a_construction_is_a_wall() -> None:
    # Колонна с отверстием-шахтой: зона по грани отверстия.
    block = EdgeConstruction(
        "blk", "monolith", [rect(-1000, -1000, 5000, 6000), rect(0, 0, 4000, 5000)]
    )
    edges = EdgeIndex([block], []).link_ring(ROOM)
    assert edges.base_mm["monolith"] == pytest.approx(18000.0)
    assert edges.open_mm == 0.0


def test_ring_without_enough_points_has_no_spans() -> None:
    edges = EdgeIndex(room_walls(), []).link_ring([(0, 0), (100, 0)])
    assert edges.spans == () and edges.perimeter_mm == 0.0


def test_closing_vertex_is_ignored() -> None:
    closed = [*ROOM, ROOM[0]]
    a = EdgeIndex(room_walls(), [door()]).link_ring(ROOM)
    b = EdgeIndex(room_walls(), [door()]).link_ring(closed)
    assert a == b


def test_parameters_are_module_constants() -> None:
    assert SAMPLE_STEP_MM == 50.0 and EDGE_TOLERANCE_MM == 80.0


def test_three_hundred_constructions_by_sixty_zones_under_a_second() -> None:
    cols, rows, cell_w, cell_h, wall = 10, 6, 4000, 5000, 200
    pieces = 3
    constructions: list[EdgeConstruction] = []
    for row in range(rows + 1):
        for col in range(cols):
            x0, y = col * cell_w, row * cell_h
            for part in range(pieces):
                xa = x0 + part * cell_w // pieces
                xb = x0 + (part + 1) * cell_w // pieces
                constructions.append(
                    EdgeConstruction(f"h{row}-{col}-{part}", "masonry", [rect(xa, y, xb, y + wall)])
                )
    for col in range(cols + 1):
        for row in range(rows):
            x, y0 = col * cell_w, row * cell_h
            for part in range(pieces):
                ya = y0 + wall + part * (cell_h - wall) // pieces
                yb = y0 + wall + (part + 1) * (cell_h - wall) // pieces
                constructions.append(
                    EdgeConstruction(
                        f"v{col}-{row}-{part}", "monolith", [rect(x, ya, x + wall, yb)]
                    )
                )
    assert len(constructions) >= 300
    rings = [
        rect(
            col * cell_w + wall,
            row * cell_h + wall,
            (col + 1) * cell_w,
            (row + 1) * cell_h,
        )
        for row in range(rows)
        for col in range(cols)
    ]
    assert len(rings) == 60
    started = time.perf_counter()
    index = EdgeIndex(constructions, [])
    results = [index.link_ring(ring) for ring in rings]
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"{elapsed:.2f} c"
    assert all(item.open_mm == 0.0 for item in results)


# ------------------------------------------------------------------ ведомость со стенами

# Кадр: pt = origin + (x_mm, -y_mm) / 10; страница 1000 x 1000 pt; комната внутри страницы.
FRAME = FinishFrame(1000.0, 1000.0, (100.0, 700.0), 10.0)


def norm(x_mm: float, y_mm: float) -> tuple[float, float]:
    return ((100.0 + x_mm / 10.0) / 1000.0, (700.0 - y_mm / 10.0) / 1000.0)


def room_zone(**kwargs: Any) -> CadZoneRead:
    zone = _zone(**kwargs)
    return zone.model_copy(update={"points": [norm(x, y) for x, y in ROOM]})


def walls_input(
    *, openings: list[EdgeOpening] | None = None, door_height_mm: int | None = 2100
) -> FinishWallsInput:
    return FinishWallsInput(
        room_walls(), [door()] if openings is None else openings, FRAME, door_height_mm
    )


def sheet(zones: list[CadZoneRead], templates: list[Any], walls: FinishWallsInput | None) -> Any:
    return build_finish_sheet(
        revision_id=uuid.uuid4(),
        page_index=0,
        zones=zones,
        templates=templates,
        levels_wall_height_mm=2800,
        walls=walls,
    )


STAGED = [
    PRIMER,
    {"work": "Обеспыливание", "bases": ["monolith"]},
    {"work": "Штукатурка", "bases": ["masonry", "monolith"]},
]


def wall_areas(result: Any) -> list[float | None]:
    (zone,) = result.zones
    return [layer.area_m2 for layer in zone.layers if layer.surface == "walls"]


def test_sheet_walls_by_base_with_stepped_layers() -> None:
    template = _template(room_types=["living"], walls=STAGED, ceiling=[PAINT])
    result = sheet([room_zone()], [template], walls_input())
    (zone,) = result.zones
    breakdown = zone.walls_breakdown
    assert breakdown.linked
    assert (breakdown.monolith_m, breakdown.masonry_m, breakdown.gkl_m) == pytest.approx(
        (8.1, 4.1, 3.1)
    )
    assert (breakdown.door_m, breakdown.gap_m, breakdown.open_m) == pytest.approx((0.9, 0.0, 1.8))
    area = breakdown.area_by_base
    assert (area.monolith, area.masonry, area.gkl) == pytest.approx(
        (8.1 * 2.8, 4.1 * 2.8, 3.1 * 2.8)
    )
    # Над дверью 2100: 0,9 м x (2,8 - 2,1) м.
    assert breakdown.door_over_area_m2 == pytest.approx(0.63)
    assert zone.wall_area_m2 == pytest.approx(15.3 * 2.8 + 0.63)
    # Откосы: 2 x 2,1 + 0,9 = 5,1 м, на половину толщины 200 мм.
    assert breakdown.reveal_m == pytest.approx(5.1)
    assert breakdown.reveal_area_m2 == pytest.approx(0.51)
    # Слои: без ограничения - все стены; монолит - только монолит; кладка+монолит - и надпроёмная
    # часть (стена-хозяин двери - кладка). Откосы шаблон не включает.
    plain, monolith, plaster = wall_areas(result)
    assert plain == pytest.approx(zone.wall_area_m2)
    assert monolith == pytest.approx(8.1 * 2.8)
    assert plaster == pytest.approx(12.2 * 2.8 + 0.63)
    assert [layer.bases for layer in zone.layers if layer.surface == "walls"] == [
        None,
        ["monolith"],
        ["masonry", "monolith"],
    ]
    codes = {warning.code: warning.zone_ids for warning in result.warnings}
    assert codes == {"windows_not_detected": [zone.zone_id]}


def test_sheet_reveals_go_to_layers_only_when_the_template_says_so() -> None:
    template = _template(room_types=["living"], walls=STAGED)
    include = template.model_copy(update={"walls_include_reveals": True})
    off = sheet([room_zone()], [template], walls_input())
    on = sheet([room_zone()], [include], walls_input())
    plain_off, mono_off, plaster_off = wall_areas(off)
    plain_on, mono_on, plaster_on = wall_areas(on)
    assert plain_on == pytest.approx(plain_off + 0.51)
    # Откос двери в кладке: слой по монолиту его не получает, слой кладки - получает.
    assert mono_on == pytest.approx(mono_off)
    assert plaster_on == pytest.approx(plaster_off + 0.51)
    assert on.zones[0].wall_area_m2 == off.zones[0].wall_area_m2


def test_sheet_door_zone_of_a_person_sets_the_door_height() -> None:
    zone = room_zone()
    door_zone = _zone(kind="door", area=None, perimeter=None).model_copy(
        update={"points": [norm(-100, 1000), norm(-100, 1900)], "door_height_mm": 2000}
    )
    template = _template(room_types=["living"], walls=[PRIMER])
    result = sheet([zone, door_zone], [template], walls_input(door_height_mm=2100))
    assert result.zones[0].walls_breakdown.door_over_area_m2 == pytest.approx(0.9 * 0.8)
    assert result.zones[0].walls_breakdown.reveal_m == pytest.approx(2 * 2.0 + 0.9)


def test_sheet_door_without_height_is_a_gap_with_a_warning() -> None:
    template = _template(room_types=["living"], walls=[PRIMER])
    include = template.model_copy(update={"walls_include_reveals": True})
    result = sheet([room_zone()], [include], walls_input(door_height_mm=None))
    (zone,) = result.zones
    breakdown = zone.walls_breakdown
    assert (breakdown.door_m, breakdown.gap_m) == pytest.approx((0.0, 0.9))
    assert breakdown.door_over_area_m2 == 0.0
    assert breakdown.reveal_m is None and breakdown.reveal_area_m2 is None
    assert zone.wall_area_m2 == pytest.approx(15.3 * 2.8)
    # Откосы не определены: слой, который должен их включать, не определён, а не занижен.
    assert zone.layers[0].area_m2 is None and zone.layers[0].material_qty is None
    codes = {warning.code: warning.zone_ids for warning in result.warnings}
    assert codes["door_height_missing"] == [zone.zone_id]
    assert "gap_unknown_height" not in codes


def test_sheet_gap_has_no_height_and_is_not_finished() -> None:
    gap = EdgeOpening("g1", "gap", rect(4000, 3500, 4200, 4300), 800, 200, None)
    template = _template(room_types=["living"], walls=[PRIMER])
    result = sheet([room_zone()], [template], walls_input(openings=[door(), gap]))
    (zone,) = result.zones
    assert zone.walls_breakdown.gap_m == pytest.approx(1.0)
    codes = {warning.code: warning.zone_ids for warning in result.warnings}
    assert codes["gap_unknown_height"] == [zone.zone_id]
    assert "door_height_missing" not in codes


def test_sheet_reveal_without_wall_thickness_is_undefined() -> None:
    thin = EdgeOpening("d1", "door", rect(-200, 1000, 0, 1900), 900, None, "masonry")
    template = _template(room_types=["living"], walls=[PRIMER])
    result = sheet([room_zone()], [template], walls_input(openings=[thin]))
    breakdown = result.zones[0].walls_breakdown
    assert breakdown.reveal_m == pytest.approx(5.1) and breakdown.reveal_area_m2 is None


def test_sheet_without_height_keeps_lengths_and_nulls_the_areas() -> None:
    template = _template(room_types=["living"], walls=[PRIMER])
    result = build_finish_sheet(
        revision_id=uuid.uuid4(),
        page_index=0,
        zones=[room_zone()],
        templates=[template],
        levels_wall_height_mm=None,
        walls=walls_input(),
    )
    (zone,) = result.zones
    breakdown = zone.walls_breakdown
    assert breakdown.linked and breakdown.masonry_m == pytest.approx(4.1)
    assert breakdown.area_by_base.masonry is None and breakdown.door_over_area_m2 is None
    assert zone.wall_area_m2 is None and zone.layers[0].area_m2 is None
    assert breakdown.reveal_area_m2 == pytest.approx(0.51)


def test_sheet_without_walls_falls_back_to_perimeter_with_edges_unlinked() -> None:
    template = _template(room_types=["living"], walls=STAGED)
    zone_in = room_zone()
    result = sheet([zone_in], [template], None)
    (zone,) = result.zones
    assert not zone.walls_breakdown.linked
    assert zone.walls_breakdown.masonry_m is None and zone.walls_breakdown.door_m is None
    assert zone.walls_breakdown.area_by_base.monolith is None
    assert zone.wall_area_m2 == pytest.approx(18.0 * 2.8)
    plain, monolith, plaster = wall_areas(result)
    # Без привязки основание неизвестно: слой с основаниями не определён (не 0 и не вся стена).
    assert plain == pytest.approx(18.0 * 2.8) and monolith is None and plaster is None
    codes = {warning.code: warning.zone_ids for warning in result.warnings}
    assert codes == {"edges_unlinked": [zone_in.id]}


def test_sheet_zone_with_unusable_contour_is_unlinked_next_to_linked_ones() -> None:
    template = _template(room_types=["living"], walls=[PRIMER])
    good = room_zone()
    broken = room_zone(area=None, perimeter=None, geometry_issue="self_intersection")
    result = sheet([good, broken], [template], walls_input())
    first, second = result.zones
    assert first.walls_breakdown.linked and not second.walls_breakdown.linked
    codes = {warning.code: warning.zone_ids for warning in result.warnings}
    assert codes["windows_not_detected"] == [good.id]
    assert codes["edges_unlinked"] == [broken.id]


def test_sheet_without_rooms_and_walls_still_warns_unlinked() -> None:
    result = sheet([], [], None)
    assert [(w.code, w.zone_ids) for w in result.warnings] == [("edges_unlinked", [])]
    assert sheet([], [], walls_input()).warnings == []


# ------------------------------------------------------------------ контракт слоя и шаблона


def test_layer_bases_only_for_wall_layers_and_unique() -> None:
    CadFinishLayer(work="Обеспыливание", bases=["monolith"])
    with pytest.raises(ValueError, match="не повторяются"):
        CadFinishLayer(work="X", bases=["gkl", "gkl"])
    with pytest.raises(ValueError):
        CadFinishLayer.model_validate({"work": "X", "bases": []})
    with pytest.raises(ValueError, match="только слоям стен"):
        CadFinishTemplateWrite(
            name="Т", floor_layers=[CadFinishLayer(work="Стяжка", bases=["monolith"])]
        )
    with pytest.raises(ValueError, match="только слоям стен"):
        CadFinishTemplateWrite(
            name="Т", ceiling_layers=[CadFinishLayer(work="Окраска", bases=["gkl"])]
        )
    ok = CadFinishTemplateWrite(
        name="Т", wall_layers=[CadFinishLayer(work="Шпаклёвка", bases=["gkl", "masonry"])]
    )
    assert ok.walls_include_reveals is False
