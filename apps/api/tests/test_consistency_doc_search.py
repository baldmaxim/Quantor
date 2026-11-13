"""Поиск ответов на вопросы к документации: числа, источники, дедуп, not_found. Синтетика."""

from __future__ import annotations

import random

import pytest

from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.doc_questions import (
    DOC_QUESTIONS_VERSION,
    DocQuestionCode,
    DocValueKind,
)
from app.services.consistency.doc_search import (
    DEFAULT_TOP_N,
    QUOTE_LIMIT,
    DocCandidate,
    DocQuestionResult,
    DocSearchPage,
    DocSearchStatus,
    clean_text,
    search_doc_questions,
    search_page,
)
from app.services.consistency.sheet_passport import PassportCandidate

CODE = DocQuestionCode


def page(
    text: str,
    mark: str | None = "АР",
    kind: SheetKind | None = SheetKind.TEXT,
    file_name: str = "doc.pdf",
    index: int = 0,
    building: str | None = None,
    section: str | None = None,
    level: str | None = None,
) -> DocSearchPage:
    passport = PassportCandidate(
        page_index=index,
        section_mark=mark,
        sheet_kind=kind,
        building=building,
        section=section,
        level_from=level,
        level_to=level,
    )
    return DocSearchPage(file_name, index, text, label=str(index + 1), passport=passport)


def result_of(pages: list[DocSearchPage], code: DocQuestionCode) -> DocQuestionResult:
    return next(item for item in search_doc_questions(pages) if item.question == code)


def values(result: DocQuestionResult) -> list[str]:
    return [candidate.value.display for candidate in result.candidates]


# --------------------------------------------------------------------------- числа


@pytest.mark.parametrize(
    ("text", "mm"),
    [
        ("Высота потолка в коридорах не менее 2,70 м.", 2700),
        ("Высота потолка в коридорах 2.7 м от чистого пола", 2700),
        ("Высота потолка в коридорах МОП 2 700 мм", 2700),  # пробел-разделитель тысяч
        ("Высота потолка в коридорах МОП 2 700 мм", 2700),  # неразрывный пробел
        ("Высота потолка в коридорах МОП 270 см", 2700),
        ("Высота подвесного потолка в МОП 2650 мм", 2650),
    ],
)
def test_ceiling_height_numbers_are_normalized_to_mm(text: str, mm: int) -> None:
    result = result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT)
    assert result.status == DocSearchStatus.FOUND
    top = result.candidates[0]
    assert top.value.kind == DocValueKind.LENGTH_MM
    assert top.value.numbers == (mm,)


def test_qualifier_not_less_than_is_kept() -> None:
    result = result_of(
        [page("Высота коридора (пол - потолок) не менее 2,70 м")], CODE.CORRIDOR_CEILING_HEIGHT
    )
    assert result.candidates[0].value.numbers == (2700,)
    assert result.candidates[0].value.qualifier == "min"


@pytest.mark.parametrize(
    "text",
    [
        "Высота потолка в коридоре: отметка +3.000",
        "Высота потолка в коридоре на отм. +2,700 м",
        "Высота потолка в коридоре на отм. 3.000 м",
        "Высота потолка МОП: уровень +47,600 м",
        "Высота потолка МОП 3.000",  # без единицы после якоря без «=» - не высота
    ],
)
def test_elevation_marks_are_not_heights(text: str) -> None:
    result = result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT)
    assert result.status == DocSearchStatus.NOT_FOUND


def test_elevation_is_skipped_but_real_height_in_same_text_is_taken() -> None:
    text = "Высота подвесного потолка коридора на отм. +3.000 составляет 2,7 м."
    result = result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT)
    assert [c.value.numbers for c in result.candidates] == [(2700,)]


def test_values_out_of_sane_range_are_dropped() -> None:
    text = "Высота потолка в коридорах МОП 1,2 м; площадь коридора 40,2 м2"
    assert result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT).status == (
        DocSearchStatus.NOT_FOUND
    )


