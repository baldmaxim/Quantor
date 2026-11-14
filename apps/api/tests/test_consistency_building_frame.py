"""Каркас здания и проверки комплектности (ADR-0043, С2): чистые функции, без базы.

Только синтетика: паспорта листов собираются в тесте.
"""

from __future__ import annotations

from app.services.consistency.building_frame import (
    LevelPoint,
    NodeKey,
    NodeKind,
    PassportRow,
    build_frame,
    derived_heights,
    level_rank,
    passport_levels,
)
from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.doc_questions import DocQuestionCode, question_by_code
from app.services.consistency.doc_search import DocSearchPage, search_page
from app.services.consistency.frame_checks import (
    AnswerView,
    CheckCode,
    CheckStatus,
    LevelView,
    check_ar_plan_per_level,
    check_level_elevations,
    check_level_sequence,
    check_pz_floor_height,
    check_scheme_per_system,
    run_frame_checks,
)
from app.services.consistency.sheet_passport import PassportCandidate


def _passport(
    pid: str,
    *,
    mark: str | None = "АР",
    kind: str | None = "floor_plan",
    building: str | None = "1",
    section: str | None = None,
    levels: tuple[int, int] | None = None,
    named: str | None = None,
    elevation: float | None = None,
    title: str | None = None,
) -> PassportRow:
    low, high = levels if levels is not None else (None, None)
    level_from = named if named else (None if low is None else f"{low} этаж")
    level_to = named if named else (None if high is None else f"{high} этаж")
    return PassportRow(
        id=pid,
        file_name=f"{pid}.pdf",
        page_index=0,
        section_mark=mark,
        sheet_kind=kind,
        building=building,
        section=section,
        level_from=level_from,
        level_to=level_to,
        level_from_ordinal=low,
        level_to_ordinal=high,
        elevation_m=elevation,
        title=title,
    )


def _level(
    lid: str,
    ordinal: int | None,
    *,
    code: str | None = None,
    building: str | None = "1",
    section: str | None = None,
    elevation: float | None = None,
    height: float | None = None,
    values: tuple[float, ...] = (),
) -> LevelView:
    return LevelView(
        id=lid,
        building=building,
        section=section,
        code=code or f"{ordinal} этаж",
        ordinal=ordinal,
        elevation_m=elevation,
        height_m=height,
        elevation_values=values,
    )


def _answer(code: str, number: int, *, building: str | None = None) -> AnswerView:
    return AnswerView(
        id=f"a-{code}",
        question_code=code,
        scope_building=building,
        scope_section=None,
        number=number,
        value_text=str(number),
        file_name="ПЗ.pdf",
        page_index=3,
    )


# --------------------------------------------------------------------------- сборка


def test_typical_plan_expands_its_range_and_skips_floor_zero() -> None:
    row = _passport("p", levels=(-1, 3))
    assert [ordinal for _, ordinal in passport_levels(row)] == [-1, 1, 2, 3]
    assert passport_levels(_passport("r", named="кровля")) == [("кровля", None)]


def test_build_frame_makes_building_section_and_levels_from_plans_only() -> None:
    nodes = build_frame(
        [
            _passport("typ", levels=(2, 4), elevation=6.0),
            _passport("p1", levels=(1, 1), elevation=0.0),
            _passport("sec", kind="section", levels=(1, 1)),
            _passport("s2", building="2", section="1", levels=(1, 1)),
        ]
    )
    keys = set(nodes)
    assert NodeKey(NodeKind.BUILDING, "1") in keys
    assert NodeKey(NodeKind.SECTION, "1", None) in keys
    assert NodeKey(NodeKind.SECTION, "2", "1") in keys
    level_codes = sorted(key.code or "" for key in keys if key.kind is NodeKind.LEVEL)
    assert level_codes == ["1 этаж", "1 этаж", "2 этаж", "3 этаж", "4 этаж"]
    # Отметка типового плана на диапазон уровней не переносится.
    assert nodes[NodeKey(NodeKind.LEVEL, "1", None, "2 этаж")].elevation_m is None
    assert nodes[NodeKey(NodeKind.LEVEL, "1", None, "1 этаж")].elevation_m == 0.0
    # Разрез уровня не даёт.
    assert len(nodes[NodeKey(NodeKind.LEVEL, "1", None, "1 этаж")].passports) == 1


