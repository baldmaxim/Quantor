"""Паспорт листа (ADR-0043, С1): чистый разборщик на синтетических строках, без БД."""

from __future__ import annotations

import io

import pytest

from app.services.consistency.dictionaries import (
    SECTION_MARKS_VERSION,
    SHEET_KINDS_VERSION,
    SheetKind,
)
from app.services.consistency.sheet_passport import (
    PARSER_VERSION,
    EvidenceSource,
    PageInput,
    dictionary_versions,
    extract_pdf_pages,
    parse_page,
)


def _stamp(code: str, title: str, *, stage: str = "П", sheet: int = 7, extra: str = "") -> str:
    """Синтетический штамп: шифр, заголовок, «Стадия Лист Листов», подписи."""
    return "\n".join(
        [
            "ГИП",
            extra,
            title,
            code,
            "Стадия Лист Листов",
            f"{stage} {sheet} 40",
            "Разработал",
            "Н.контроль",
        ]
    )


def _page(text: str, file_name: str = "комплект.pdf", page_label: str | None = None) -> PageInput:
    return PageInput(page_index=0, text=text, file_name=file_name, page_label=page_label)


def test_code_gives_section_and_stage_with_stamp_evidence() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План 3 этажа")))
    assert result.code == "ПД-00000001-12-АР1"
    assert result.section_mark == "АР"
    assert result.stage == "П"
    assert result.sheet_number == "7"
    assert result.evidence["section_mark"].source == EvidenceSource.STAMP
    assert result.evidence["stage"].source == EvidenceSource.STAMP


def test_working_stage_from_stamp() -> None:
    result = parse_page(_page(_stamp("РД-00000002-ИОС2.1", "Схема водоснабжения В1", stage="Р")))
    assert result.stage == "РД"
    assert result.section_mark == "ИОС2"


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("План 5 этажа на отм. +14.400", SheetKind.FLOOR_PLAN),
        ("Схема водоснабжения В1", SheetKind.SCHEME),
        ("Разрез 1-1", SheetKind.SECTION),
        ("Фасад в осях 1-10", SheetKind.FACADE),
        ("Ведомость объемов работ", SheetKind.TABLE),
        ("Общие данные", SheetKind.GENERAL_DATA),
    ],
)
def test_title_gives_sheet_kind(title: str, kind: SheetKind) -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-ИОС3", title)))
    assert result.sheet_kind == kind
    assert result.title is not None
    assert result.evidence["sheet_kind"].source == EvidenceSource.TITLE
    assert len(result.evidence["title"].snippet) <= 120


def test_title_is_taken_next_to_stamp_not_from_table_header() -> None:
    text = "Экспликация помещений 6 этажа\nКвартира 1\n" + _stamp(
        "ПД-00000001-12-АР1", "План 6 этажа на отм. +21.700"
    )
    result = parse_page(_page(text))
    assert result.sheet_kind == SheetKind.FLOOR_PLAN


def test_building_and_section_from_stamp_lines() -> None:
    result = parse_page(
        _page(_stamp("ПД-00000001-12-АР1", "План 2 этажа", extra="Корпус 2-6\nСекция 3"))
    )
    assert result.building == "2-6"
    assert result.section == "3"
    assert result.evidence["building"].source == EvidenceSource.STAMP


def test_building_and_section_from_title_with_spaces_in_range() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План 4 этажа. Корпус 5, Секция 1 – 2")))
    assert result.building == "5"
    assert result.section == "1-2"
    assert result.evidence["building"].source == EvidenceSource.TITLE


def test_floor_range_gives_from_and_to() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План 2-17 этажа")))
    assert (result.level_from, result.level_to) == ("2 этаж", "17 этаж")
    assert (result.level_from_ordinal, result.level_to_ordinal) == (2, 17)


def test_floor_list_gives_min_and_max() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План типовых 3, 4, 5, 7 этажей")))
    assert (result.level_from_ordinal, result.level_to_ordinal) == (3, 7)