def test_slab_thickness_with_and_without_unit() -> None:
    text = "План 4 этажа. Перекрытие на отм. +14.500 тщ. плиты 200 мм. Левая часть: тщ. 240"
    result = result_of([page(text, "КР", SheetKind.FLOOR_PLAN)], CODE.SLAB_THICKNESS)
    assert sorted(c.value.numbers[0] for c in result.candidates) == [200, 240]


def test_slab_thickness_kr_plan_title_and_ocr_variant() -> None:
    text = "План несущих конструкций 4–20 этажа С3 в осях 1-17. Примечание: тщ. плиты 200 мм."
    result = result_of([page(text, "КР", SheetKind.FLOOR_PLAN)], CODE.SLAB_THICKNESS)
    assert [c.value.numbers[0] for c in result.candidates] == [200]
    ocr = result_of(
        [page("Зона: мщ. плиты 240 мм", "КР", SheetKind.FLOOR_PLAN)], CODE.SLAB_THICKNESS
    )
    assert [c.value.numbers[0] for c in ocr.candidates] == [240]


def test_slab_thickness_sign_plus_after_anchor_is_elevation() -> None:
    result = result_of([page("тщ. +14.500", "КР", SheetKind.FLOOR_PLAN)], CODE.SLAB_THICKNESS)
    assert result.status == DocSearchStatus.NOT_FOUND


def test_slab_thickness_phrase_form() -> None:
    text = "Толщина монолитной плиты перекрытия типового этажа - 200 мм."
    result = result_of([page(text, "КР")], CODE.SLAB_THICKNESS)
    assert result.candidates[0].value.numbers == (200,)


@pytest.mark.parametrize("sep", ["×", "х", "x", " x ", "*"])  # «х» - кириллица
def test_tray_section_separators(sep: str) -> None:
    text = f"Кабели прокладываются по перфорированным лоткам 1000{sep}500 мм."
    result = result_of([page(text, "ИОС1")], CODE.CABLE_TRAY_SECTION)
    top = result.candidates[0]
    assert top.value.kind == DocValueKind.SECTION_MM
    assert top.value.numbers == (1000, 500)
    assert top.value.display == "1000x500"


def test_tray_without_size_is_not_found() -> None:
    text = "Электропроводка прокладывается по металлическим перфорированным лоткам."
    assert result_of([page(text, "ИОС1")], CODE.CABLE_TRAY_SECTION).status == (
        DocSearchStatus.NOT_FOUND
    )


def test_duct_section_with_system_and_round() -> None:
    text = "Клапан дымоудаления ДУ-2.3 1000 х 500 мм врезан в шахту. Воздуховод ДП-4.3 Ø315."
    result = result_of([page(text, "ИОС4", SheetKind.TABLE)], CODE.DUCT_SECTION)
    by_display = {c.value.display: c.value for c in result.candidates}
    assert by_display["ДУ-2.3: 1000x500"].numbers == (1000, 500)
    assert by_display["ДП-4.3: Ø315"].code == "round"
    assert by_display["ДП-4.3: Ø315"].numbers == (315,)


def test_duct_without_smoke_context_is_ignored() -> None:
    text = "Воздуховод общеобменной вентиляции 400х200 мм."
    assert result_of([page(text, "ИОС4")], CODE.DUCT_SECTION).status == DocSearchStatus.NOT_FOUND


def test_sprinkler_range_and_model() -> None:
    text = (
        "Приняты оросители фирмы «Тест» модель «СВН-12», устанавливаемые розеткой вниз. "
        "Расстояние оросителя до плоскости перекрытия принимается от 0,08 до 0,30 м."
    )
    pages = [page(text, "ИОС2")]
    gap = result_of(pages, CODE.SPRINKLER_CEILING_GAP).candidates[0].value
    assert gap.kind == DocValueKind.RANGE_MM
    assert gap.numbers == (80, 300)
    assert gap.display == "80-300"
    model = result_of(pages, CODE.SPRINKLER_MODEL).candidates[0].value
    assert model.kind == DocValueKind.ENUM
    assert model.display == "СВН-12; розеткой вниз"
    assert model.code == "rosette_down"