def test_conflicting_elevations_leave_value_empty_with_all_sources() -> None:
    nodes = build_frame(
        [
            _passport("a", levels=(3, 3), elevation=6.6),
            _passport("b", mark="ИОС2", levels=(3, 3), elevation=6.9),
            _passport("c", mark="ИОС3", levels=(3, 3), elevation=6.6002),
        ]
    )
    level = nodes[NodeKey(NodeKind.LEVEL, "1", None, "3 этаж")]
    assert level.elevation_m is None
    evidence = level.evidence()
    assert evidence["passport_count"] == 3
    sources = evidence["elevations"]
    assert isinstance(sources, list)
    assert len(sources) == 3


def test_heights_come_from_neighbour_elevations_only() -> None:
    heights = derived_heights(
        [
            LevelPoint("m1", -1, -3.3),
            LevelPoint("l1", 1, 0.0),
            LevelPoint("l2", 2, 3.6),
            LevelPoint("l4", 4, 9.9),
            LevelPoint("roof", None, 50.0),
        ]
    )
    assert heights == {"m1": 3.3, "l1": 3.6}


def test_named_levels_order_around_numbered() -> None:
    order = sorted(
        [(None, "кровля"), (1, "1 этаж"), (None, "цоколь"), (-1, "подвал"), (2, "2 этаж")],
        key=lambda item: level_rank(item[0], item[1]),
    )
    assert [code for _, code in order] == ["подвал", "цоколь", "1 этаж", "2 этаж", "кровля"]


# --------------------------------------------------------------------------- проверки


def test_ar_plan_per_level_flags_level_seen_only_on_mep_plans() -> None:
    passports = [
        _passport("ar", levels=(1, 2)),
        _passport("vk", mark="ИОС2", levels=(1, 3)),
        _passport("ar-any", building=None, levels=(4, 4)),
    ]
    results = check_ar_plan_per_level(
        [_level("l1", 1), _level("l3", 3), _level("l4", 4)], passports
    )
    by_level = {item.level: item for item in results}
    assert by_level["1 этаж"].status is CheckStatus.MATCH
    assert by_level["3 этаж"].status is CheckStatus.MISMATCH
    assert "ИОС2" in by_level["3 этаж"].message
    assert by_level["3 этаж"].refs[0].id == "vk"
    # План без корпуса подходит любому корпусу.
    assert by_level["4 этаж"].status is CheckStatus.MATCH


def test_checks_without_confirmed_levels_are_not_run_not_match() -> None:
    results = run_frame_checks([], [], [])
    statuses = {item.code: item.status for item in results}
    assert set(statuses.values()) == {CheckStatus.NOT_RUN}
    assert CheckCode.PZ_STOREYS in statuses


def test_scheme_per_system_by_titles() -> None:
    passports = [
        _passport("plan", mark="ИОС2", levels=(2, 9), title="План сетей В1, Т3 на отм. +3,300"),
        _passport("scheme", mark="ИОС2", kind="scheme", levels=None, title="Схема системы В1"),
        _passport("ov", mark="ИОС4", levels=(1, 1), title="План вентиляции В1"),
    ]
    results = check_scheme_per_system(passports)
    messages = {item.message: item.status for item in results}
    assert any("В1: схема есть" in text for text in messages)
    t3 = next(item for item in results if "Т3" in item.message)
    assert t3.status is CheckStatus.MISMATCH
    # «В1» на плане ИОС4 - вентсистема, не водопровод: у раздела без схем - своё замечание.
    ov = next(item for item in results if item.message.startswith("ИОС4"))
    assert ov.status is CheckStatus.MISMATCH
    assert "схем нет" in ov.message


