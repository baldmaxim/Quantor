"""Поиск `clear_height` и `hot_over_cold_gap`: новые якоря, исключения, источник ИОС4. Синтетика."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.doc_questions import (
    DocQuestionCode,
    question_by_code,
)
from app.services.consistency.doc_search import (
    DocQuestionResult,
    DocSearchPage,
    search_doc_questions,
    search_page,
)
from app.services.consistency.sheet_passport import PassportCandidate

CODE = DocQuestionCode
SMOKE_LABEL = "ИОС4 / ОВ: расчёты дымоудаления"


def page(text: str, mark: str, kind: SheetKind | None = SheetKind.TEXT) -> DocSearchPage:
    passport = PassportCandidate(page_index=0, section_mark=mark, sheet_kind=kind)
    return DocSearchPage("doc.pdf", 0, text, label="1", passport=passport)


def result_of(text: str, mark: str, code: DocQuestionCode) -> DocQuestionResult:
    results = search_doc_questions([page(text, mark)])
    return next(item for item in results if item.question == code)


def numbers(result: DocQuestionResult) -> list[int]:
    return [candidate.value.numbers[0] for candidate in result.candidates]


# --------------------------------------------------------------------------- clear_height


@pytest.mark.parametrize(
    ("text", "mm"),
    [
        # АР ПЗ 314: лишнее слово «ж/б» между «низа» и «плиты», «от уровня чистого пола».
        (
            "Уровень пола антресольного уровня -1,700, высота основной части помещения 3,8 м "
            "от уровня чистого пола до низа ж/б плиты покрытия. Вместимость автостоянки.",
            3800,
        ),
        ("Высота 2,9 м от отметки чистого пола до низа монолитной ж/б плиты перекрытия.", 2900),
        ("Высота 3,0 м от чистого пола до плиты перекрытия.", 3000),
        # Потерянная при извлечении текста «л»: «ж/б питы».
        ("Высота 3,8 м от уровня чистого пола до низа ж/б питы покрытия.", 3800),
    ],
)
def test_clear_height_anchor_allows_words_before_the_slab(text: str, mm: int) -> None:
    result = result_of(text, "АР", CODE.CLEAR_HEIGHT)
    assert numbers(result)[0] == mm
    top = result.candidates[0]
    assert "чист" in top.quote and top.score >= 80


def test_clear_height_room_height_h_is_a_low_weight_source_from_ios4() -> None:
    for text, mm in (
        ("Высота помещения, h: 2,85 м", 2850),
        ("Высота помещения h= 3,5 м", 3500),
    ):
        result = result_of(text, "ИОС4", CODE.CLEAR_HEIGHT)
        assert numbers(result) == [mm]
        candidate = result.candidates[0]
        assert candidate.source_label == SMOKE_LABEL
        assert candidate.score < 60, "слабее любого якоря АР"
    # В АР такой якорь не работает: источник ИОС4 только для него.
    assert result_of("Высота помещения, h: 2,85 м этаж", "АР", CODE.CLEAR_HEIGHT).candidates == ()
    # Прочие якоря вопроса ИОС4 не читают: «(в свету)» рядом с «этаж» - не высота.
    noisy = "Расстояние по горизонтали (в свету) до оси 3 м, этаж 5."
    assert result_of(noisy, "ИОС4", CODE.CLEAR_HEIGHT).candidates == ()


def test_floor_to_floor_height_is_not_a_clear_height() -> None:
    text = "Высота этажа в свету принята 3,36 м в отметках чистых полов."
    assert result_of(text, "АР", CODE.CLEAR_HEIGHT).candidates == ()
    # Охранный шаблон - причина: без него тот же текст даёт кандидата.
    question = replace(question_by_code(CODE.CLEAR_HEIGHT), value_exclusions=())
    unguarded = search_page(page(text, "АР"), [question])
    assert {c.value.numbers[0] for c in unguarded} == {3360}
    # Перечень этажей с высотами в отметках чистых полов.
    listing = (
        "Высота всех жилых этажей в секции 1 принята 3,36 м в отметках чистых полов "
        "за исключением 11 - 3,68 м в отметках чистых полов, 3,84 ммв отметках чистых полов."
    )
    assert result_of(listing, "АР", CODE.CLEAR_HEIGHT).candidates == ()


def test_floor_to_floor_guard_keeps_a_real_clear_height_next_to_it() -> None:
    text = (
        "Высота этажа принята 3,36 м в отметках чистых полов. "
        "Высота основной части помещения 3,8 м от уровня чистого пола до низа плиты покрытия."
    )
    assert numbers(result_of(text, "АР", CODE.CLEAR_HEIGHT)) == [3800]


def test_mop_minimum_from_the_customer_brief_is_not_a_clear_height() -> None:
    text = (
        "Высота помещений МОП (до подвесного потолка и устройства пола): не менее 2200 мм. "
        "Высота помещений кладовых, не менее 2500 мм."
    )
    assert result_of(text, "АР", CODE.CLEAR_HEIGHT).candidates == ()
    customer = DocSearchPage(
        "ТЗ_общее.pdf", 0, text, passport=PassportCandidate(0, None, None), is_customer_doc=True
    )
    assert [c for c in search_page(customer) if c.question is CODE.CLEAR_HEIGHT] == []


# --------------------------------------------------------------------------- hot_over_cold_gap


@pytest.mark.parametrize(
    ("text", "mm", "qualifier"),
    [
        (
            "Трубопроводы Т3 прокладывать выше трубопроводов В1 на расстоянии 100 мм в свету.",
            100,
            None,
        ),
        ("Трубопровод ГВС размещать над трубопроводом ХВС, зазор 100 мм.", 100, None),
        ("Стояки ХВС прокладывать ниже стояков ГВС, расстояние 120 мм.", 120, None),
        ("ГВС прокладывать под трубопроводом ХВС не менее 100 мм.", 100, "min"),
        ("Не менее 100 мм между трубами ГВС и ХВС.", 100, "min"),
        ("Не менее 100 мм по вертикали: горячая вода выше холодной.", 100, "min"),
    ],
)
def test_hot_over_cold_gap_abbreviations_and_number_first(
    text: str, mm: int, qualifier: str | None
) -> None:
    result = result_of(text, "ИОС2", CODE.HOT_OVER_COLD_GAP)
    assert result.candidates, text
    top = result.candidates[0]
    assert top.value.numbers == (mm,) and top.value.qualifier == qualifier
    assert result.assumption is None


@pytest.mark.parametrize(
    "text",
    [
        # Голое «под» без слова о трубах - не якорь.
        "Подача горячей воды под потолком выполнена на высоте 3000 мм.",
        "Холодная вода под давлением 0,45 МПа, расстояние 100 мм.",
    ],
)
def test_hot_over_cold_gap_bare_pod_is_not_an_anchor(text: str) -> None:
    result = result_of(text, "ИОС2", CODE.HOT_OVER_COLD_GAP)
    assert result.candidates == ()
    assert result.assumption is not None  # нет ответа - норматив-допущение СП 40-101