def test_underground_levels_are_negative() -> None:
    minus = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План -2 этажа на отм. -7,200")))
    assert (minus.level_from_ordinal, minus.level_to_ordinal) == (-2, -2)
    assert minus.level_from == "-2 этаж"
    basement = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План подвала")))
    assert (basement.level_from, basement.level_from_ordinal) == ("подвал", -1)
    words = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План минус первого этажа")))
    assert words.level_from_ordinal == -1


def test_roof_and_technical_floor_have_text_but_no_ordinal() -> None:
    roof = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План кровли")))
    assert roof.level_from == "кровля"
    assert roof.level_from_ordinal is None
    tech = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План технического этажа")))
    assert tech.level_from == "технический этаж"
    assert tech.level_from_ordinal is None


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("План 6 этажа на отм. +21.700", 21.7),
        ("План на отм. -4,200", -4.2),
        ("План 1 этажа на отм. +3,300", 3.3),
        ("План на отм. ±0.000", 0.0),
        ("План на отм. - 4,200", -4.2),
    ],
)
def test_elevation_with_comma_and_sign(title: str, expected: float) -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", title)))
    assert result.elevation_m == pytest.approx(expected)
    assert result.evidence["elevation_m"].source == EvidenceSource.TITLE


def test_title_continuation_line_joins_elevation() -> None:
    text = _stamp("ПД-00000001-12-КР1", "Схема расположения плит покрытия на\nотм. -2.000")
    result = parse_page(_page(text))
    assert result.elevation_m == pytest.approx(-2.0)


def test_code_with_spaces_in_text_layer() -> None:
    text = "ПД -00000001-12-ИОС 4.1-ПЗ\nПояснительная записка"
    result = parse_page(_page(text))
    assert result.code == "ПД-00000001-12-ИОС4.1-ПЗ"
    assert result.section_mark == "ИОС4"
    assert result.sheet_kind == SheetKind.TEXT


def test_text_volume_gets_text_kind_without_title() -> None:
    result = parse_page(_page("Взам. инв. №\nПД-00000001-12-ОВ-ПЗ\nОбщие сведения о системе"))
    assert result.section_mark == "ОВ"
    assert result.sheet_kind == SheetKind.TEXT
    assert result.evidence["sheet_kind"].source == EvidenceSource.STAMP


def test_file_name_gives_section_and_building_when_no_stamp() -> None:
    result = parse_page(_page("", file_name="01-04-00-03_ПД-00000001-КР3-КОР1.pdf"))
    assert result.section_mark == "КР"
    assert result.code == "ПД-00000001-КР3-КОР1"
    assert result.building == "1"
    assert result.stage == "П"
    for name in ("section_mark", "code", "building", "stage"):
        assert result.evidence[name].source == EvidenceSource.FILE_NAME


def test_file_name_without_code_uses_mark_token() -> None:
    result = parse_page(_page("", file_name="Проект_ОВ1.pdf"))
    assert result.section_mark == "ОВ"
    assert result.code is None
    assert result.evidence["section_mark"].source == EvidenceSource.FILE_NAME


def test_stamp_code_wins_over_file_name() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План 1 этажа"), file_name="ИОС2.pdf"))
    assert result.section_mark == "АР"


def test_empty_page_gives_none_not_zero() -> None:
    result = parse_page(_page("", file_name="Договор.pdf"))
    assert result.section_mark is None
    assert result.sheet_kind is None
    assert result.stage is None
    assert result.building is None
    assert result.level_from_ordinal is None
    assert result.elevation_m is None
    assert result.code is None
    assert result.sheet_number is None
    assert result.title is None
    assert result.evidence == {}


def test_levels_are_not_guessed_without_title() -> None:
    result = parse_page(_page("Взам. инв. №\nПД-00000001-12-ОВ-ПЗ\nна 5 этаже расположены"))
    assert result.level_from is None
    assert result.level_from_ordinal is None