def test_sprinkler_range_with_en_dash_and_single_value() -> None:
    en_dash = "Расстояние от оросителя до плоскости перекрытия 80–300 мм."
    value = result_of([page(en_dash, "ИОС2")], CODE.SPRINKLER_CEILING_GAP).candidates[0].value
    assert value.numbers == (80, 300)
    single = "Расстояние от розетки оросителя до подвесного потолка не менее 300 мм."
    value = result_of([page(single, "ИОС2")], CODE.SPRINKLER_CEILING_GAP).candidates[0].value
    assert (value.numbers, value.qualifier) == ((300,), "min")


def test_sprinkler_rosette_up() -> None:
    text = "Спринклерные оросители устанавливаются розеткой вверх, модель СВВ-15."
    value = result_of([page(text, "ВК")], CODE.SPRINKLER_MODEL).candidates[0].value
    assert (value.display, value.code) == ("СВВ-15; розеткой вверх", "rosette_up")


def test_floor_buildup_type_and_layers_sum() -> None:
    text = (
        "Тип П-1.3а (МОП жилых этажей кроме 1 этажа)\n"
        "1. керамогранит на клее -20 мм\n2. стяжка М200, армированная фиброй -70 мм\n"
        "3. звукоизоляция -10мм\n4. монолитная плита\n"
        "Тип П-2 (квартиры)\n1. ламинат -8 мм"
    )
    result = result_of([page(text, "АР", SheetKind.TABLE)], CODE.CORRIDOR_FLOOR_BUILDUP)
    top = result.candidates[0].value
    assert top.display == "тип П-1.3а; слои 20+70+10 мм, итого 100 мм"
    assert top.numbers == (100,)
    assert len(result.candidates) == 1  # тип квартир не попал в МОП


def test_floor_buildup_thickness_without_type() -> None:
    text = "Для МОП: толщина конструкции пола - 151 мм (1 этаж), 100 мм (типовой этаж)."
    result = result_of([page(text, "АР", SheetKind.TABLE)], CODE.CORRIDOR_FLOOR_BUILDUP)
    assert result.candidates[0].value.numbers == (151, 100)


def test_hot_over_cold_gap_found_in_text() -> None:
    text = (
        "Трубопроводы горячего водоснабжения прокладываются выше холодного, зазор не менее 50 мм."
    )
    result = result_of([page(text, "ИОС2")], CODE.HOT_OVER_COLD_GAP)
    assert result.status == DocSearchStatus.FOUND
    assert result.candidates[0].value.numbers == (50,)
    assert result.assumption is None  # норматив предлагается только когда ответа нет


# --------------------------------------------------------------------------- источники


def test_page_of_unrelated_section_is_not_searched() -> None:
    text = "Высота потолка в коридорах МОП 2,70 м"
    assert result_of([page(text, "КР")], CODE.CORRIDOR_CEILING_HEIGHT).status == (
        DocSearchStatus.NOT_FOUND
    )
    assert result_of([page(text, None)], CODE.CORRIDOR_CEILING_HEIGHT).status == (
        DocSearchStatus.NOT_FOUND
    )


def test_context_is_required_for_corridor_ceiling() -> None:
    text = "Высота потолков в жилых комнатах квартир 2,70 м"
    assert result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT).status == (
        DocSearchStatus.NOT_FOUND
    )


