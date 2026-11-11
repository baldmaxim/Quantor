"""Штамп листа (ADR-0043, С1): «Стадия Лист Листов», окно штампа, номер листа.

Работает по строкам текстового слоя страницы. Стадию и номер листа берёт только из строк,
которые похожи на штамп; не определённое — `None`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_FLAGS: Final = re.IGNORECASE
SPACES_RE: Final = re.compile(r"[ \t ]+")
_WINDOW: Final = 6
_STAGE_WORDS: Final = r"(ПД|РД|П|Р)"
_STAGE_HEAD_RE: Final = re.compile(
    rf"(?:Стадия\s*Лист\s*Листов|Лист\s*Стадия\s*Листов)\s*{_STAGE_WORDS}(?=\s|$)"
    rf"(?:\s+(\d{{1,4}})\s+(\d{{1,4}})(?!\d))?",
    _FLAGS,
)
_STAGE_TRIPLE_LINE_RE: Final = re.compile(rf"^{_STAGE_WORDS}\s+(\d{{1,4}})\s+(\d{{1,4}})$", _FLAGS)
# «ПД 5» без числа листов: стадия и номер листа, только рядом со строками подписей штампа.
_STAGE_PAIR_LINE_RE: Final = re.compile(rf"^{_STAGE_WORDS}\s+(\d{{1,4}})$", _FLAGS)
_LIST_COLON_RE: Final = re.compile(r"(?<!\w)Лист:\s*(\d{1,4})\s+Листов:\s*\d{1,4}", _FLAGS)
_SIGN_NEAR: Final = 3
STAGE_ANCHOR_RE: Final = re.compile(r"Стади[яи]|Листов|^Лист$", _FLAGS)
_SIGN_ANCHOR_RE: Final = re.compile(r"Разработал|Н\.?\s*контр|^ГИП\b", _FLAGS)
_LIST_SHEET_RE: Final = re.compile(r"^Лист$", _FLAGS)
_DIGITS_RE: Final = re.compile(r"^\d{1,4}$")


def stage_of(word: str) -> str:
    return "РД" if word.upper() in {"Р", "РД"} else "П"


@dataclass(frozen=True, slots=True)
class Stamp:
    anchors: tuple[int, ...]
    window: tuple[int, ...]


def is_pair_line(lines: list[str], i: int) -> bool:
    """«ПД 5»: стадия и номер листа — только если следом идут подписи штампа."""
    if _STAGE_PAIR_LINE_RE.match(lines[i]) is None:
        return False
    return any(_SIGN_ANCHOR_RE.search(line) for line in lines[i + 1 : i + 1 + _SIGN_NEAR]) or any(
        line.upper().startswith("ГАП") for line in lines[i + 1 : i + 1 + _SIGN_NEAR]
    )


def stamp_window(lines: list[str]) -> Stamp:
    anchors = [
        i
        for i, line in enumerate(lines)
        if _STAGE_TRIPLE_LINE_RE.match(line)
        or is_pair_line(lines, i)
        or _LIST_COLON_RE.search(line)
        or (len(line) <= 40 and STAGE_ANCHOR_RE.search(line))
    ]
    if not anchors:
        anchors = [i for i, line in enumerate(lines) if _SIGN_ANCHOR_RE.search(line)]
    window: set[int] = set()
    for anchor in anchors:
        window.update(range(max(0, anchor - _WINDOW), min(len(lines), anchor + _WINDOW + 1)))
    return Stamp(tuple(anchors), tuple(sorted(window)))


def stamp_stage_and_sheet(text: str, lines: list[str]) -> tuple[str | None, str | None, str | None]:
    """(стадия, номер листа, фрагмент) из «Стадия Лист Листов / П 1 1» или строки «ПД 7 37»."""
    head = _STAGE_HEAD_RE.search(SPACES_RE.sub(" ", text))
    if head is not None and head.group(2) is not None:
        return stage_of(head.group(1)), head.group(2), head.group(0)
    for i, line in enumerate(lines):
        stage_line = _STAGE_TRIPLE_LINE_RE.match(line)
        if stage_line is None and is_pair_line(lines, i):
            stage_line = _STAGE_PAIR_LINE_RE.match(line)
        if stage_line is not None:
            return stage_of(stage_line.group(1)), stage_line.group(2), line
    if head is not None:
        return stage_of(head.group(1)), None, head.group(0)
    colon = _LIST_COLON_RE.search(text)
    if colon is not None:
        return None, colon.group(1), colon.group(0)
    return None, None, None


def sheet_number_near_code(lines: list[str], code: str | None) -> tuple[str, str] | None:
    """Строка с шифром, затем «Лист» и число: номер листа рядом с шифром."""
    if code is None:
        return None
    tail = code[-12:].lower()
    for i, line in enumerate(lines):
        if tail not in compact_code(line).lower():
            continue
        for offset in (1, 2):
            if i + offset + 1 < len(lines) and _LIST_SHEET_RE.match(lines[i + offset]):
                number = lines[i + offset + 1]
                if _DIGITS_RE.match(number):
                    return number, f"{line} {lines[i + offset]} {number}"
    return None


def label_is_meaningful(label: str | None, page_index: int) -> bool:
    """Метка, равная порядковому номеру страницы, номером листа не считается."""
    return bool(label) and label != str(page_index + 1)


def compact_code(raw: str) -> str:
    """Шифр без пробелов; тире приведены к «-»."""
    return re.sub(r"[-–—−]", "-", SPACES_RE.sub("", raw)).strip("-._/")