def test_level_sequence_and_elevations() -> None:
    levels = [
        _level("l1", 1, elevation=0.0),
        _level("l2", 2, elevation=3.3),
        _level("l4", 4, elevation=3.0, values=()),
        _level("r", None, code="кровля", elevation=None, values=(12.0, 12.3)),
    ]
    sequence = check_level_sequence(levels)
    assert sequence[0].status is CheckStatus.MISMATCH
    assert "3" in sequence[0].message
    elevations = check_level_elevations(levels)
    assert {item.status for item in elevations} == {CheckStatus.MISMATCH}
    assert any("не выше" in item.message for item in elevations)
    assert any("Разные отметки" in item.message for item in elevations)


def test_pz_storeys_counts_named_above_ground_as_alternative() -> None:
    levels = [_level(f"l{n}", n) for n in range(1, 18)]
    levels.append(_level("t", None, code="технический этаж"))
    levels.append(_level("b", -1, code="-1 этаж"))
    results = run_frame_checks(
        levels,
        [],
        [_answer("storeys", 18), _answer("floors_total", 18)],
    )
    storeys = next(item for item in results if item.code is CheckCode.PZ_STOREYS)
    total = next(item for item in results if item.code is CheckCode.PZ_FLOORS_TOTAL)
    assert storeys.status is CheckStatus.MATCH  # 17 + технический этаж
    assert total.status is CheckStatus.MATCH  # 17 + 1 подземный
    wrong = run_frame_checks(levels, [], [_answer("storeys", 25)])
    assert next(i for i in wrong if i.code is CheckCode.PZ_STOREYS).status is CheckStatus.MISMATCH


def test_pz_storeys_scope_without_levels_is_not_run() -> None:
    results = run_frame_checks([_level("l1", 1)], [], [_answer("storeys", 5, building="7")])
    storeys = next(item for item in results if item.code is CheckCode.PZ_STOREYS)
    assert storeys.status is CheckStatus.NOT_RUN


def test_pz_floor_height_uses_typical_height() -> None:
    levels = [_level("l1", 1, height=4.2)] + [_level(f"l{n}", n, height=3.0) for n in range(2, 8)]
    ok = check_pz_floor_height(levels, [_answer("floor_height", 3005)])
    assert ok[0].status is CheckStatus.MATCH
    bad = check_pz_floor_height(levels, [_answer("floor_height", 3300)])
    assert bad[0].status is CheckStatus.MISMATCH
    no_heights = check_pz_floor_height([_level("l1", 1)], [_answer("floor_height", 3000)])
    assert no_heights[0].status is CheckStatus.NOT_RUN


# --------------------------------------------------------------------------- вопросы ПЗ


def _page(text: str, mark: str = "ПЗ") -> DocSearchPage:
    passport = PassportCandidate(page_index=0, section_mark=mark, sheet_kind=SheetKind.TEXT)
    return DocSearchPage(file_name="ПЗ.pdf", page_index=0, text=text, passport=passport)


def test_storeys_and_floors_total_are_counts_from_text() -> None:
    page = _page(
        "Здание переменной этажности. Этажность - 25 этажей. Количество этажей: 27, "
        "в том числе подземных - 2. Высота типового этажа 3,0 м, высота в свету 2,7 м."
    )
    questions = [
        question_by_code(code)
        for code in (
            DocQuestionCode.STOREYS,
            DocQuestionCode.FLOORS_TOTAL,
            DocQuestionCode.FLOOR_HEIGHT,
        )
    ]
    found = search_page(page, questions)
    best: dict[DocQuestionCode, str] = {}
    for candidate in sorted(found, key=lambda item: -item.score):
        best.setdefault(candidate.question, candidate.value.display)
    assert best[DocQuestionCode.STOREYS] == "25"
    assert best[DocQuestionCode.FLOORS_TOTAL] == "27"
    assert best[DocQuestionCode.FLOOR_HEIGHT] == "3000"
    heights = {
        item.value.display for item in found if item.question is DocQuestionCode.FLOOR_HEIGHT
    }
    assert "2700" not in heights


def test_count_ignores_numbers_with_units() -> None:
    page = _page("Этажность здания 3 м над уровнем земли не определяет.")
    found = search_page(page, [question_by_code(DocQuestionCode.STOREYS)])
    assert found == []
