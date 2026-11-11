"""Паспорт листа: кандидат по текстовому слою PDF (ADR-0043, этап С1).

Чистый разборщик без БД и API. Только pypdf: без OCR, растра и геометрии. Источники по
надёжности: штамп (рядом с шифром, «Стадия Лист Листов») → заголовок → метка страницы →
имя файла. Не определённое поле — `None`, а не 0 и не догадка. Правила общие для любого
комплекта, настроек под объект нет.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import BinaryIO, Final

from pypdf import PdfReader

from app.services.consistency.dictionaries import (
    SECTION_MARKS_VERSION,
    SHEET_KINDS_VERSION,
    SheetKind,
    match_section_mark,
    sheet_kind_match,
)
from app.services.consistency.pdf_text import page_text
from app.services.consistency.sheet_levels import parse_elevation, parse_level
from app.services.consistency.sheet_stamp import (
    SPACES_RE,
    STAGE_ANCHOR_RE,
    Stamp,
    compact_code,
    label_is_meaningful,
    sheet_number_near_code,
    stage_of,
    stamp_stage_and_sheet,
    stamp_window,
)

PARSER_VERSION: Final = "consistency.sheet_passport.v2"

_SNIPPET_MAX: Final = 120


class EvidenceSource(StrEnum):
    STAMP = "stamp"
    TITLE = "title"
    PAGE_LABEL = "page_label"
    FILE_NAME = "file_name"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class PageInput:
    page_index: int
    text: str
    file_name: str
    page_label: str | None = None


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    source: EvidenceSource
    snippet: str  # не длиннее 120 символов исходного текста


@dataclass(frozen=True, slots=True)
class PassportCandidate:
    page_index: int
    section_mark: str | None = None
    sheet_kind: SheetKind | None = None
    stage: str | None = None
    building: str | None = None
    section: str | None = None
    level_from: str | None = None
    level_to: str | None = None
    level_from_ordinal: int | None = None
    level_to_ordinal: int | None = None
    elevation_m: float | None = None
    code: str | None = None
    sheet_number: str | None = None
    title: str | None = None
    evidence: dict[str, FieldEvidence] = field(default_factory=dict)


# --------------------------------------------------------------------------- регулярки

_FLAGS: Final = re.IGNORECASE
_DASH: Final = r"[-–—−]"
_ID_CHARS: Final = r"[0-9A-Za-zА-Яа-яЁё]"
_LETTER: Final = r"[A-Za-zА-Яа-яЁё]"
# Шифр: «ПД-00284979-14-АР.ПЗ»; в текстовом слое бывают пробелы: «ПД -00284979-14-ИОС 4.1-ПЗ».
_CODE_RE: Final = re.compile(
    rf"(?<![A-Za-zА-Яа-яЁё0-9-])(?:ПД|РД)[ \t]*{_DASH}[ \t]*\d{{5,}}"
    rf"(?:[ \t]*[-–—−._/][ \t]*{_ID_CHARS}+)*"
)
# «ИОС 4.1», «АР 4»: пробел внутри шифра склеивается, только если слева марка раздела.
_CODE_SPACED_TAIL_RE: Final = re.compile(r"[ \t]+(\d{1,2}(?:\.\d+)?)(?!\d)")
_CODE_LAST_LETTERS_RE: Final = re.compile(r"([A-Za-zА-Яа-яЁё]+)$")
_CODE_REST_RE: Final = re.compile(rf"(?:[ \t]*[-–—−._/][ \t]*{_ID_CHARS}+)*")
_CODE_PREFIX_RE: Final = re.compile(rf"^(ПД|РД){_DASH}\d+", _FLAGS)
_TEXT_SUFFIXES: Final = frozenset({"ПЗ", "ТЧ"})
# Суффикс шифра по ГОСТ Р 21.101 / 21.110: «ПЗ» — пояснительная записка, «ТЧ» — текстовая часть,
# «СО» — спецификация оборудования. Работает, когда заголовка листа в тексте нет.
_CODE_SUFFIX_KINDS: Final = {
    "ПЗ": SheetKind.TEXT,
    "ТЧ": SheetKind.TEXT,
    "СО": SheetKind.TABLE,
}
_CORPS_IN_CODE_RE: Final = re.compile(r"(?:^|[-._/])КОР(?:ПУС)?(\d+)(?:$|[-._/])", _FLAGS)


_NUM: Final = r"\d+(?:\.\d+)?(?:\s*[,–—-]\s*\d+(?:\.\d+)?)*"
_BUILDING_LINE_RE: Final = re.compile(rf"^Корпус\w*\s+({_NUM})(?:[.,;:\s].{{0,40}})?$", _FLAGS)
_BUILDING_FILE_RE: Final = re.compile(rf"(?<![\w])Корп(?:ус\w*)?[\s._-]*({_NUM})", _FLAGS)
_SECTION_LINE_RE: Final = re.compile(
    rf"^(?:Блок[\s-]*)?Секци[яи]\s+({_NUM})(?:[.,;:\s].{{0,40}})?$", _FLAGS
)
_SECTION_TITLE_RE: Final = re.compile(rf"(?<![\w])Секци[яи]\s+({_NUM})", _FLAGS)
_BUILDING_TITLE_RE: Final = re.compile(rf"(?<![\w])Корпус\w*\s+({_NUM})", _FLAGS)

_CONTINUATION_END_RE: Final = re.compile(r"(?:\bна|отм\.?|,|\(|\w(?:ого|его))\s*$", _FLAGS)
_CONTINUATION_START_RE: Final = re.compile(
    r"^(?:на\s+отм|отм\.|\(?часть\s+\d|\)|и\s|этаж|пространств|подполь|подвал)", _FLAGS
)
_TOC_RE: Final = re.compile(r"\.{4,}|…{2,}")
# Титульный лист и заголовки частей томов — не заголовок листа: «Раздел 2. Схема планировочной…».
_NOT_TITLE_RE: Final = re.compile(r"^(?:под)?раздел\b|^часть\s+\d|^том\b|^книга\b", _FLAGS)

_TITLE_MAX_LEN: Final = 200
_TITLE_START_MAX: Final = 20
_MAX_CONTINUATION: Final = 2
_FILE_EXT_RE: Final = re.compile(r"\.pdf$", _FLAGS)

_KIND_PRIORITY: Final = {
    SheetKind.FLOOR_PLAN: 0,
    SheetKind.SCHEME: 1,
    SheetKind.SECTION: 2,
    SheetKind.FACADE: 3,
    SheetKind.GENERAL_DATA: 4,
    SheetKind.TABLE: 5,
    SheetKind.TEXT: 6,
    SheetKind.OTHER: 7,
}


# --------------------------------------------------------------------------- служебное


def _snippet(text: str) -> str:
    return SPACES_RE.sub(" ", text).strip()[:_SNIPPET_MAX]


def _lines(text: str) -> list[str]:
    result = []
    for raw in text.splitlines():
        line = SPACES_RE.sub(" ", raw).strip()
        if line:
            result.append(line)
    return result


def _normalize_numbers(raw: str) -> str:
    """«2 – 6» → «2-6», «1, 2» → «1,2»."""
    return re.sub(r"\s*([,–—-])\s*", lambda m: "," if m.group(1) == "," else "-", raw.strip())


def _code_tail(code: str) -> str:
    """Часть шифра после числового идентификатора: «ПД-00284979-14-АР.ПЗ» → «-14-АР.ПЗ»."""
    prefix = _CODE_PREFIX_RE.match(code)
    return code[prefix.end() :] if prefix else code


def _code_tokens(code: str) -> list[str]:
    return [token for token in re.split(r"[-._/]+", _code_tail(code).upper()) if token]


def _kind_from_code(code: str, section_mark: str | None) -> SheetKind | None:
    """Тип листа по шифру: раздел «ПЗ» либо суффикс «-ПЗ», «-ТЧ», «-СО» после марки."""
    if section_mark == "ПЗ":
        return SheetKind.TEXT
    for token in _code_tokens(code)[1:]:
        if token in _CODE_SUFFIX_KINDS:
            return _CODE_SUFFIX_KINDS[token]
    return None


def _file_stem(file_name: str) -> str:
    name = file_name.replace("\\", "/").rsplit("/", 1)[-1]
    return _FILE_EXT_RE.sub("", name)


# --------------------------------------------------------------------------- шифр


def _code_matches(text: str) -> Iterator[tuple[str, str]]:
    """(сырой фрагмент, шифр без пробелов) для каждого шифра в тексте."""
    for match in _CODE_RE.finditer(text):
        raw = match.group(0)
        tail = _CODE_SPACED_TAIL_RE.match(text, match.end())
        letters = _CODE_LAST_LETTERS_RE.search(raw)
        if tail is not None and letters is not None:
            word = letters.group(1).upper()
            first_digits = tail.group(1).split(".")[0]
            if word not in _TEXT_SUFFIXES and match_section_mark(word + first_digits):
                raw += tail.group(0)
                rest = _CODE_REST_RE.match(text, match.end() + len(tail.group(0)))
                raw += "" if rest is None else rest.group(0)
        yield raw, compact_code(raw)


def _file_code(file_name: str) -> str | None:
    for _, code in _code_matches(_file_stem(file_name)):
        return code
    return None


def _page_code(text: str, lines: list[str], stamp: Stamp, file_code: str | None) -> str | None:
    """Шифр страницы: у штампа, совпадающий с шифром файла и частый — надёжнее."""
    window_text = "\n".join(lines[i] for i in stamp.window)
    found: dict[str, list[bool]] = {}
    for raw, code in _code_matches(text):
        if not _code_tokens(code):
            continue
        found.setdefault(code, []).append(raw.strip() in window_text)
    if not found:
        return None
    return max(
        found,
        key=lambda code: (any(found[code]), code == file_code, len(found[code]), -len(code)),
    )


# --------------------------------------------------------------------------- заголовок


def _title_candidates(
    lines: list[str], indices: tuple[int, ...], anchors: tuple[int, ...], *, capital: bool = False
) -> list[tuple[int, int, SheetKind]]:
    """(расстояние до штампа, индекс строки, тип) для строк, начинающихся с типа листа.

    `capital` — строка обязана начинаться с заглавной буквы (отсекает обрывки фраз из текста).
    """
    result = []
    for i in indices:
        line = lines[i]
        if len(line) > _TITLE_MAX_LEN or _TOC_RE.search(line) or _NOT_TITLE_RE.match(line):
            continue
        if capital and not line[:1].isupper():
            continue
        match = sheet_kind_match(line)
        if match is None or match[1] > _TITLE_START_MAX:
            continue
        result.append((min((abs(i - a) for a in anchors), default=0), i, match[0]))
    return result


def _pick_title(lines: list[str], stamp: Stamp) -> tuple[int, SheetKind] | None:
    """Заголовок в окне штампа: ближайшая к штампу строка."""
    candidates = _title_candidates(lines, stamp.window, stamp.anchors)
    if not candidates:
        return None
    _, index, kind = min(candidates, key=lambda item: (item[0], item[1]))
    return index, kind


def _pick_title_global(lines: list[str]) -> tuple[int, SheetKind] | None:
    """Запасной путь без заголовка у штампа: чертёжные типы раньше таблиц, ранняя строка раньше."""
    candidates = _title_candidates(lines, tuple(range(len(lines))), (), capital=True)
    if not candidates:
        return None
    _, index, kind = min(candidates, key=lambda item: (_KIND_PRIORITY[item[2]], item[1]))
    return index, kind


def _join_title(lines: list[str], index: int) -> str:
    parts = [lines[index]]
    cursor = index
    while len(parts) <= _MAX_CONTINUATION and cursor + 1 < len(lines):
        nxt = lines[cursor + 1]
        if not (_CONTINUATION_END_RE.search(parts[-1]) or _CONTINUATION_START_RE.match(nxt)):
            break
        if STAGE_ANCHOR_RE.search(nxt) or len(nxt) > _TITLE_MAX_LEN:
            break
        parts.append(nxt)
        cursor += 1
    return " ".join(parts)[:_TITLE_MAX_LEN]


# --------------------------------------------------------------------------- штамп


def _first_line_group(
    pattern: re.Pattern[str], lines: list[str], indices: tuple[int, ...]
) -> tuple[str, str] | None:
    for i in indices:
        match = pattern.match(lines[i])
        if match is not None:
            return _normalize_numbers(match.group(1)), lines[i]
    return None


# --------------------------------------------------------------------------- разбор


def parse_page(page: PageInput) -> PassportCandidate:
    text = page.text or ""
    lines = _lines(text)
    stamp = stamp_window(lines)
    evidence: dict[str, FieldEvidence] = {}

    def put(name: str, source: EvidenceSource, snippet: str) -> None:
        evidence[name] = FieldEvidence(source, _snippet(snippet))

    stem = _file_stem(page.file_name)

    # --- шифр и раздел
    file_code = _file_code(page.file_name)
    code = _page_code(text, lines, stamp, file_code)
    code_source = EvidenceSource.STAMP
    if code is None and file_code is not None:
        code, code_source = file_code, EvidenceSource.FILE_NAME
    if code is not None:
        put("code", code_source, code)

    section_mark = None if code is None else match_section_mark(_code_tail(code))
    if section_mark is not None and code is not None:
        put("section_mark", code_source, code)
    else:
        section_mark = match_section_mark(stem)
        if section_mark is not None:
            put("section_mark", EvidenceSource.FILE_NAME, stem)

    code_kind = None if code is None else _kind_from_code(code, section_mark)
    is_text = code_kind == SheetKind.TEXT

    # --- стадия и номер листа
    stage, sheet_number, stamp_snippet = stamp_stage_and_sheet(text, lines)
    if stage is not None and stamp_snippet is not None:
        put("stage", EvidenceSource.STAMP, stamp_snippet)
    elif code is not None and (prefix := _CODE_PREFIX_RE.match(code)) is not None:
        stage = stage_of(prefix.group(1))
        put("stage", code_source, code)
    near = sheet_number_near_code(lines, code) if sheet_number is None else None
    if sheet_number is not None and stamp_snippet is not None:
        put("sheet_number", EvidenceSource.STAMP, stamp_snippet)
    elif near is not None:
        sheet_number = near[0]
        put("sheet_number", EvidenceSource.STAMP, near[1])
    elif page.page_label and label_is_meaningful(page.page_label, page.page_index):
        sheet_number = page.page_label
        put("sheet_number", EvidenceSource.PAGE_LABEL, page.page_label)

    # --- заголовок и тип листа
    picked = _pick_title(lines, stamp)
    if picked is None and not is_text:
        picked = _pick_title_global(lines)
    title: str | None = None
    sheet_kind: SheetKind | None = None
    if picked is not None:
        title = _join_title(lines, picked[0])
        sheet_kind = picked[1]
        put("title", EvidenceSource.TITLE, title)
        put("sheet_kind", EvidenceSource.TITLE, title)
    elif code_kind is not None and code is not None:
        sheet_kind = code_kind
        put("sheet_kind", code_source, code)

    # --- корпус и секция
    building: str | None = None
    section: str | None = None
    if title is not None:
        found = _BUILDING_TITLE_RE.search(title)
        if found is not None:
            building = _normalize_numbers(found.group(1))
            put("building", EvidenceSource.TITLE, found.group(0))
        found = _SECTION_TITLE_RE.search(title)
        if found is not None:
            section = _normalize_numbers(found.group(1))
            put("section", EvidenceSource.TITLE, found.group(0))
    if not is_text:
        hit = _first_line_group(_BUILDING_LINE_RE, lines, stamp.window)
        if building is None and hit is not None:
            building = hit[0]
            put("building", EvidenceSource.STAMP, hit[1])
        hit = _first_line_group(_SECTION_LINE_RE, lines, stamp.window)
        if section is None and hit is not None:
            section = hit[0]
            put("section", EvidenceSource.STAMP, hit[1])
    if building is None and code is not None and (corps := _CORPS_IN_CODE_RE.search(code)):
        building = corps.group(1)
        put("building", code_source, code)
    if building is None:
        by_name = _BUILDING_FILE_RE.search(stem)
        if by_name is not None:
            building = _normalize_numbers(by_name.group(1))
            put("building", EvidenceSource.FILE_NAME, by_name.group(0))
        elif (corps := _CORPS_IN_CODE_RE.search(stem)) is not None:
            building = corps.group(1)
            put("building", EvidenceSource.FILE_NAME, stem)

    # --- уровень и отметка
    level_from = level_to = None
    ordinal_from = ordinal_to = None
    elevation: float | None = None
    if title is not None:
        level = parse_level(title)
        if level is not None:
            level_from, level_to = level.text_from, level.text_to
            ordinal_from, ordinal_to = level.ordinal_from, level.ordinal_to
            put("level_from", EvidenceSource.TITLE, level.snippet)
            put("level_to", EvidenceSource.TITLE, level.snippet)
            if ordinal_from is not None:
                put("level_from_ordinal", EvidenceSource.TITLE, level.snippet)
            if ordinal_to is not None:
                put("level_to_ordinal", EvidenceSource.TITLE, level.snippet)
        parsed = parse_elevation(title)
        if parsed is not None:
            elevation = parsed[0]
            put("elevation_m", EvidenceSource.TITLE, parsed[1])

    return PassportCandidate(
        page_index=page.page_index,
        section_mark=section_mark,
        sheet_kind=sheet_kind,
        stage=stage,
        building=building,
        section=section,
        level_from=level_from,
        level_to=level_to,
        level_from_ordinal=ordinal_from,
        level_to_ordinal=ordinal_to,
        elevation_m=elevation,
        code=code,
        sheet_number=sheet_number,
        title=title,
        evidence=evidence,
    )


# --------------------------------------------------------------------------- PDF


def extract_pdf_pages(stream: BinaryIO, file_name: str) -> Iterator[PageInput]:
    """Страницы PDF по одной: текстовый слой и метка страницы. Без OCR и растра."""
    reader = PdfReader(stream)
    try:
        labels: list[str] | None = list(reader.page_labels)
    except Exception:  # битое дерево меток страниц не мешает разбору текста
        labels = None
    for index, page in enumerate(reader.pages):
        try:
            text = page_text(page, reader)
        except Exception:  # страница с нечитаемым потоком: пустой текст, не падение файла
            text = ""
        label = labels[index] if labels is not None and index < len(labels) else None
        yield PageInput(page_index=index, text=text, file_name=file_name, page_label=label)


def dictionary_versions() -> dict[str, str]:
    """Версии разборщика и словарей: пишутся в паспорт для воспроизводимости."""
    return {
        "parser": PARSER_VERSION,
        "sections": SECTION_MARKS_VERSION,
        "sheet_kinds": SHEET_KINDS_VERSION,
    }