def test_source_priority_pz_before_sections_before_customer() -> None:
    text = "Высота потолка в коридоре МОП: {} м."
    pages = [
        page(text.format("2,70"), None, None, "Договор_(общий).pdf"),
        page(text.format("2,60"), "АР", SheetKind.TABLE, "ar-table.pdf"),
        page(text.format("2,80"), "АР", SheetKind.SECTION, "ar-section.pdf"),
        page(text.format("2,90"), "АР", SheetKind.TEXT, "ar-pz.pdf"),
    ]
    result = result_of(pages, CODE.CORRIDOR_CEILING_HEIGHT)
    assert [c.value.numbers[0] for c in result.candidates] == [2900, 2800, 2600, 2700]
    assert [c.source_label for c in result.candidates] == [
        "ПЗ АР",
        "Разрезы АР",
        "Ведомость отделки АР",
        "Договор / ТЗ Заказчика",
    ]
    assert result.candidates[-1].file_name == "Договор_(общий).pdf"


def test_customer_flag_is_taken_from_page_when_set() -> None:
    text = "Высота коридора (пол - потолок) не менее 2,70 м"
    flagged = DocSearchPage("scan.pdf", 0, text, is_customer_doc=True)
    assert result_of([flagged], CODE.CORRIDOR_CEILING_HEIGHT).status == DocSearchStatus.FOUND
    unflagged = DocSearchPage("scan.pdf", 0, text, is_customer_doc=False)
    assert result_of([unflagged], CODE.CORRIDOR_CEILING_HEIGHT).status == (
        DocSearchStatus.NOT_FOUND
    )


def test_unknown_sheet_kind_matches_any_source_with_kinds() -> None:
    text = "Высота потолка в коридоре МОП 2,70 м"
    result = result_of([page(text, "АР", None)], CODE.CORRIDOR_CEILING_HEIGHT)
    assert result.status == DocSearchStatus.FOUND


def test_scope_comes_from_passport() -> None:
    text = "Толщина плиты перекрытия 200 мм"
    result = result_of(
        [page(text, "КР", building="9", section="3", level="14")], CODE.SLAB_THICKNESS
    )
    top = result.candidates[0]
    assert (top.scope.building, top.scope.section, top.scope.level_from) == ("9", "3", "14")
    assert (top.file_name, top.page_index, top.page_label) == ("doc.pdf", 0, "1")


# --------------------------------------------------------------------------- not_found


def test_not_found_gives_norm_assumption_where_catalog_has_one() -> None:
    results = {item.question: item for item in search_doc_questions([])}
    assert len(results) == len(CODE)
    assert all(item.status == DocSearchStatus.NOT_FOUND for item in results.values())
    assert all(not item.candidates for item in results.values())
    hot = results[CODE.HOT_OVER_COLD_GAP].assumption
    assert hot is not None
    assert (hot.mm_from, hot.reference) == (100, "СП 40-101-96, п. 2.25")
    gap = results[CODE.SPRINKLER_CEILING_GAP].assumption
    assert gap is not None
    assert (gap.mm_from, gap.mm_to) == (80, 300)
    assert results[CODE.CORRIDOR_CEILING_HEIGHT].assumption is None
    assert results[CODE.SLAB_THICKNESS].assumption is None


def test_versions_are_recorded() -> None:
    result = search_doc_questions([])[0]
    assert result.versions["catalog"] == DOC_QUESTIONS_VERSION
    assert result.versions["sections"].startswith("consistency.dict.sections.")
    assert result.versions["sheet_kinds"].startswith("consistency.dict.sheet_kinds.")
    assert result.versions["search"].startswith("consistency.doc_search.")


# --------------------------------------------------------------------------- дедуп, top-N


def test_same_quote_in_two_files_is_merged_with_occurrences() -> None:
    text = "Толщина плиты перекрытия 200 мм."
    pages = [page(text, "КР", file_name="a.pdf"), page(text, "КР", file_name="b.pdf")]
    result = result_of(pages, CODE.SLAB_THICKNESS)
    assert len(result.candidates) == 1
    assert result.candidates[0].occurrences == 2


