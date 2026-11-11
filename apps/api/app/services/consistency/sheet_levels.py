"""Уровни и отметки в заголовке листа (ADR-0043, С1): разбор текста заголовка.

Этаж, диапазон, список этажей, подвал, кровля, техэтаж и отметка «на отм. +3,300».
Не определённое — `None`; кровля, техэтаж и цоколь порядкового номера не получают.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_FLAGS: Final = re.IGNORECASE
_DASH: Final = r"[-–—−]"

_ELEVATION_RE: Final = re.compile(
    rf"отм\w*\.?\s*(?:в\.\s*)?(?P<sign>[+±]|{_DASH})?\s*(?P<int>\d{{1,3}})[.,](?P<frac>\d{{3}})(?!\d)",
    _FLAGS,
)

_LEVEL_LIST: Final = rf"-?\d{{1,3}}(?:\s*(?:{_DASH}|,|и)\s*-?\d{{1,3}})*"
_LEVEL_NUM_FIRST_RE: Final = re.compile(
    rf"(?<![\d.,+±])(?P<list>{_LEVEL_LIST})(?:-?(?:ого|го|й|ый|е))?\s+этаж\w*", _FLAGS
)
_LEVEL_NUM_AFTER_RE: Final = re.compile(rf"этаж\w*\s+(?P<list>{_LEVEL_LIST})(?![\d.,])", _FLAGS)
_LEVEL_MINUS_WORD_RE: Final = re.compile(
    r"минус\s+(?P<word>перв|втор|трет|четв[её]рт|пят)\w*\s+этаж\w*", _FLAGS
)
_MINUS_WORDS: Final = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5}
_LEVEL_WORDS: Final[tuple[tuple[re.Pattern[str], str, int | None], ...]] = (
    (re.compile(r"(?<!\w)подвал\w*", _FLAGS), "подвал", -1),
    (re.compile(r"(?<!\w)цокол\w*", _FLAGS), "цоколь", None),
    (re.compile(r"(?<!\w)кровл\w*", _FLAGS), "кровля", None),
    (re.compile(r"(?<!\w)чердак\w*", _FLAGS), "чердак", None),
    (
        re.compile(r"(?<!\w)тех(?:нич\w*|\.)?\s*(?:этаж|подполь|пространств)\w*", _FLAGS),
        "технический этаж",
        None,
    ),
    (re.compile(r"(?<!\w)техэтаж\w*", _FLAGS), "технический этаж", None),
)


@dataclass(frozen=True, slots=True)
class Level:
    text_from: str
    text_to: str
    ordinal_from: int | None
    ordinal_to: int | None
    snippet: str


def _level_text(number: int) -> str:
    return f"{number} этаж"


def _level_numbers(raw: str) -> list[int]:
    """Номера этажей из списка или диапазона; минус — знак, только если слева не цифра.

    «27 -28» и «2-17» — диапазоны, «3, -1» и «-2» — подземные этажи.
    """
    result = []
    for match in re.finditer(r"(-?)(\d{1,3})", raw):
        before = raw[: match.start()].rstrip()
        is_range_dash = match.group(1) == "-" and before[-1:].isdigit()
        number = int(match.group(2))
        result.append(-number if match.group(1) == "-" and not is_range_dash else number)
    return result


def parse_level(title: str) -> Level | None:
    """Уровень из заголовка листа; побеждает конструкция, стоящая в заголовке раньше."""
    found: list[tuple[int, Level]] = []
    for pattern in (_LEVEL_NUM_FIRST_RE, _LEVEL_NUM_AFTER_RE):
        match = pattern.search(title)
        if match is None:
            continue
        numbers = _level_numbers(match.group("list"))
        if numbers:
            low, high = min(numbers), max(numbers)
            level = Level(_level_text(low), _level_text(high), low, high, match.group(0))
            found.append((match.start(), level))
    minus = _LEVEL_MINUS_WORD_RE.search(title)
    if minus is not None:
        stem = minus.group("word")[:4].lower().replace("ё", "е")
        value = -_MINUS_WORDS[stem]
        text = _level_text(value)
        found.append((minus.start(), Level(text, text, value, value, minus.group(0))))
    for pattern, text, ordinal in _LEVEL_WORDS:
        word = pattern.search(title)
        if word is not None:
            found.append((word.start(), Level(text, text, ordinal, ordinal, word.group(0))))
    return min(found, key=lambda item: item[0])[1] if found else None


def parse_elevation(text: str) -> tuple[float, str] | None:
    match = _ELEVATION_RE.search(text)
    if match is None:
        return None
    value = int(match.group("int")) + int(match.group("frac")) / 1000
    sign = match.group("sign")
    if sign is not None and re.fullmatch(_DASH, sign):
        value = -value
    return value, match.group(0)
