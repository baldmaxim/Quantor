"""Нормализация распознанного текста: числа, этажи, секции, единицы, названия помещений.

Правила здесь — правила чтения документа, а не инженерные: «4-5 этажа» — это этажи 4 и 5,
«3,3 м» — три целых три десятых метра. Единица без правила не угадывается: «3,3» без «м» —
не высота. Единственное правило, задающее единицу, — отметки «отм. +27.900» и «±0,000=…»:
по ГОСТ 21.101 они в метрах; и напор «25 м» — метры водяного столба.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final

_SPACES = re.compile(r"[\s\u00a0\u2009\u202f]+")
_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")
_DASHES = str.maketrans({"−": "-", "–": "-", "—": "-"})


def normalize_text(value: str) -> str:
    """Нижний регистр, «ё» как «е», пробелы схлопнуты — для сравнения подписей."""
    return _SPACES.sub(" ", value.lower().replace("ё", "е")).strip()


def parse_decimal_ru(text: str) -> Decimal | None:
    """«3,3» → 3.3; «1 280» → 1280; «−5.600» → -5.600. Точность записи сохраняется."""
    cleaned = _SPACES.sub("", text.translate(_DASHES)).replace(",", ".")
    if not _NUMBER.match(cleaned):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def stated_text(value: Decimal) -> str:
    """Запись числа как в документе: «3,0» → «3.0», «162,050» → «162.050» — нули не теряются."""
    return format(value, "f")


def parse_count(text: str) -> int | None:
    value = parse_decimal_ru(text)
    if value is None or value != value.to_integral_value() or value < 0:
        return None
    return int(value)


# ----------------------------------------------------------------------------------- этажи

_FLOOR_RANGE = re.compile(
    r"(?<![\d.])(-?\d{1,3})\s*(?:[-–—÷]|по)\s*(-?\d{1,3})\s*(?:-?(?:го|й|ой|х))?\s*этаж",
    re.IGNORECASE,
)
_FLOOR_RANGE_AFTER = re.compile(
    r"этаж\w*\s*(?:со?\s+)?(-?\d{1,3})\s*(?:[-–—÷]|по)\s*(-?\d{1,3})(?![\d.])", re.IGNORECASE
)
_FLOOR_SINGLE = re.compile(r"(?<![\d.\-–—])(-?\d{1,3})\s*(?:-?(?:го|й|ой))?\s*этаж", re.IGNORECASE)


def floor_code(low: int, high: int | None = None) -> str | None:
    if high is None or high == low:
        return str(low)
    return f"{low}..{high}" if low < high else None


def parse_floor_scope(text: str) -> str | None:
    """Этаж или группа этажей из подписи: «4-5 этажа» → «4..5», «-1 этажа» → «-1».

    «Типового этажа» без номеров места не даёт — возвращается пусто, а не догадка.
    """
    for pattern in (_FLOOR_RANGE, _FLOOR_RANGE_AFTER):
        match = pattern.search(text.translate(_DASHES))
        if match:
            return floor_code(int(match.group(1)), int(match.group(2)))
    match = _FLOOR_SINGLE.search(text.translate(_DASHES))
    if match:
        return floor_code(int(match.group(1)))
    return None


def floors_in(scope: str) -> list[int]:
    if ".." in scope:
        low, high = (int(part) for part in scope.split(".."))
        return list(range(low, high + 1))
    return [int(scope)]


_SECTION = re.compile(r"^секци[яи]\s*№?\s*([0-9]+[а-яa-z]?)\b", re.IGNORECASE)
_APARTMENT = re.compile(r"^квартир[аы]\s*№?\s*(.+)$", re.IGNORECASE)
_BUILDING = re.compile(r"корпус\w*\s*№?\s*([0-9]+[а-яa-z]?)\b", re.IGNORECASE)


def parse_section(cell: str) -> str | None:
    match = _SECTION.match(normalize_text(cell))
    return match.group(1).upper() if match else None


def parse_apartment_label(cell: str) -> str | None:
    match = _APARTMENT.match(normalize_text(cell))
    if not match:
        return None
    label = match.group(1).strip(" .;:")
    return label or None


def building_in_text(text: str) -> str | None:
    match = _BUILDING.search(text)
    return match.group(1).upper() if match else None


# --------------------------------------------------------------------------------- единицы

_UNIT_WORDS: Final[dict[str, str]] = {
    "м": "m",
    "м.": "m",
    "мм": "mm",
    "см": "cm",
    "м2": "m2",
    "м²": "m2",
    "кв.м": "m2",
    "кв. м": "m2",
    "мпа": "MPa",
    "кпа": "kPa",
    "бар": "bar",
    "м вод. ст.": "m_h2o",
    "м вод.ст.": "m_h2o",
    "м.вод.ст.": "m_h2o",
    "м вод. ст": "m_h2o",
    "м вод ст": "m_h2o",
    "л/с": "l_s",
    "м3/ч": "m3_h",
    "м³/ч": "m3_h",
    "м3/сут": "m3_day",
    "м³/сут": "m3_day",
    "л/сут": "l_day",
    "°с": "degC",
    "°c": "degC",
}


def parse_unit(token: str) -> str | None:
    return _UNIT_WORDS.get(normalize_text(token))


# --------------------------------------------------------------------- названия помещений

_KITCHEN = re.compile(r"^кухн")
_SANITARY = re.compile(r"^(сан\.?\s*узел|санузел|с/у|с\.у\.?|ванн|туалет|уборн|душев)")
_WET_NONRESIDENTIAL = re.compile(
    r"(^|[\s+])(пуи|сан\.?\s*узел|санузел|с/у|с\.у|уборн|туалет|душев|моечн)"
)


def is_kitchen(name: str) -> bool:
    return bool(_KITCHEN.match(normalize_text(name)))


def is_sanitary_room(name: str) -> bool:
    return bool(_SANITARY.match(normalize_text(name)))


def is_wet_nonresidential(name: str) -> bool:
    """ПУИ, санузлы, душевые, моечные — помещения с водоразборными приборами вне квартир."""
    return bool(_WET_NONRESIDENTIAL.search(normalize_text(name)))


_APARTMENT_TYPES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (re.compile(r"^студи"), "STUDIO"),
    (re.compile(r"^(1\s*-?\s*(к|комн|ком)|однокомн)"), "R1"),
    (re.compile(r"^(2\s*-?\s*(к|комн|ком)|двухкомн)"), "R2"),
    (re.compile(r"^(3\s*-?\s*(к|комн|ком)|тр[её]хкомн)"), "R3"),
    (re.compile(r"^([4-9]\s*-?\s*(к|комн|ком)|четыр[её]хкомн|пятикомн|многокомн)"), "R4_PLUS"),
)
_EURO = re.compile(r"^\d\s*-?\s*е\b|евро")


def apartment_type(label: str) -> str | None:
    """Тип квартиры по подписи квартирографии. «2Е» (евроформат) не сопоставляется: неоднозначно."""
    text = normalize_text(label)
    if _EURO.search(text):
        return None
    for pattern, code in _APARTMENT_TYPES:
        if pattern.match(text):
            return code
    return None