def test_same_value_on_many_pages_of_one_file_is_one_candidate() -> None:
    pages = [
        page(f"Лист {i}. Толщина плиты перекрытия 200 мм, этаж {i}", "КР", index=i)
        for i in range(10)
    ]
    result = result_of(pages, CODE.SLAB_THICKNESS)
    assert len(result.candidates) == 1
    assert result.candidates[0].occurrences == 10


def test_different_values_stay_separate_and_top_n_limits() -> None:
    pages = [
        page(f"Толщина плиты перекрытия {200 + 10 * i} мм", "КР", file_name=f"f{i}.pdf")
        for i in range(8)
    ]
    result = result_of(pages, CODE.SLAB_THICKNESS)
    assert len(result.candidates) == DEFAULT_TOP_N == 5
    custom = search_doc_questions(pages, top_n=3)
    assert len(next(r for r in custom if r.question == CODE.SLAB_THICKNESS).candidates) == 3


def test_ranking_is_deterministic_and_independent_of_page_order() -> None:
    pages = [
        page(f"Толщина плиты перекрытия {200 + 10 * (i % 4)} мм, лист {i}", "КР", index=i)
        for i in range(12)
    ] + [
        page("Высота потолка в коридоре МОП 2,70 м", file_name="pz.pdf"),
        page("Расстояние оросителя до перекрытия от 0,08 до 0,30 м", "ИОС2", file_name="v.pdf"),
    ]
    first = search_doc_questions(pages)
    for seed in range(5):
        shuffled = pages[:]
        random.Random(seed).shuffle(shuffled)  # noqa: S311
        assert search_doc_questions(shuffled) == first
    assert search_doc_questions(pages) == first


def test_score_is_integer_in_range_and_better_source_scores_higher() -> None:
    text = "Высота потолка в коридоре МОП 2,70 м"
    pages = [page(text, "АР", SheetKind.TEXT, "pz.pdf"), page(text + ".", "АР", None, "x.pdf")]
    result = result_of(pages, CODE.CORRIDOR_CEILING_HEIGHT)
    assert all(isinstance(c.score, int) and 0 <= c.score <= 100 for c in result.candidates)
    scores = {c.file_name: c.score for c in result.candidates}
    assert scores["pz.pdf"] >= scores["x.pdf"]


# --------------------------------------------------------------------------- цитата


def test_quote_is_cleaned_and_limited() -> None:
    filler = "слово " * 120
    text = filler + "Высота\x00  потолка\n\n в   коридорах\tМОП  2,70\nм." + filler
    result = result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT)
    quote = result.candidates[0].quote
    assert len(quote) <= QUOTE_LIMIT
    assert "\x00" not in quote
    assert "  " not in quote
    assert "\n" not in quote
    assert "Высота потолка в коридорах МОП 2,70 м" in quote
    top = result.candidates[0]
    assert quote[top.quote_focus :].startswith("Высота потолка")


def test_quote_contains_anchor_and_value_for_far_apart_pair() -> None:
    text = "Высота потолка коридоров " + "и прочих помещений здания " * 5 + "составляет 2,70 м"
    result = result_of([page(text)], CODE.CORRIDOR_CEILING_HEIGHT)
    quote = result.candidates[0].quote
    assert "Высота потолка" in quote
    assert quote.endswith("2,70 м")


def test_yo_and_dash_variants_are_matched() -> None:
    text = "Высота общего коридора и лифтового холла (пол – потолок) ≥ 2,70 м, высота — «ё»"
    result = result_of(
        [page(text, None, None, "Приложение_№19_Чек-лист.pdf")], CODE.CORRIDOR_CEILING_HEIGHT
    )
    assert result.candidates[0].value.numbers == (2700,)


def test_clean_text_removes_nul_and_collapses_spaces() -> None:
    assert clean_text(" a\x00b \n\t c  d ") == "a b c d"


