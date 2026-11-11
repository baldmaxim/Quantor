"""Общие словари контура согласованности (ADR-0043): без БД."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

import pytest

from app.services.calc.adapters import recognized
from app.services.calc.adapters.recognized import section_from_code
from app.services.consistency.dictionaries import (
    SECTION_MARKS,
    SYSTEM_CODES,
    RoomType,
    SheetKind,
    match_section_mark,
    normalize_mark,
    room_type_from_name,
    sheet_kind_from_title,
    system_from_code,
)


def test_normalize_mark_maps_latin_lookalikes_to_cyrillic() -> None:
    assert normalize_mark("ap") == "АР"
    assert normalize_mark("Ob") == "ОВ"
    assert all(
        unicodedata.name(char).startswith("CYRILLIC") for char in normalize_mark("ABCEHKMOPTXY")
    )


def test_marks_and_aliases_are_unique_after_normalization() -> None:
    keys = [normalize_mark(item.mark) for item in SECTION_MARKS]
    keys += [normalize_mark(alias) for item in SECTION_MARKS for alias in item.aliases]
    assert len(keys) == len(set(keys))


def test_every_calc_mark_is_in_the_shared_dictionary() -> None:
    shared = {normalize_mark(item.mark) for item in SECTION_MARKS}
    calc_marks = {normalize_mark(mark) for mark, _, _ in recognized._SECTION_MARKS}
    assert calc_marks <= shared


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ПД-00000000-АР.С-КОР1", "АР"),
        ("ПД-1-ОВ0-1", "ОВ"),
        ("ИОС2.1", "ИОС2"),
        ("ПД-1-НВК", "НВК"),
        ("AP", "АР"),
        ("КР1", "КР"),
        ("ОВиК", "ИОС4"),
        ("ВКЛ", None),
        ("", None),
    ],
)
def test_match_section_mark(code: str, expected: str | None) -> None:
    assert match_section_mark(code) == expected


def test_match_section_mark_respects_allowed_set() -> None:
    assert match_section_mark("ПД-1-ОВ1", allowed={"АР"}) is None
    assert match_section_mark("ПД-1-АР1", allowed={"АР"}) == "АР"


def test_match_section_mark_can_skip_aliases() -> None:
    assert match_section_mark("ОВиК", with_aliases=False) is None


_OLD_TOKEN_SPLIT: Final = re.compile(r"[-_.\s/,]+")
_OLD_LOOKALIKES: Final = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")


def _old_section_from_code(code: str) -> str | None:
    """Эталон: прежняя реализация section_from_code до перехода на общий словарь."""
    for token in _OLD_TOKEN_SPLIT.split(code.upper().translate(_OLD_LOOKALIKES)):
        for mark, _, _ in recognized._SECTION_MARKS:
            rest = token[len(mark) :]
            if token.startswith(mark) and (not rest or rest.isdigit()):
                return mark
    return None


@pytest.mark.parametrize(
    "code",
    [
        "ПД-00000000-АР.С-КОР1",
        "ПД-1-ОВ0-1",
        "ПД-1-ОВиК",
        "ИОС1",
        "ИОС2.1",
        "ИОС3-1",
        "ИОС4_2",
        "ИОС12",
        "ИОС",
        "ПД-1-НВК",
        "ЭОМ1",
        "ЭС",
        "ЭМ2",
        "СС-3",
        "ПЗ",
        "ПЗУ",
        "СП",
        "КР1",
        "ГС",
        "ВС",
        "ВКЛ",
        "AP",
        "ap.1",
        "Р-12-ВК 3",
        "",
        "-",
        "ПД",
    ],
)
def test_section_from_code_equals_old_algorithm(code: str) -> None:
    assert section_from_code(code) == _old_section_from_code(code)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("План 2–14 этажа", SheetKind.FLOOR_PLAN),
        ("Разрез 1-1", SheetKind.SECTION),
        ("Схема систем В1, Т3", SheetKind.SCHEME),
        ("Экспликация помещений", SheetKind.TABLE),
        ("Общие данные", SheetKind.GENERAL_DATA),
        ("Фасад в осях 1-12", SheetKind.FACADE),
        ("Пояснительная записка", SheetKind.TEXT),
        ("Аксонометрическая схема В1", SheetKind.SCHEME),
        ("Схема планировочной организации", SheetKind.SCHEME),
        ("Узел А", None),
        ("", None),
    ],
)
def test_sheet_kind_from_title(title: str, expected: SheetKind | None) -> None:
    assert sheet_kind_from_title(title) == expected


def test_sheet_kind_earlier_word_wins() -> None:
    assert sheet_kind_from_title("План и разрез") == SheetKind.FLOOR_PLAN
    assert sheet_kind_from_title("Разрез. План кровли") == SheetKind.SECTION


def test_system_codes() -> None:
    found = system_from_code("т3")
    assert found is not None and found.code == "Т3"
    assert system_from_code(" k1 ") is not None
    assert system_from_code("В5") is None
    keys = [normalize_mark(item.code) for item in SYSTEM_CODES]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Кухня-гостиная — кухня: для ИОС важна мокрая точка (длинная фраза бьёт «гостиная»).
        ("Кухня-гостиная", RoomType.KITCHEN),
        ("Кухня гостиная", RoomType.KITCHEN),
        ("ПУИ", RoomType.CLEANING_ROOM),
        ("Лестничная клетка", RoomType.STAIR),
        ("Лифтовой холл", RoomType.ELEVATOR_HALL),
        ("Холл", RoomType.LOBBY),
        ("Шахта лифта", RoomType.ELEVATOR_SHAFT),
        ("Шахта", RoomType.UTILITY_SHAFT),
        ("Санузел", RoomType.BATHROOM),
        ("Тамбур", RoomType.VESTIBULE),
        ("Кладовая уборочного инвентаря", RoomType.CLEANING_ROOM),
        ("Кухонный гарнитур", None),
        ("", None),
    ],
)
def test_room_type_from_name(name: str, expected: RoomType | None) -> None:
    assert room_type_from_name(name) == expected
