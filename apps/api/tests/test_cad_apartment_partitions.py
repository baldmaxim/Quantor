"""Внутриквартирные перегородки: классификация, высота маячного ряда, 3D, якорь вопроса.

Ожидаемые числа выписаны руками: высота этажа 3000, плита 200 -> стена 2800; маячный ряд 188;
объём перегородки = длина x толщина x высота.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dev import DEV_USER_ID
from app.contracts.cad_constructions import (
    CadConstructionProps,
    WallsConstruction,
    WallsDocument,
)
from app.contracts.cad_floor3d import WallsFloorExtras
from app.models import DocQuestionAnswer
from app.services import cad_constructions as calc
from app.services import cad_floor3d as f3d
from app.services import cad_partitions
from app.services.consistency.doc_questions import DocQuestionCode, question_by_code
from tests.conftest import make_context
from tests.doc_questions_support import make_project
from tests.test_cad_constructions_calc import NO_LEVELS, construction, document, opening
from tests.test_cad_floor3d import BASE, raw_document, raw_extras
from tests.test_consistency_doc_search import page, result_of

CODE = DocQuestionCode
PARTITION_ID = "pppppppppppp"
ANSWER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
HEIGHT = calc.PartitionHeight(188, "observed", ANSWER_ID, "АР ПЗ.pdf", 4, "высотой 188 мм")
# Перегородка 80 мм между двумя помещениями: x от 2960 до 3040.
THIN_SHELL = [[2960.0, 0.0], [3040.0, 0.0], [3040.0, 2000.0], [2960.0, 2000.0]]


def room(
    kind: str, apartment_no: str | None, x0: float, x1: float, room_type: str | None = None
) -> calc.PartitionZone:
    return calc.PartitionZone(
        kind, apartment_no, [[x0, 0.0], [x1, 0.0], [x1, 2000.0], [x0, 2000.0]], room_type
    )


LEFT_12 = room("room_apartment", "12", 0.0, 2960.0)
RIGHT_12 = room("room_apartment", "12", 3040.0, 6000.0)
RIGHT_13 = room("room_apartment", "13", 3040.0, 6000.0)
RIGHT_MOP = room("room_mop", None, 3040.0, 6000.0)
LEFT_LIVING = room("room_apartment", "12", 0.0, 2960.0, "living")
RIGHT_LIVING = room("room_apartment", "12", 3040.0, 6000.0, "living")
RIGHT_BATH = room("room_apartment", "12", 3040.0, 6000.0, "bath")
RIGHT_WC = room("room_apartment", "12", 3040.0, 6000.0, "wc")


def thin(
    *, key: str = PARTITION_ID, nominal: float | None = 80.0, kind: str = "masonry"
) -> dict[str, Any]:
    item = construction(key, kind=kind, nominal=nominal, axis=2000.0)
    item["polygon"] = {"shell": THIN_SHELL, "holes": []}
    item["area_plan_mm2"] = 160_000.0
    return item


def wall(**kwargs: Any) -> WallsConstruction:
    return WallsConstruction.model_validate(thin(**kwargs))


def props(**fields: Any) -> CadConstructionProps:
    return CadConstructionProps(**fields)


# ------------------------------------------------------------------ классификация


@pytest.mark.parametrize(
    ("zones", "expected"),
    [
        ([LEFT_12, RIGHT_12], True),  # две комнаты одной квартиры
        ([LEFT_12, RIGHT_MOP], False),  # квартира и МОП
        ([LEFT_12, RIGHT_13], False),  # две квартиры
        ([LEFT_12], False),  # с другой стороны нет зоны: обстройка шахты, не маячный ряд
        ([], False),  # зон нет
        ([room("room_apartment", None, 0.0, 2960.0)], False),  # номера квартиры нет
        ([room("room_apartment", "12", 0.0, 2000.0)], False),  # зона дальше 150 мм
    ],
)
def test_classification_by_touched_zones(zones: list[calc.PartitionZone], expected: bool) -> None:
    assert calc.is_apartment_partition(wall(), props(), zones) is expected


def test_zone_within_reach_150_counts_as_touching() -> None:
    near = room("room_apartment", "12", 0.0, 2960.0 - 140.0)
    assert calc.is_apartment_partition(wall(), props(), [near, RIGHT_12]) is True


def test_thickness_over_100_is_not_a_partition() -> None:
    assert calc.is_apartment_partition(wall(nominal=200.0), props(), [LEFT_12, RIGHT_12]) is False
    assert calc.is_apartment_partition(wall(nominal=100.0), props(), [LEFT_12, RIGHT_12]) is True
    assert calc.is_apartment_partition(wall(nominal=None), props(), [LEFT_12, RIGHT_12]) is False


@pytest.mark.parametrize("kind", ["monolith_wall", "monolith_pylon", "frame_partition"])
def test_only_masonry_is_a_partition(kind: str) -> None:
    assert calc.is_apartment_partition(wall(kind=kind), props(), [LEFT_12, RIGHT_12]) is False


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("mop", False),
        ("external", False),
        ("inter_apartment", False),
        ("shaft", False),
        ("interior", True),
        ("other", True),
        (None, True),
    ],
)
def test_manual_purpose_cancels_the_rule_except_interior(
    purpose: str | None, expected: bool
) -> None:
    assert calc.is_apartment_partition(wall(), props(purpose=purpose), [LEFT_12, RIGHT_12]) is (
        expected
    )


# ------------------------------------------------------------------ санузлы и шахты


@pytest.mark.parametrize(
    ("zones", "expected"),
    [
        ([LEFT_LIVING, RIGHT_LIVING], "apartment_partition"),  # две жилые комнаты
        ([LEFT_LIVING, RIGHT_BATH], "bathroom_wall"),  # комната и ванная
        ([LEFT_LIVING, RIGHT_WC], "bathroom_wall"),  # комната и туалет
        ([LEFT_LIVING], "shaft_enclosure"),  # комната и пустота
        ([RIGHT_LIVING], "shaft_enclosure"),
        ([LEFT_LIVING, RIGHT_MOP], None),  # квартира и МОП - не квартирная
        ([room("room_apartment", "12", 0.0, 2000.0)], None),  # зона дальше 150 мм: пустота с обеих
    ],
)
def test_classify_partition_bathroom_shaft_and_beacon_row(
    zones: list[calc.PartitionZone], expected: str | None
) -> None:
    assert calc.classify_partition(wall(), props(), zones) == expected


def test_wall_with_both_sides_empty_is_not_a_partition() -> None:
    far = [room("room_apartment", "12", 0.0, 1000.0), room("room_apartment", "12", 5000.0, 6000.0)]
    assert calc.classify_partition(wall(), props(), far) is None


def test_side_is_empty_when_most_probes_are_outside_zones() -> None:
    # Зона справа закрывает только нижнюю треть стены: 1 проба из 3 - зона, 2 - пустота.
    partial = calc.PartitionZone(
        "room_apartment", "12", [[3040.0, 0.0], [6000.0, 0.0], [6000.0, 600.0], [3040.0, 600.0]]
    )
    assert calc.classify_partition(wall(), props(), [LEFT_LIVING, partial]) == "shaft_enclosure"
    # Закрывает две трети (две пробы из трёх): сторона с зоной.
    most = calc.PartitionZone(
        "room_apartment", "12", [[3040.0, 0.0], [6000.0, 0.0], [6000.0, 1200.0], [3040.0, 1200.0]]
    )
    assert calc.classify_partition(wall(), props(), [LEFT_LIVING, most]) == "apartment_partition"


# Перегородка 5600 x 80 мм с выступом-нишей на правом конце: грани 5600, 5520, 500 и 420 мм.
NICHE_SHELL = [
    [0.0, 0.0],
    [5600.0, 0.0],
    [5600.0, 500.0],
    [5520.0, 500.0],
    [5520.0, 80.0],
    [0.0, 80.0],
]


def niche_wall() -> WallsConstruction:
    item = thin()
    item["polygon"] = {"shell": NICHE_SHELL, "holes": []}
    return WallsConstruction.model_validate(item)


def block(apartment_no: str, x1: float, y0: float, y1: float) -> calc.PartitionZone:
    return calc.PartitionZone(
        "room_apartment", apartment_no, [[0.0, y0], [x1, y0], [x1, y1], [0.0, y1]], "living"
    )


def test_long_partition_with_short_empty_niche_face_is_beacon_row() -> None:
    # Комнаты по обе стороны до x=5400: у ниши справа пусто только одна грань в 500 мм из ~12 м.
    zones = [block("12", 6000.0, -3000.0, -40.0), block("12", 5400.0, 120.0, 3000.0)]
    assert calc.classify_partition(niche_wall(), props(), zones) == "apartment_partition"


def test_wall_with_most_face_length_without_zones_is_shaft_enclosure() -> None:
    # Зона только снизу: грани сверху и у ниши (5520 + 500 + 420 мм) без зон - больше половины.
    zones = [block("12", 6000.0, -3000.0, -40.0)]
    assert calc.classify_partition(niche_wall(), props(), zones) == "shaft_enclosure"


@pytest.mark.parametrize(
    ("zones", "basis"),
    [
        ([LEFT_LIVING, RIGHT_BATH], "bathroom_wall"),
        ([LEFT_LIVING], "shaft_enclosure"),
    ],
)
def test_bathroom_and_shaft_walls_get_full_height_with_reason(
    zones: list[calc.PartitionZone], basis: str
) -> None:
    result = sheet(partition=calc.PartitionContext(zones, HEIGHT))
    computed = result.constructions[0].computed
    assert (computed.height_mm, computed.height_basis, computed.sources.height) == (
        2800,
        basis,
        "derived",
    )
    assert computed.wall_area_m2 == pytest.approx(2.0 * 2.8)
    assert result.summary.apartment_partition_count == 0
    assert result.partition_warnings == []


def test_bathroom_wall_has_no_warning_without_answer() -> None:
    result = sheet(partition=calc.PartitionContext([LEFT_LIVING, RIGHT_BATH], None))
    assert result.partition_warnings == []
    assert result.constructions[0].computed.height_basis == "bathroom_wall"


def test_manual_height_and_purpose_beat_bathroom_and_shaft_rules() -> None:
    zones = [LEFT_LIVING, RIGHT_BATH]
    context = calc.PartitionContext(zones, HEIGHT)
    manual = sheet({PARTITION_ID: (props(height_override_mm=1500), False)}, partition=context)
    assert (
        manual.constructions[0].computed.height_mm,
        manual.constructions[0].computed.height_basis,
    ) == (1500, "manual")
    for purpose in ("external", "shaft", "inter_apartment", "mop"):
        assert calc.classify_partition(wall(), props(purpose=purpose), zones) is None
        plain = sheet({PARTITION_ID: (props(purpose=purpose), False)}, partition=context)
        assert plain.constructions[0].computed.height_basis == "sheet"


# ------------------------------------------------------------------ высота и объём


def sheet(
    props_by_key: dict[str, tuple[CadConstructionProps, bool]] | None = None,
    *,
    partition: calc.PartitionContext | None,
    openings: list[dict[str, Any]] | None = None,
) -> calc.SheetResult:
    doc = document([thin()], openings)
    return calc.compute_sheet(doc, props_by_key or {}, NO_LEVELS, partition=partition)


ZONES = [LEFT_12, RIGHT_12]


def test_height_priority_manual_then_beacon_row_then_sheet() -> None:
    context = calc.PartitionContext(ZONES, HEIGHT)
    beacon = sheet(partition=context).constructions[0].computed
    assert (beacon.height_mm, beacon.height_basis, beacon.sources.height) == (
        188,
        "apartment_partition",
        "observed",
    )
    manual = sheet({PARTITION_ID: (props(height_override_mm=300), False)}, partition=context)
    manual_computed = manual.constructions[0].computed
    assert (manual_computed.height_mm, manual_computed.height_basis) == (300, "manual")
    assert manual_computed.sources.height == "manual"
    plain = sheet(partition=calc.PartitionContext(ZONES, None)).constructions[0].computed
    assert (plain.height_mm, plain.height_basis, plain.sources.height) == (2800, "sheet", "derived")
    assert sheet(partition=None).constructions[0].computed.height_mm == 2800


def test_beacon_row_volume_and_area_for_188() -> None:
    result = sheet(partition=calc.PartitionContext(ZONES, HEIGHT))
    computed = result.constructions[0].computed
    assert computed.volume_m3 == pytest.approx(
        2000 * 80 * 188 / 1e9, abs=5e-5
    )  # округление до 4 знаков
    assert computed.wall_area_m2 == pytest.approx(2.0 * 0.188)
    assert result.summary.apartment_partition_count == 1
    assert result.heights.apartment_partition_height is not None
    assert result.heights.apartment_partition_height.height_mm == 188
    assert result.partition_warnings == []


def test_opening_above_part_is_zero_when_beacon_row_is_below_the_door() -> None:
    door = opening("d1", PARTITION_ID, width=800.0)
    with_door = sheet(partition=calc.PartitionContext(ZONES, HEIGHT), openings=[door])
    without = sheet(partition=calc.PartitionContext(ZONES, HEIGHT))
    assert with_door.constructions[0].computed.volume_m3 == pytest.approx(
        without.constructions[0].computed.volume_m3 or 0.0
    )
    assert with_door.constructions[0].computed.wall_area_m2 == pytest.approx(2.0 * 0.188)


def test_monolith_lintels_over_beacon_row_partition_give_no_volume() -> None:
    door = opening("d1", PARTITION_ID, width=800.0)
    door["lintel"] = [[100.0, 0.0], [900.0, 0.0], [900.0, 80.0], [100.0, 80.0]]
    door["lintel_material"] = "monolith"
    result = sheet(partition=calc.PartitionContext(ZONES, HEIGHT), openings=[door])
    assert [g for g in result.totals if g.element == "lintel"] == []


def test_warning_height_unknown_without_answer() -> None:
    result = sheet(partition=calc.PartitionContext(ZONES, None))
    assert [code for code, _ in result.partition_warnings] == ["apartment_partition_height_unknown"]
    assert "перегородки посчитаны на высоту этажа" in result.partition_warnings[0][1]
    assert result.summary.apartment_partition_count == 0
    assert result.heights.apartment_partition_height is None


def test_no_warning_when_there_are_no_candidates_or_no_context() -> None:
    assert sheet(partition=calc.PartitionContext([], None)).partition_warnings == []
    assert sheet(partition=None).partition_warnings == []
    manual = {PARTITION_ID: (props(height_override_mm=188), False)}
    assert sheet(manual, partition=calc.PartitionContext(ZONES, None)).partition_warnings == []


def test_warning_zones_missing_when_answer_accepted_but_no_apartment_zones() -> None:
    result = sheet(partition=calc.PartitionContext([RIGHT_MOP], HEIGHT))
    assert [code for code, _ in result.partition_warnings] == ["apartment_zones_missing"]
    assert result.constructions[0].computed.height_mm == 2800


def test_manual_height_limit_is_100() -> None:
    assert CadConstructionProps(height_override_mm=188).height_override_mm == 188
    with pytest.raises(ValueError, match="greater than or equal to 100"):
        CadConstructionProps(height_override_mm=99)


# ------------------------------------------------------------------ 3D этажа


def build_3d(partition: calc.PartitionContext | None, **prop_fields: Any) -> Any:
    raw = raw_document()
    wall_raw = raw["constructions"][0]
    wall_raw["polygon"] = {"shell": THIN_SHELL, "holes": []}
    wall_raw["thickness_nominal_mm"] = 80.0
    wall_raw["thickness_measured_mm"] = 80.0
    raw["openings"][0]["host_id"] = "aaaaaaaaaaaa"
    extras = raw_extras()
    extras["openings"][0]["leaf"] = [[500.0, 30.0], [1500.0, 30.0], [1500.0, 50.0], [500.0, 50.0]]
    entries = {"aaaaaaaaaaaa": (CadConstructionProps(**prop_fields), False)} if prop_fields else {}
    return f3d.build_floor3d(
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(extras),
        props_by_key=entries,
        overrides=NO_LEVELS,
        project_slab=None,
        hole_decisions={},
        door_zones=[],
        partition=partition,
    )


def wall_of(model: Any) -> Any:
    return next(w for w in model.walls if w.construction_key == "aaaaaaaaaaaa")


def test_floor3d_partition_top_is_base_plus_beacon_row_and_has_no_reaches_top_warning() -> None:
    model = build_3d(calc.PartitionContext(ZONES, HEIGHT))
    partition = wall_of(model)
    assert (partition.z_bottom_mm, partition.z_top_mm) == (BASE, BASE + 188)
    assert partition.height_basis == "apartment_partition"
    # Остальные стены этажа - на высоту листа.
    other = next(w for w in model.walls if w.construction_key == "bbbbbbbbbbbb")
    assert (other.z_top_mm, other.height_basis) == (BASE + 2800, "sheet")
    assert "opening_reaches_wall_top" not in {w.code for w in model.warnings}
    assert model.lintels == []
    (door,) = model.doors
    assert (door.z_bottom_mm, door.z_top_mm) == (BASE, BASE + 188)
    assert model.heights.apartment_partition_height is not None


def test_floor3d_and_volume_agree_for_bathroom_and_shaft_walls() -> None:
    for zones, basis in (
        ([LEFT_LIVING, RIGHT_BATH], "bathroom_wall"),
        ([LEFT_LIVING], "shaft_enclosure"),
    ):
        context = calc.PartitionContext(zones, HEIGHT)
        model = build_3d(context)
        assert (wall_of(model).z_top_mm, wall_of(model).height_basis) == (BASE + 2800, basis)
        assert model.heights.apartment_partition_height is not None
        computed = sheet(partition=context).constructions[0].computed
        assert (computed.height_mm, computed.height_basis) == (2800, basis)
    # Рядом жилые комнаты: маячный ряд и в 3D, и в объёме.
    model = build_3d(calc.PartitionContext([LEFT_LIVING, RIGHT_LIVING], HEIGHT))
    assert (wall_of(model).z_top_mm, wall_of(model).height_basis) == (
        BASE + 188,
        "apartment_partition",
    )


def test_floor3d_manual_height_beats_beacon_row() -> None:
    model = build_3d(calc.PartitionContext(ZONES, HEIGHT), height_override_mm=1200)
    assert (wall_of(model).z_top_mm, wall_of(model).height_basis) == (BASE + 1200, "manual")


def test_floor3d_without_answer_builds_to_sheet_height_and_warns() -> None:
    model = build_3d(calc.PartitionContext(ZONES, None))
    assert (wall_of(model).z_top_mm, wall_of(model).height_basis) == (BASE + 2800, "sheet")
    assert "apartment_partition_height_unknown" in {w.code for w in model.warnings}


def test_floor3d_without_partition_context_is_unchanged() -> None:
    model = build_3d(None)
    assert wall_of(model).z_top_mm == BASE + 2800
    assert {w.code for w in model.warnings} == set()


# ------------------------------------------------------------------ проём над стеной санузла

BATH_ZONES = [LEFT_LIVING, RIGHT_BATH]
BEACON_ZONES = [LEFT_LIVING, RIGHT_LIVING]
# Второй кусок той же линии стен (y от 2300 до 4300): дальше 150 мм от первого куска.
SECOND_ID = "cccccccccccc"
SECOND_SHELL = [[2960.0, 2300.0], [3040.0, 2300.0], [3040.0, 4300.0], [2960.0, 4300.0]]


def second_piece() -> dict[str, Any]:
    item = thin(key=SECOND_ID)
    item["polygon"] = {"shell": SECOND_SHELL, "holes": []}
    return item


def zones_with_bath_second_piece() -> list[calc.PartitionZone]:
    def box(x0: float, x1: float, room_type: str) -> calc.PartitionZone:
        shell = [[x0, 2300.0], [x1, 2300.0], [x1, 4300.0], [x0, 4300.0]]
        return calc.PartitionZone("room_apartment", "12", shell, room_type)

    return [*BEACON_ZONES, box(0.0, 2960.0, "living"), box(3040.0, 6000.0, "bath")]


def test_door_in_bathroom_wall_has_above_part_in_volume_and_lintel_to_wall_top() -> None:
    context = calc.PartitionContext(BATH_ZONES, HEIGHT)
    door = opening("d1", PARTITION_ID, width=800.0)
    computed = sheet(partition=context, openings=[door]).constructions[0].computed
    assert (computed.height_mm, computed.height_basis) == (2800, "bathroom_wall")
    # (2000 x 2800 + 800 x (2800 - 2100)) x 80 мм
    assert computed.volume_m3 == pytest.approx((2000 * 2800 + 800 * 700) * 80 / 1e9, abs=5e-5)
    model = build_3d(context)
    (lintel,) = model.lintels
    assert (lintel.z_bottom_mm, lintel.z_top_mm) == (BASE + 2100, BASE + 2800)


def test_door_in_beacon_row_has_no_above_part_and_no_lintel() -> None:
    context = calc.PartitionContext(BEACON_ZONES, HEIGHT)
    door = opening("d1", PARTITION_ID, width=800.0)
    computed = sheet(partition=context, openings=[door]).constructions[0].computed
    assert computed.volume_m3 == pytest.approx(2000 * 80 * 188 / 1e9, abs=5e-5)
    assert build_3d(context).lintels == []


def test_door_hosted_by_beacon_piece_next_to_bathroom_piece_goes_to_the_bathroom_wall() -> None:
    context = calc.PartitionContext(zones_with_bath_second_piece(), HEIGHT)
    door = opening("d1", PARTITION_ID, width=800.0)
    door["adjacent_ids"] = [PARTITION_ID, SECOND_ID]
    result = calc.compute_sheet(
        document([thin(), second_piece()], [door]), {}, NO_LEVELS, partition=context
    )
    beacon, bath = (c.computed for c in result.constructions)
    assert (beacon.height_basis, bath.height_basis) == ("apartment_partition", "bathroom_wall")
    assert beacon.volume_m3 == pytest.approx(2000 * 80 * 188 / 1e9, abs=5e-5)
    assert bath.volume_m3 == pytest.approx((2000 * 2800 + 800 * 700) * 80 / 1e9, abs=5e-5)


def test_floor3d_door_between_beacon_and_bathroom_pieces_gets_lintel_to_wall_top() -> None:
    raw = raw_document()
    raw["constructions"][0]["polygon"] = {"shell": THIN_SHELL, "holes": []}
    raw["constructions"][0]["thickness_nominal_mm"] = 80.0
    second = {**raw["constructions"][0], "id": SECOND_ID}
    second["polygon"] = {"shell": SECOND_SHELL, "holes": []}
    raw["constructions"].append(second)
    raw["openings"][0]["adjacent_ids"] = ["aaaaaaaaaaaa", SECOND_ID]
    zones = zones_with_bath_second_piece()
    model = f3d.build_floor3d(
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(raw_extras()),
        props_by_key={},
        overrides=NO_LEVELS,
        project_slab=None,
        hole_decisions={},
        door_zones=[],
        partition=calc.PartitionContext(zones, HEIGHT),
    )
    assert wall_of(model).z_top_mm == BASE + 188
    (lintel,) = model.lintels
    assert (lintel.z_bottom_mm, lintel.z_top_mm) == (BASE + 2100, BASE + 2800)
    assert lintel.host_id == SECOND_ID


# ------------------------------------------------------------------ якорь вопроса

POLIGRAN_TEXT = (
    "Внутриквартирные перегородки выполняются подрядчиком в виде выкладки «Маячный ряд» "
    "из камня перегородочного полнотелого «ПОЛИГРАН 80» (ТУ 5741-001) высотой 188 мм."
)


def test_question_is_in_the_catalog_with_range_100_3000() -> None:
    question = question_by_code(CODE.APARTMENT_PARTITION_HEIGHT)
    assert CODE.APARTMENT_PARTITION_HEIGHT.value == "apartment_partition_height"
    assert question.receiver_param == "apartment_partition_height_mm"
    assert (question.min_mm, question.max_mm) == (100, 3000)
    assert question.assumption is None


def test_anchor_finds_188_and_ignores_80_from_the_stone_name() -> None:
    result = result_of([page(POLIGRAN_TEXT, "АР")], CODE.APARTMENT_PARTITION_HEIGHT)
    assert result.status.value == "found"
    assert [c.value.numbers for c in result.candidates] == [(188,)]
    assert "188 мм" in result.candidates[0].quote


def test_anchor_needs_the_partition_context() -> None:
    text = "Высота этажа принята 3000 мм, высотой 2700 мм."
    result = result_of([page(text, "АР")], CODE.APARTMENT_PARTITION_HEIGHT)
    assert result.status.value == "not_found"


# ------------------------------------------------------------------ чтение принятого ответа


async def _answer(
    session: AsyncSession,
    project_id: str,
    *,
    number: int | None,
    source: str = "document",
    code: str = "apartment_partition_height",
    section: str | None = None,
) -> uuid.UUID:
    row = DocQuestionAnswer(
        project_id=uuid.UUID(project_id),
        question_code=code,
        source=source,
        value=None
        if number is None
        else {"kind": "length_mm", "display": str(number), "numbers": [number]},
        file_name="АР ПЗ.pdf" if source == "document" else None,
        page_index=4 if source == "document" else None,
        quote="высотой 188 мм" if source == "document" else None,
        catalog_version="test",
        confirmed_by=DEV_USER_ID,
        scope_section=section,  # разные области - несколько ответов одного вопроса
    )
    session.add(row)
    await session.commit()
    return row.id


async def test_apartment_partition_height_reads_the_accepted_answer(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context()) as api:
        project_id = await make_project(api)
    pid = uuid.UUID(project_id)
    assert await cad_partitions.apartment_partition_height(db_session, project_id=pid) is None

    # Норматив-допущение, «в проекте нет» и чужой вопрос ответом не считаются.
    await _answer(db_session, project_id, number=150, source="norm_assumption", section="n1")
    await _answer(db_session, project_id, number=None, source="not_in_project", section="n2")
    await _answer(db_session, project_id, number=999, code="slab_thickness")
    assert await cad_partitions.apartment_partition_height(db_session, project_id=pid) is None

    answer_id = await _answer(db_session, project_id, number=188, section="1")
    height = await cad_partitions.apartment_partition_height(db_session, project_id=pid)
    assert height is not None
    assert (height.height_mm, height.source, height.answer_id) == (188, "observed", answer_id)
    assert (height.file_name, height.page_index, height.quote) == (
        "АР ПЗ.pdf",
        4,
        "высотой 188 мм",
    )
    manual = await _answer(db_session, project_id, number=190, source="manual", section="2")
    latest = await cad_partitions.apartment_partition_height(db_session, project_id=pid)
    assert latest is not None
    assert (latest.height_mm, latest.source, latest.answer_id) == (190, "manual", manual)