def test_search_page_returns_raw_candidates_without_merging() -> None:
    text = "Толщина плиты перекрытия 200 мм. Плита перекрытия: тщ. 200"
    candidates: list[DocCandidate] = search_page(page(text, "КР"))
    assert all(c.question == CODE.SLAB_THICKNESS for c in candidates)
    assert len(candidates) >= 2
    assert all(c.occurrences == 1 for c in candidates)


def test_page_without_text_or_passport_is_skipped() -> None:
    assert search_page(page("", "АР")) == []
    assert search_page(DocSearchPage("x.pdf", 0, "Толщина плиты перекрытия 200 мм")) == []


def test_pipe_diameter_du_is_not_a_smoke_system() -> None:
    text = "Дефлектор Ду315 и решетка 1500x700 мм в котельном зале."
    assert result_of([page(text, "ИОС4")], CODE.DUCT_SECTION).status == DocSearchStatus.NOT_FOUND


def test_range_beats_single_value_for_sprinkler_gap() -> None:
    single = "Допускается увеличение расстояния от оросителя до плоскости перекрытия до 1,3 м."
    ranged = "Расстояние от оросителя до плоскости перекрытия принимается от 0,08 до 0,30 м."
    pages = [page(single, "ИОС2", file_name="a.pdf"), page(ranged, "ИОС2", file_name="b.pdf")]
    result = result_of(pages, CODE.SPRINKLER_CEILING_GAP)
    assert values(result) == ["80-300", "1300"]


def test_exception_wording_lowers_sprinkler_gap_score() -> None:
    exception = (
        "Допускается увеличение расстояния от оросителя до плоскости перекрытия "
        "до 0,4-1,0 м при установке экранов."
    )
    main = "Расстояние от оросителя до плоскости перекрытия принимается от 0,08 до 0,30 м."
    pages = [page(exception, "ИОС2", file_name="a.pdf"), page(main, "ИОС2", file_name="b.pdf")]
    result = result_of(pages, CODE.SPRINKLER_CEILING_GAP)
    assert values(result) == ["80-300", "400-1000"]
    assert result.candidates[0].score - result.candidates[1].score >= 10


def test_floor_buildup_type_without_parentheses() -> None:
    text = (
        "П-3. Полы в МОП на жилых этажах 1. Финишный слой - 20 мм 2. Стяжка М150 - 80 мм "
        "3. Монолитная плита перекрытия"
    )
    result = result_of([page(text, "АР", SheetKind.TABLE)], CODE.CORRIDOR_FLOOR_BUILDUP)
    assert result.candidates[0].value.display == "тип П-3; слои 20+80 мм, итого 100 мм"


def test_floor_buildup_sum_is_not_claimed_when_layer_list_is_open() -> None:
    text = (
        "Тип П-6 (МОП, выход на кровлю) 1. Финишный слой - 20 мм 2. Стяжка - 50 мм 3. Гидроизоляция"
    )
    result = result_of([page(text, "АР", SheetKind.TABLE)], CODE.CORRIDOR_FLOOR_BUILDUP)
    value = result.candidates[0].value
    assert value.display == "тип П-6; слои 20+50 мм (список мог быть неполным)"
    assert value.numbers == (20, 50)
    assert value.code == "layers_partial"


def test_floor_buildup_long_layer_list_and_total_line_is_not_a_layer() -> None:
    text = (
        "П-6. Полы в МОП в зоне выходов на кровлю 1. Финишный слой (см. дизайн) - 20мм "
        "2. Стяжка цементно-песчаная М150 с добавлением фиброволокна* - 50мм "
        "3. Керамзитобетон D600** - 480мм Основание: Монолитная ж/б плита перекрытия ИТОГО: 100мм"
    )
    result = result_of([page(text, "АР", SheetKind.TABLE)], CODE.CORRIDOR_FLOOR_BUILDUP)
    value = result.candidates[0].value
    assert value.numbers == (550,)
    assert value.display == "тип П-6; слои 20+50+480 мм, итого 550 мм"
