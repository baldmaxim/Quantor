"""«Отделка квартир»: вопрос к документации, чтение ответа, двери, 3D, итоги, отделка. Синтетика."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dev import DEV_USER_ID
from app.contracts.doc_questions import ManualValueIn
from app.models import DocQuestionAnswer
from app.services import cad_constructions as calc
from app.services import cad_partitions, doc_answers
from app.services.cad_finishes import build_finish_sheet
from app.services.consistency.doc_questions import (
    DocQuestionCode,
    DocValueKind,
    ExtractorKind,
    question_by_code,
)
from tests.conftest import make_context
from tests.doc_questions_support import make_project
from tests.test_cad_apartment_partitions import (
    BATH_ZONES,
    BEACON_ZONES,
    HEIGHT,
    LEFT_12,
    LEFT_LIVING,
    PARTITION_ID,
    RIGHT_12,
    RIGHT_13,
    RIGHT_MOP,
    build_3d,
    sheet,
    thin,
)
from tests.test_cad_constructions_calc import document, opening
from tests.test_cad_finishes import (
    PAINT,
    REVISION,
    _body,
    _sheet,
    _template,
    _templates_url,
    _zone,
    _zones_url,
)
from tests.test_cad_qa import BROKEN_PDF, _upload_calibrated, cad_settings
from tests.test_cad_zones import _room
from tests.test_consistency_doc_search import page, result_of

CODE = DocQuestionCode
ANSWER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
WITHOUT = calc.ApartmentFinishing("without_finish", "observed", ANSWER_ID)
WITH = calc.ApartmentFinishing("with_finish", "manual", ANSWER_ID)


def ctx(
    zones: list[calc.PartitionZone], finishing: calc.ApartmentFinishing | None
) -> calc.PartitionContext:
    return calc.PartitionContext(zones, HEIGHT, finishing=finishing)


# ------------------------------------------------------------------ вопрос и экстрактор


def test_question_is_in_the_catalog_with_options() -> None:
    question = question_by_code(CODE.APARTMENT_FINISHING)
    assert CODE.APARTMENT_FINISHING.value == "apartment_finishing"
    assert question.receiver_param == "apartment_finishing"
    assert question.value_kind is DocValueKind.ENUM
    assert question.extractor is ExtractorKind.APARTMENT_FINISHING
    assert [(o.code, o.label) for o in question.options] == [
        ("without_finish", "Без отделки (Shell&Core)"),
        ("with_finish", "С отделкой"),
    ]
    assert [o.code for o in question_by_code(CODE.SPRINKLER_MODEL).options] == [
        "rosette_down",
        "rosette_up",
    ]
    assert question_by_code(CODE.CLEAR_HEIGHT).options == ()


@pytest.mark.parametrize(
    "text",
    [
        "Отделка квартир выполняется собственником после ввода объекта в эксплуатацию.",
        "По заданию предусматривается отделка квартир: Shell&core - 100%.",
        "Квартиры сдаются в предчистовой отделке.",
        "Квартиры передаются в варианте White Box.",
        "Квартиры сдаются без чистовой отделки.",
    ],
)
def test_extractor_finds_without_finish(text: str) -> None:
    result = result_of([page(text, "АР")], CODE.APARTMENT_FINISHING)
    assert result.status.value == "found"
    candidate = result.candidates[0]
    assert candidate.value.kind is DocValueKind.ENUM
    assert candidate.value.code == "without_finish"
    assert candidate.value.numbers == ()
    assert candidate.value.display


@pytest.mark.parametrize(
    "text",
    [
        "Квартиры передаются с чистовой отделкой.",
        "Квартиры сдаются под ключ.",
    ],
)
def test_extractor_finds_with_finish(text: str) -> None:
    result = result_of([page(text, "АР")], CODE.APARTMENT_FINISHING)
    assert result.status.value == "found"
    assert result.candidates[0].value.code == "with_finish"


@pytest.mark.parametrize(
    "text",
    [
        "Высота этажа принята 3000 мм.",
        # отделка коммерческих помещений - не ответ про квартиры
        "Предусматривается отделка коммерческих помещений: Shell&core - 100%.",
    ],
)
def test_extractor_does_not_find_without_apartment_sentence(text: str) -> None:
    result = result_of([page(text, "АР")], CODE.APARTMENT_FINISHING)
    assert result.status.value == "not_found"


def test_extractor_takes_apartment_sentence_next_to_commercial_one() -> None:
    text = (
        "Для коммерческих помещений предусмотрено Shell&core - 100%. "
        "Для квартир предусмотрено Shell&core - 100%."
    )
    result = result_of([page(text, "АР")], CODE.APARTMENT_FINISHING)
    assert [c.value.code for c in result.candidates] == ["without_finish"]
    assert "квартир" in result.candidates[0].quote


# ------------------------------------------------------------------ проверка ответа


def _manual(code: str | None, numbers: list[int] | None = None) -> dict[str, Any]:
    return doc_answers.manual_value(
        question_by_code(
            CODE.APARTMENT_FINISHING
            if code in (None, "without_finish", "with_finish", "x")
            else CODE.SPRINKLER_MODEL
        ),
        ManualValueIn(code=code, numbers=numbers or []),
        "текст",
    )


def test_manual_value_finishing_needs_a_known_code() -> None:
    assert _manual("without_finish")["code"] == "without_finish"
    assert _manual("with_finish")["code"] == "with_finish"
    for bad in (None, "x"):
        with pytest.raises(HTTPException) as error:
            _manual(bad)
        assert error.value.status_code == 422
        assert "without_finish / with_finish" in str(error.value.detail)
    with pytest.raises(HTTPException):
        _manual("without_finish", [5])


def test_manual_value_rosette_codes_still_work_and_code_is_optional() -> None:
    sprinkler = question_by_code(CODE.SPRINKLER_MODEL)
    for code in ("rosette_down", "rosette_up", None):
        value = doc_answers.manual_value(sprinkler, ManualValueIn(code=code), "СВН")
        assert value["code"] == code
    with pytest.raises(HTTPException) as error:
        doc_answers.manual_value(sprinkler, ManualValueIn(code="without_finish"), "СВН")
    assert "rosette_down / rosette_up" in str(error.value.detail)


async def test_questions_view_gives_options(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context()) as api:
        project_id = await make_project(api)
    questions, _ = await doc_answers.questions_view(db_session, project_id=uuid.UUID(project_id))
    options = {q.code: [(o.code, o.label) for o in q.options] for q in questions}
    assert options["apartment_finishing"] == [
        ("without_finish", "Без отделки (Shell&Core)"),
        ("with_finish", "С отделкой"),
    ]
    assert options["sprinkler_model"] == [
        ("rosette_down", "Розеткой вниз"),
        ("rosette_up", "Розеткой вверх"),
    ]
    assert options["clear_height"] == []


# ------------------------------------------------------------------ чтение ответа


async def _finishing_answer(
    session: AsyncSession,
    project_id: str,
    *,
    code: str | None,
    source: str = "document",
    section: str | None = None,
) -> uuid.UUID:
    row = DocQuestionAnswer(
        project_id=uuid.UUID(project_id),
        question_code="apartment_finishing",
        source=source,
        value=None
        if source == "not_in_project"
        else {"kind": "enum", "display": "фраза", "numbers": [], "code": code},
        file_name="АР ПЗ.pdf" if source == "document" else None,
        page_index=41 if source == "document" else None,
        quote="отделка квартир: Shell&core" if source == "document" else None,
        catalog_version="test",
        confirmed_by=DEV_USER_ID,
        scope_section=section,
    )
    session.add(row)
    await session.commit()
    return row.id


async def test_apartment_finishing_reads_the_accepted_answer(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context()) as api:
        project_id = await make_project(api)
    pid = uuid.UUID(project_id)
    assert await cad_partitions.apartment_finishing(db_session, project_id=pid) is None
    assert await cad_partitions.apartment_without_finish(db_session, project_id=pid) is False

    # Норматив-допущение, «в проекте нет», чужой код и чужой вопрос ответом не считаются.
    await _finishing_answer(db_session, project_id, code=None, source="not_in_project", section="1")
    await _finishing_answer(
        db_session, project_id, code="without_finish", source="norm_assumption", section="2"
    )
    await _finishing_answer(db_session, project_id, code="rosette_up", section="3")
    assert await cad_partitions.apartment_finishing(db_session, project_id=pid) is None

    answer_id = await _finishing_answer(db_session, project_id, code="without_finish", section="4")
    got = await cad_partitions.apartment_finishing(db_session, project_id=pid)
    assert got is not None and got.without_finish is True
    assert (got.code, got.source, got.answer_id) == ("without_finish", "observed", answer_id)
    assert (got.file_name, got.page_index, got.quote) == (
        "АР ПЗ.pdf",
        41,
        "отделка квартир: Shell&core",
    )
    assert await cad_partitions.apartment_without_finish(db_session, project_id=pid) is True

    # Самый поздний подтверждённый ответ выигрывает.
    manual = await _finishing_answer(
        db_session, project_id, code="with_finish", source="manual", section="5"
    )
    latest = await cad_partitions.apartment_finishing(db_session, project_id=pid)
    assert latest is not None
    assert (latest.code, latest.source, latest.answer_id) == ("with_finish", "manual", manual)
    assert latest.without_finish is False
    assert await cad_partitions.apartment_without_finish(db_session, project_id=pid) is False


# ------------------------------------------------------------------ внутриквартирные двери

# Контур проёма в оси перегородки (x = 3000), касается зон слева и справа.
LINTEL = [[2960.0, 800.0], [3040.0, 800.0], [3040.0, 1600.0], [2960.0, 1600.0]]


def door_doc(
    *,
    host: str = PARTITION_ID,
    adjacent: list[str] | None = None,
    lintel: list[list[float]] | None = LINTEL,
    kind: str = "door",
    status: str = "ok",
) -> Any:
    door = opening("d1", host, kind=kind, status=status, width=800.0)
    door["adjacent_ids"] = [host] if adjacent is None else adjacent
    door["lintel"] = lintel
    return document([thin()], [door])


def interior(
    zones: list[calc.PartitionZone],
    classes: dict[str, Any] | None = None,
    **kwargs: Any,
) -> frozenset[str]:
    return calc.interior_apartment_door_ids(
        door_doc(**kwargs),
        {PARTITION_ID: "bathroom_wall"} if classes is None else classes,
        zones,
    )


def test_bathroom_door_is_interior() -> None:
    assert interior(BATH_ZONES) == {"d1"}


@pytest.mark.parametrize("basis", ["apartment_partition", "bathroom_wall", "shaft_enclosure"])
def test_door_in_any_partition_class_is_interior(basis: str) -> None:
    assert interior(BEACON_ZONES, {PARTITION_ID: basis}) == {"d1"}


def test_entrance_door_between_apartment_and_mop_is_not_interior() -> None:
    # хозяин - не перегородка (стена квартиры), откос - перегородка, проём касается МОП
    assert interior([LEFT_12, RIGHT_MOP], host="other", adjacent=["other", PARTITION_ID]) == set()
    assert interior([LEFT_12, RIGHT_MOP]) == set()


def test_door_between_two_apartments_is_not_interior() -> None:
    assert interior([LEFT_12, RIGHT_13]) == set()
    assert interior([LEFT_12, RIGHT_12]) == {"d1"}


def test_balcony_door_is_not_interior() -> None:
    balcony = calc.PartitionZone("room_apartment", "12", RIGHT_12.shell, "balcony")
    assert interior([LEFT_LIVING, balcony]) == set()


def test_door_without_partition_jamb_is_not_interior() -> None:
    assert interior(BATH_ZONES, {}) == set()
    assert interior(BATH_ZONES, {"other": "bathroom_wall"}) == set()


def test_only_doors_count_and_status_no_data_is_included_without_lintel() -> None:
    assert interior(BATH_ZONES, kind="gap") == set()
    assert interior(BATH_ZONES, kind="window") == set()
    # дверь без разрыва: контура проёма нет - берётся контур хозяина
    assert interior(BATH_ZONES, status="no_data", lintel=None) == {"d1"}


def test_no_zones_gives_nothing() -> None:
    assert interior([]) == set()


# ------------------------------------------------------------------ итоги конструкций


def one_door() -> list[dict[str, Any]]:
    door = opening("d1", PARTITION_ID, width=800.0)
    door["lintel"] = LINTEL
    return [door]


def test_totals_count_doors_and_exclude_interior_ones_without_finish() -> None:
    plain = sheet(partition=ctx(BATH_ZONES, None), openings=one_door())
    without = sheet(partition=ctx(BATH_ZONES, WITHOUT), openings=one_door())
    with_finish = sheet(partition=ctx(BATH_ZONES, WITH), openings=one_door())
    assert (plain.summary.door_count, plain.summary.doors_excluded_without_finish) == (1, 0)
    assert (with_finish.summary.door_count, with_finish.summary.doors_excluded_without_finish) == (
        1,
        0,
    )
    assert (without.summary.door_count, without.summary.doors_excluded_without_finish) == (0, 1)
    # объёмы кладки и перемычки не меняются
    assert [t.model_dump() for t in without.totals] == [t.model_dump() for t in plain.totals]
    assert without.constructions[0].computed.volume_m3 == plain.constructions[0].computed.volume_m3


def test_entrance_door_stays_in_door_count_without_finish() -> None:
    result = sheet(partition=ctx([LEFT_12, RIGHT_MOP], WITHOUT), openings=one_door())
    assert (result.summary.door_count, result.summary.doors_excluded_without_finish) == (1, 0)


def codes(result: calc.SheetResult) -> list[str]:
    return [code for code, _ in result.partition_warnings]


def test_without_finish_warning_is_added_only_for_that_answer() -> None:
    text = (
        "Квартиры без отделки (ответ к документации): внутриквартирные двери не учитываются - "
        "1 шт., отделка квартир не считается."
    )
    without = sheet(partition=ctx(BATH_ZONES, WITHOUT), openings=one_door())
    assert ("apartment_without_finish", text) in without.partition_warnings
    for finishing in (None, WITH):
        other = sheet(partition=ctx(BATH_ZONES, finishing), openings=one_door())
        assert "apartment_without_finish" not in codes(other)
    assert "apartment_without_finish" not in codes(sheet(partition=None, openings=one_door()))


# ------------------------------------------------------------------ 3D


def test_floor3d_has_no_leaf_for_interior_door_without_finish() -> None:
    without = build_3d(ctx(BATH_ZONES, WITHOUT))
    assert without.doors == []
    # перемычка и надпроёмная часть в стене санузла на полную высоту остаются
    assert len(without.lintels) == 1
    warning = next(w for w in without.warnings if w.code == "apartment_without_finish")
    assert "1 шт." in warning.message


@pytest.mark.parametrize("finishing", [None, WITH])
def test_floor3d_keeps_leaf_without_answer_or_with_finish(
    finishing: calc.ApartmentFinishing | None,
) -> None:
    model = build_3d(ctx(BATH_ZONES, finishing))
    assert len(model.doors) == 1
    assert len(model.lintels) == 1
    assert "apartment_without_finish" not in [w.code for w in model.warnings]
    assert len(build_3d(None).doors) == 1


# ------------------------------------------------------------------ отделка


def test_finish_sheet_skips_apartment_zones_without_finish_but_keeps_mop() -> None:
    template = _template_for_types()
    apartment = _zone(room_type="living")
    mop = _zone(kind="room_mop", room_type="corridor")
    explicit = _zone(room_type="hall", template_id=template.id)
    zones = [apartment, mop, explicit]

    before = _sheet(zones, [template])
    assert {z.zone_id for z in before.zones if z.layers} == {apartment.id, mop.id, explicit.id}

    after = build_sheet(zones, [template], without_finish=True)
    rows = {row.zone_id: row for row in after.zones}
    assert rows[apartment.id].layers == [] and rows[apartment.id].template_id is None
    assert rows[explicit.id].layers == [] and rows[explicit.id].template_id is None
    assert rows[mop.id].layers != []
    warnings = {w.code: w.zone_ids for w in after.warnings}
    assert set(warnings["apartment_without_finish"]) == {apartment.id, explicit.id}
    assert "no_template" not in warnings
    # в итоги входит только МОП; тип «гостиная» / «прихожая» в сводке по типам не показан
    assert all(t.zone_count == 1 for t in after.totals)
    assert [r.room_type for r in after.by_room_type] == ["corridor"]


def test_finish_sheet_without_answer_is_unchanged() -> None:
    template = _template_for_types()
    zones = [_zone(room_type="living"), _zone(kind="room_mop", room_type="corridor")]
    assert build_sheet(zones, [template], without_finish=False) == _sheet(zones, [template])
    assert "apartment_without_finish" not in [w.code for w in _sheet(zones, [template]).warnings]


def _template_for_types() -> Any:
    return _template(room_types=["living", "hall", "corridor"], ceiling=[PAINT])


def build_sheet(zones: list[Any], templates: list[Any], *, without_finish: bool) -> Any:
    return build_finish_sheet(
        revision_id=REVISION,
        page_index=0,
        zones=zones,
        templates=templates,
        levels_wall_height_mm=2800,
        apartment_without_finish=without_finish,
    )


async def test_mass_assign_skips_apartment_zones_without_finish(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        zones_url = await _zones_url(project_id)
        template = (await api.post(_templates_url(project_id), json=_body())).json()
        room = (await api.post(zones_url, json=_room(revision_id))).json()
        mop = (
            await api.post(zones_url, json=_room(revision_id, kind="room_mop", apartment_no=None))
        ).json()
        assign = f"/api/v1/projects/{project_id}/cad/zones/finish-assign"
        body = {"zone_ids": [room["id"], mop["id"]], "template_id": template["id"]}

        # без ответа - обе зоны получают шаблон
        assert (await api.post(assign, json=body)).json()["assigned"] == 2

        await _finishing_answer(db_session, project_id, code="without_finish")
        result = (await api.post(assign, json=body)).json()
        assert result["assigned"] == 1 and result["skipped_count"] == 1
        assert result["skipped"] == [{"zone_id": room["id"], "reason": "apartment_without_finish"}]

        # снять явное назначение можно и у квартиры
        cleared = await api.post(assign, json={"zone_ids": [room["id"]], "template_id": None})
        assert cleared.json()["assigned"] == 1 and cleared.json()["skipped_count"] == 0

        # ведомость: квартира уходит в предупреждение, слоёв нет
        sheet_url = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/finishes"
        response = await api.get(sheet_url, params={"page_index": 0})
        assert response.status_code == 200, response.text
        data = response.json()
        flagged = {w["code"]: w["zone_ids"] for w in data["warnings"]}
        assert flagged["apartment_without_finish"] == [room["id"]]
        row = next(z for z in data["zones"] if z["zone_id"] == room["id"])
        assert row["layers"] == [] and row["template_id"] is None