def test_meaningful_page_label_is_sheet_number_fallback() -> None:
    result = parse_page(_page("", file_name="документ.pdf", page_label="А-12"))
    assert result.sheet_number == "А-12"
    assert result.evidence["sheet_number"].source == EvidenceSource.PAGE_LABEL
    trivial = parse_page(PageInput(page_index=4, text="", file_name="x.pdf", page_label="5"))
    assert trivial.sheet_number is None


def test_sheet_number_near_code_when_no_triple() -> None:
    text = "ПД-00000001-12-АР.ПЗ\nЛист\n12\nИзм. Кол.уч."
    result = parse_page(_page(text))
    assert result.sheet_number == "12"


def test_dictionary_versions_include_parser_and_dictionaries() -> None:
    assert dictionary_versions() == {
        "parser": PARSER_VERSION,
        "sections": SECTION_MARKS_VERSION,
        "sheet_kinds": SHEET_KINDS_VERSION,
    }


def test_extract_pdf_pages_reads_text_layer_page_by_page() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)
    pages = list(extract_pdf_pages(buffer, "пустой.pdf"))
    assert [page.page_index for page in pages] == [0, 1]
    assert all(page.text == "" and page.file_name == "пустой.pdf" for page in pages)


def test_cover_heading_is_not_a_sheet_title() -> None:
    text = "Раздел 2. Схема планировочной организации земельного участка\nПД-00000001-12-ПЗУ"
    result = parse_page(_page(text))
    assert result.section_mark == "ПЗУ"
    assert result.sheet_kind is None
    assert result.title is None


def test_lowercase_prose_fragment_is_not_a_sheet_title() -> None:
    text = "Взам. инв. №\nплана здания даны в приложении\nПД-00000001-12-ОВ1"
    result = parse_page(_page(text))
    assert result.sheet_kind is None


def test_stage_and_sheet_from_pair_line_before_signatures() -> None:
    text = "Принципиальные узлы кровли\nПД 5\nГИП\nГАП\nРазработал"
    result = parse_page(_page(text))
    assert result.stage == "П"
    assert result.sheet_number == "5"
    assert result.evidence["sheet_number"].source == EvidenceSource.STAMP


def test_pair_line_without_signatures_is_not_a_stamp() -> None:
    result = parse_page(_page("Таблица\nП 5\nпримечание к таблице", file_name="документ.pdf"))
    assert result.stage is None
    assert result.sheet_number is None


def test_sheet_number_from_colon_form() -> None:
    result = parse_page(_page("ПД-00000001-12-ИОС4.1. Приложение 1\nЛист:35 Листов: 62"))
    assert result.sheet_number == "35"


def test_page_number_after_code_is_not_glued_to_it() -> None:
    result = parse_page(_page("ПД-00000001-12-КР3.РР1-КОР1 43\nЛист"))
    assert result.code == "ПД-00000001-12-КР3.РР1-КОР1"
    assert result.building == "1"


def test_equipment_specification_suffix_gives_table_without_title() -> None:
    text = "Лист\n15 Изм. Кол.уч Лист №док\nПД-00000001-12-ОВ1-2.СО\nПоз. Наименование"
    result = parse_page(_page(text))
    assert result.section_mark == "ОВ"
    assert result.sheet_kind == SheetKind.TABLE
    assert result.evidence["sheet_kind"].source == EvidenceSource.STAMP


def test_floor_range_with_space_before_dash_is_not_negative() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План типового этажа (27 -28 этаж )")))
    assert (result.level_from_ordinal, result.level_to_ordinal) == (27, 28)


def test_negative_floor_after_comma_stays_negative() -> None:
    result = parse_page(_page(_stamp("ПД-00000001-12-АР1", "План типовых -2, -1 этажей")))
    assert (result.level_from_ordinal, result.level_to_ordinal) == (-2, -1)
