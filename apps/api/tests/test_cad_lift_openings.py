"""Двери шахт лифтов: распознавание разрывов по зонам листа, высота из принятого ответа, вопрос.

Данные - с листа ЖК «Знаки» (стр. 82): лифтовый холл ≈ (18268, 12451)-(21263, 16747) мм, разрывы
у лифтов шириной 1300 и 1000 мм с центром x = 21167, направление (0, 1), толщина стены 200 мм;
за ними зоны нет. Ожидаемые числа выписаны руками: высота этажа 3000, плита 200 -> стена 2800.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import cad_constructions as calc
from app.services import cad_lift_openings as lift
from app.services import cad_partitions
from app.services.consistency.doc_questions import DocQuestionCode, question_by_code
from tests.conftest import make_context
from tests.doc_questions_support import make_project
from tests.test_cad_apartment_partitions import _answer as answer_row
from tests.test_cad_constructions_calc import NO_LEVELS, construction, document, opening
from tests.test_consistency_doc_search import page, result_of

CODE = DocQuestionCode
ANSWER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
OBSERVED = calc.PartitionHeight(2400, "observed", ANSWER_ID, "ТЗ.pdf", 7, "1200*2400")
MANUAL = calc.PartitionHeight(2300, "manual", ANSWER_ID, None, None, None)

HOST = "wall00000001"


def rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


HALL = calc.PartitionZone(
    "room_mop", None, rect(18268.0, 12451.0, 21263.0, 16747.0), room_type="lift_hall"
)
CORRIDOR = calc.PartitionZone(
    "room_mop", None, rect(21300.0, 12451.0, 25000.0, 16747.0), room_type="corridor"
)
APARTMENT = calc.PartitionZone(
    "room_apartment", "12", rect(30000.0, 12000.0, 36000.0, 17000.0), room_type="apt_other"
)


def gap(key: str, x: float, y: float, *, width: float = 1300.0, **extra: Any) -> dict[str, Any]:
    item = opening(key, HOST, kind="gap", status="no_data", width=width)
    item["center"] = [x, y]
    item["thickness_mm"] = 200.0
    item.update(extra)
    return item


def extras(*ids: str, direction: tuple[float, float] = (0.0, 1.0)) -> WallsFloorExtras:
    return WallsFloorExtras.model_validate(
        {"openings": [{"id": key, "direction": list(direction)} for key in ids]}
    )


LIFT_1 = gap("gap_lift_1", 21167.0, 13198.0)
LIFT_2 = gap("gap_lift_2", 21167.0, 15797.0, width=1000.0)


def sheet_document(*openings: dict[str, Any]) -> Any:
    return document([construction(HOST)], list(openings))


def apply(
    zones: list[calc.PartitionZone],
    height: calc.PartitionHeight | None,
    *openings: dict[str, Any],
) -> lift.LiftOpenings:
    doc = sheet_document(*openings)
    return lift.apply_lift_door_heights(
        doc,
        extras(*(item["id"] for item in openings)),
        calc.PartitionContext(zones=zones, lift_door_height=height),
    )


def heights(result: lift.LiftOpenings) -> dict[str, tuple[int | None, str | None]]:
    return {o.id: (o.opening_height_mm, o.opening_height_status) for o in result.document.openings}


# ------------------------------------------------------------------ распознавание


def test_gap_on_the_lift_hall_border_with_nothing_behind_gets_the_accepted_height() -> None:
    result = apply([HALL], OBSERVED, LIFT_1, LIFT_2)
    assert heights(result) == {
        "gap_lift_1": (2400, "observed"),
        "gap_lift_2": (2400, "observed"),
    }
    assert result.lift_gap_ids == {"gap_lift_1", "gap_lift_2"}
    assert result.warnings == []


def test_manual_answer_gives_manual_source() -> None:
    result = apply([HALL], MANUAL, LIFT_1)
    assert heights(result) == {"gap_lift_1": (2300, "manual")}


def test_hall_side_may_be_either_side_of_the_gap() -> None:
    mirrored = gap("g", 21167.0, 13198.0)
    result = lift.apply_lift_door_heights(
        sheet_document(mirrored),
        extras("g"),
        calc.PartitionContext(
            zones=[
                calc.PartitionZone(
                    "room_mop",
                    None,
                    rect(21300.0, 12451.0, 24000.0, 16747.0),
                    room_type="lift_hall",
                )
            ],
            lift_door_height=OBSERVED,
        ),
    )
    assert heights(result) == {"g": (2400, "observed")}


def test_gap_between_the_lift_hall_and_a_corridor_is_not_a_lift_door() -> None:
    result = apply([HALL, CORRIDOR], OBSERVED, LIFT_1)
    assert heights(result) == {"gap_lift_1": (None, None)}
    assert result.lift_gap_ids == frozenset()
    assert result.warnings == []


def test_gap_inside_an_apartment_is_not_a_lift_door() -> None:
    inside = gap("g", 33000.0, 14000.0)
    result = apply([HALL, APARTMENT], OBSERVED, inside)
    assert heights(result) == {"g": (None, None)}


def test_gap_far_from_the_hall_is_not_a_lift_door() -> None:
    far = gap("g", 27000.0, 14000.0)
    assert heights(apply([HALL], OBSERVED, far)) == {"g": (None, None)}


def test_door_blocks_and_gaps_without_direction_are_left_alone() -> None:
    door = opening("door1", HOST, kind="door")
    door["center"] = [21167.0, 13198.0]
    doc = sheet_document(door, LIFT_1)
    result = lift.apply_lift_door_heights(
        doc,
        WallsFloorExtras.model_validate({"openings": [{"id": "door1", "direction": [0.0, 1.0]}]}),
        calc.PartitionContext(zones=[HALL], lift_door_height=OBSERVED),
    )
    assert heights(result) == {"door1": (None, None), "gap_lift_1": (None, None)}


def test_own_height_from_walls_json_beats_the_accepted_answer() -> None:
    own = gap("g", 21167.0, 13198.0, opening_height_mm=2200, opening_height_status="observed")
    assert heights(apply([HALL], MANUAL, own)) == {"g": (2200, "observed")}


# ------------------------------------------------------------------ ответа нет


def test_no_answer_gives_the_warning_and_leaves_the_gap_without_height() -> None:
    result = apply([HALL], None, LIFT_1, LIFT_2)
    assert heights(result) == {"gap_lift_1": (None, None), "gap_lift_2": (None, None)}
    assert [code for code, _message in result.warnings] == ["lift_door_height_unknown"]


def test_no_lift_gaps_means_no_warning_and_no_zones_means_nothing_to_do() -> None:
    assert apply([HALL, CORRIDOR], None, LIFT_1).warnings == []
    result = lift.apply_lift_door_heights(
        sheet_document(LIFT_1), extras("gap_lift_1"), calc.PartitionContext(zones=[])
    )
    assert result.warnings == [] and heights(result) == {"gap_lift_1": (None, None)}
    assert (
        lift.apply_lift_door_heights(sheet_document(LIFT_1), extras("gap_lift_1"), None).warnings
        == []
    )


# ------------------------------------------------------------------ объём


def test_volume_counts_the_part_above_the_lift_door_only_with_the_answer() -> None:
    with_answer = apply([HALL], OBSERVED, LIFT_1)
    without = apply([HALL], None, LIFT_1)
    computed_with = calc.compute_sheet(with_answer.document, {}, NO_LEVELS)
    computed_without = calc.compute_sheet(without.document, {}, NO_LEVELS)
    one = computed_with.constructions[0].computed
    # 5000 x 200 x 2800 + проём 1300 x 200 x (2800 - 2400) надпроёмной части.
    assert one.volume_m3 == pytest.approx((5000 * 200 * 2800 + 1300 * 200 * 400) / 1e9)
    assert one.sources.gap_opening_height == "observed"
    assert "opening_no_data" not in one.warnings
    assert computed_with.summary.unaccounted_gap_openings == 0
    assert computed_without.summary.unaccounted_gap_openings == 1
    assert "opening_no_data" in computed_without.constructions[0].computed.warnings


# ------------------------------------------------------------------ вопрос к документации


def test_question_is_in_the_catalog_with_range_1900_3000() -> None:
    question = question_by_code(CODE.LIFT_DOOR_HEIGHT)
    assert question.receiver_param == "lift_door_opening_height_mm"
    assert (question.min_mm, question.max_mm) == (1900, 3000)
    assert question.context_required is True
    assert question.assumption is None


def test_question_extracts_the_height_from_the_width_by_height_pair() -> None:
    text = (
        "Лифты. Характеристики. Дверь (ширина х высота), мм 1200*2400 для лифта "
        "грузоподъёмностью 1000 кг."
    )
    result = result_of([page(text, "АР")], CODE.LIFT_DOOR_HEIGHT)
    assert result.status.value == "found"
    assert result.candidates[0].value.numbers == (2400,)
    assert all(c.value.numbers != (1200,) for c in result.candidates)


def test_question_reads_a_plain_height_near_the_lift_door_anchor() -> None:
    text = "Проём двери шахты лифта высотой 2100 мм в чистоте."
    result = result_of([page(text, "АР")], CODE.LIFT_DOOR_HEIGHT)
    assert result.candidates[0].value.numbers == (2100,)


def test_question_needs_the_lift_context() -> None:
    text = "Дверь (ширина х высота), мм 1200*2400"
    assert result_of([page(text, "АР")], CODE.LIFT_DOOR_HEIGHT).status.value == "not_found"


def test_question_ignores_a_height_outside_the_range() -> None:
    text = "Дверь шахты лифта высотой 1500 мм."
    assert result_of([page(text, "АР")], CODE.LIFT_DOOR_HEIGHT).status.value == "not_found"


# ------------------------------------------------------------------ чтение принятого ответа


async def test_lift_door_height_reads_the_accepted_answer_inside_the_range(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context()) as api:
        project_id = await make_project(api)
    pid = uuid.UUID(project_id)
    code = CODE.LIFT_DOOR_HEIGHT.value
    assert await cad_partitions.lift_door_height(db_session, project_id=pid) is None

    # Вне 1900-3000, норматив-допущение и ответ маячного ряда не считаются.
    await answer_row(db_session, project_id, number=1500, code=code, section="a")
    await answer_row(db_session, project_id, number=3500, code=code, section="b")
    await answer_row(db_session, project_id, number=2400, source="norm_assumption", code=code)
    await answer_row(db_session, project_id, number=2400, code="apartment_partition_height")
    assert await cad_partitions.lift_door_height(db_session, project_id=pid) is None

    answer_id = await answer_row(db_session, project_id, number=2400, code=code, section="c")
    height = await cad_partitions.lift_door_height(db_session, project_id=pid)
    assert height is not None
    assert (height.height_mm, height.source, height.answer_id) == (2400, "observed", answer_id)
    manual = await answer_row(
        db_session, project_id, number=2300, source="manual", code=code, section="d"
    )
    latest = await cad_partitions.lift_door_height(db_session, project_id=pid)
    assert latest is not None
    assert (latest.height_mm, latest.source, latest.answer_id) == (2300, "manual", manual)
