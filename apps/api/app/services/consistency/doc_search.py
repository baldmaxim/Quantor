"""Поиск ответов на вопросы к документации по тексту страниц (ADR-0043, шаг 2, этапы В2-В3).

Чистая функция: на входе каталог и страницы (текст + паспорт листа), на выходе по каждому
вопросу кандидаты - нормализованное значение, цитата, ссылка на страницу, область и оценка.
Без IO и побочных эффектов; модель чисел не выдаёт: якоря и числа ищутся шаблонами каталога
(`consistency.doc_questions.v1`).

Оценка кандидата (0-100, целая, детерминированная):

    источник  40 - 8 на каждую позицию в списке источников вопроса (не меньше 8)
    якорь     вес сработавшего якоря (до 20)
    контекст  +5 за каждый ещё один якорь рядом и +5 за контекст «коридор / МОП» и т. п. (до 10)
    слабо     -10, если перед якорем слово исключения («допускается увеличение», «настенный»)
    значение  30 - число с единицей («2,70 м», «200 мм», «1000×500»); 20 - число без единицы после
              якоря («тщ. 200») или неполное значение (тип пола без толщины); минус 5 за каждое
              следующее по удалённости число в окне вокруг якоря

Отметки уровня («+3.000», «отм. +47,600») высотой не считаются: число со знаком «+» и число после
«отм.» отбрасываются, число без единицы берётся только сразу после слова-якоря.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final

from app.services.consistency.dictionaries import (
    SECTION_MARKS_VERSION,
    SHEET_KINDS_VERSION,
    SheetKind,
    normalize_mark,
)
from app.services.consistency.doc_questions import (
    DOC_QUESTIONS,
    DOC_QUESTIONS_VERSION,
    DocAnchor,
    DocQuestion,
    DocQuestionCode,
    DocSource,
    DocValueKind,
    ExtractorKind,
    NormAssumption,
    is_customer_document,
)
from app.services.consistency.sheet_passport import PassportCandidate

DOC_SEARCH_VERSION: Final = "consistency.doc_search.v1"
DEFAULT_TOP_N: Final = 5
QUOTE_LIMIT: Final = 300

_BEFORE: Final = 100  # окно значения и контекста вокруг якоря, символы
_AFTER: Final = 200
_MAX_HITS_PER_PAGE: Final = 40
_MAX_TEXT: Final = 600_000
_MAX_VALUES_PER_ANCHOR: Final = 3
_RANK_PENALTY: Final = 5
_WEAK_PENALTY: Final = 10
_COMPACT_AT: Final = 2000  # потоковое слияние, чтобы не копить все находки комплекта
_COMPACT_KEEP: Final = 500


# --------------------------------------------------------------------------- типы


class DocSearchStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class DocSearchPage:
    """Страница для поиска: текст, ссылка и паспорт-кандидат страницы (раздел, тип, область)."""

    file_name: str
    page_index: int
    text: str
    revision_id: str | None = None
    label: str | None = None
    passport: PassportCandidate | None = None
    # Файл целиком - документ Заказчика; None - определить по имени файла и заголовку 1-й страницы.
    is_customer_doc: bool | None = None


@dataclass(frozen=True, slots=True)
class DocValue:
    """Нормализованное значение: мм целым числом, диапазон, «ш×в» либо текст."""

    kind: DocValueKind
    display: str
    numbers: tuple[int, ...] = ()
    qualifier: str | None = None  # "min" - «не менее», "max" - «не более»
    code: str | None = None  # "round", "rosette_down", "rosette_up", "layers_sum"

    @property
    def key(self) -> tuple[str, str, tuple[int, ...], str | None, str | None]:
        return (self.kind.value, self.display, self.numbers, self.qualifier, self.code)


@dataclass(frozen=True, slots=True)
class DocScope:
    """Область страницы по паспорту листа; не определено - None."""

    building: str | None = None
    section: str | None = None
    level_from: str | None = None
    level_to: str | None = None


@dataclass(frozen=True, slots=True)
class DocCandidate:
    question: DocQuestionCode
    value: DocValue
    quote: str  # не длиннее QUOTE_LIMIT, без NUL и лишних пробелов
    quote_focus: int  # позиция якоря в цитате
    file_name: str
    revision_id: str | None
    page_index: int
    page_label: str | None
    source_label: str
    source_rank: int
    section_mark: str | None
    sheet_kind: SheetKind | None
    scope: DocScope
    score: int
    occurrences: int = 1  # сколько одинаковых находок слито в этот кандидат


@dataclass(frozen=True, slots=True)
class DocQuestionResult:
    question: DocQuestionCode
    status: DocSearchStatus
    candidates: tuple[DocCandidate, ...]
    # Только при NOT_FOUND и только если в каталоге есть норматив; это допущение, а не ответ.
    assumption: NormAssumption | None
    versions: dict[str, str]


def doc_search_versions() -> dict[str, str]:
    """Версии каталога, поиска и словарей: пишутся в результат для воспроизводимости."""
    return {
        "catalog": DOC_QUESTIONS_VERSION,
        "search": DOC_SEARCH_VERSION,
        "sections": SECTION_MARKS_VERSION,
        "sheet_kinds": SHEET_KINDS_VERSION,
    }


# --------------------------------------------------------------------------- текст

_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0e-\x1f\x7f​-‏ -‮﻿]")
_SPACES_RE: Final = re.compile(r"\s+")
_DASHES: Final = "‐‑‒–—―−"
# Посимвольно, длина не меняется: смещения в поисковом тексте равны смещениям в цитате.
_SEARCH_TABLE: Final = str.maketrans({"ё": "е", "Ё": "Е", **dict.fromkeys(_DASHES, "-")})


def clean_text(text: str) -> str:
    """Без NUL и управляющих символов, пробелы и переводы строк схлопнуты в один пробел."""
    return _SPACES_RE.sub(" ", _CONTROL_RE.sub(" ", text)).strip()


# --------------------------------------------------------------------------- числа

_NUM: Final = r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_NOT_AFTER_DIGIT: Final = r"(?<!\d)(?<!\d[.,])"
_UNIT_END: Final = r"(?![\w²³/])"

_LEN_RE: Final = re.compile(
    rf"(?P<sign>[+-])?{_NOT_AFTER_DIGIT}(?P<num>{_NUM})\s*(?P<unit>мм|см|м){_UNIT_END}",
    re.IGNORECASE,
)
_BARE_RE: Final = re.compile(
    rf"\s*(?:[=:]|не\s+менее|не\s+более|≥|≤)?\s*(?P<sign>[+-])?(?P<num>{_NUM})(?!\d)"
    rf"(?:\s*(?P<unit>мм|см|м){_UNIT_END})?",
    re.IGNORECASE,
)
_RANGE_RE: Final = re.compile(
    rf"{_NOT_AFTER_DIGIT}(?P<a>{_NUM})\s*(?:мм|см|м)?\s*(?:до|-)\s*(?P<b>{_NUM})\s*"
    rf"(?P<unit>мм|см|м){_UNIT_END}",
    re.IGNORECASE,
)
_RECT_RE: Final = re.compile(
    rf"{_NOT_AFTER_DIGIT}(?P<w>\d{{2,4}})\s*[xх×*]\s*(?P<h>\d{{2,4}})(?!\d)(?![.,]\d)",
    re.IGNORECASE,
)
_ROUND_RE: Final = re.compile(
    r"(?:[Øø∅⌀]|диаметр\w*\.?|(?<![a-zа-я\d])d\s*=)\s*(?P<d>\d{2,4})(?!\d)(?![.,]\d)",
    re.IGNORECASE,
)
# Регистр важен: «ДУ-2.3» - система дымоудаления, «Ду315» - условный проход трубы.
_SYSTEM_RE: Final = re.compile(r"(?<!\w)(?:КДУ|ДУ|ДП)\s*-?\s*\d+(?:[.,]\d+)*(?:-\w+)?")
_QUALIFIER_MIN_RE: Final = re.compile(r"(?:не\s+менее|не\s+ниже|≥)\s*$", re.IGNORECASE)
_QUALIFIER_MAX_RE: Final = re.compile(r"(?:не\s+более|не\s+выше|≤)\s*$", re.IGNORECASE)
_ELEVATION_WORD_RE: Final = re.compile(r"отм\w*\.?\s*$", re.IGNORECASE)
_THREE_DECIMALS_RE: Final = re.compile(r"[.,]\d{3}$")

# «Тип П-1.3а (МОП ...)» и «П-3. Полы в МОП ...».
_FLOOR_TYPE_RE: Final = re.compile(
    r"(?<!\w)п-?\s*(?P<code>\d+(?:\.\d+)?[а-я]?)"
    r"(?=\s*\(|[.\s]+пол\w*\s+(?:в\s*)?(?:моп|коридор|мест\w+\s+общего))",
    re.IGNORECASE,
)
_BASE_SLAB_RE: Final = re.compile(r"монолитн|железобетонн|ж\s*/?\s*б|основани", re.IGNORECASE)
_FLOOR_AFTER: Final = 500  # пирог пола длиннее общего окна значения
_LAYER_RE: Final = re.compile(rf"{_NOT_AFTER_DIGIT}(?P<n>\d{{1,3}})\s*мм{_UNIT_END}", re.IGNORECASE)
_SPRINKLER_MODEL_RE: Final = re.compile(
    r"(?<![а-яa-z])(?P<model>(?:свн|свв|свс|спн|спв|двн|двв|дпн|дпв|дсн|дсв)"
    r"(?:\s*-?\s*\d{1,3}(?:[-/][a-zа-я\d]+)?)?)(?![а-я])",
    re.IGNORECASE,
)
_ROSETTE_RE: Final = re.compile(
    r"розетк\w*\s+(?P<a>вниз|вверх)|(?P<b>вниз|вверх)\s+розетк", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class _Found:
    value: DocValue
    start: int
    end: int
    points: int  # очки за значение до штрафа за удалённость


def _parse_number(raw: str) -> float:
    return float(raw.replace(" ", "").replace(",", "."))


def _to_mm(raw: str, unit: str | None) -> int:
    value = _parse_number(raw)
    if unit is None:
        # Без единицы: десятичное число до 30 - метры, остальное - миллиметры.
        factor = 1000.0 if ("," in raw or "." in raw) and value <= 30 else 1.0
    else:
        factor = {"мм": 1.0, "см": 10.0, "м": 1000.0}[unit.lower()]
    return round(value * factor)


def _distance(anchor: tuple[int, int], start: int, end: int) -> int:
    """Расстояние от якоря до числа; число перед якорем «дальше» на штраф, чтобы после - раньше."""
    if start >= anchor[1]:
        return start - anchor[1]
    if end <= anchor[0]:
        return anchor[0] - end + 15
    return 0


def _qualifier(text: str, start: int) -> str | None:
    before = text[max(0, start - 16) : start]
    if _QUALIFIER_MIN_RE.search(before):
        return "min"
    if _QUALIFIER_MAX_RE.search(before):
        return "max"
    return None


def _is_elevation(text: str, match: re.Match[str]) -> bool:
    """Отметка уровня, а не размер: «+3.000», «отм. 47,600 м», «-0,150 м»."""
    sign = match.group("sign")
    if sign == "+":
        return True
    if _ELEVATION_WORD_RE.search(text[max(0, match.start() - 14) : match.start()]):
        return True
    return (
        sign == "-"
        and (match.group("unit") or "").lower() == "м"
        and _THREE_DECIMALS_RE.search(match.group("num")) is not None
    )


def _window(text: str, anchor: tuple[int, int]) -> tuple[int, int]:
    return max(0, anchor[0] - _BEFORE), min(len(text), anchor[1] + _AFTER)


def _within(question: DocQuestion, *values: int) -> bool:
    return all(question.min_mm <= value <= question.max_mm for value in values)


def _length_found(
    question: DocQuestion, text: str, anchor: tuple[int, int], *, bare: bool
) -> list[_Found]:
    """Числа-длины в окне вокруг якоря, ближайшие первыми (до _MAX_VALUES_PER_ANCHOR)."""
    lo, hi = _window(text, anchor)
    items: list[tuple[int, int, _Found]] = []
    for match in _LEN_RE.finditer(text, lo, hi):
        if _is_elevation(text, match):
            continue
        mm = _to_mm(match.group("num"), match.group("unit"))
        if not _within(question, mm):
            continue
        value = DocValue(
            DocValueKind.LENGTH_MM, str(mm), (mm,), _qualifier(text, match.start()), None
        )
        found = _Found(value, match.start(), match.end(), 30)
        items.append((_distance(anchor, found.start, found.end), found.start, found))
    if question.code == DocQuestionCode.LIFT_DOOR_HEIGHT:
        # «1200*2400» после «Дверь (ширина х высота), мм»: ответ - вторая величина, высота.
        for rect in _RECT_RE.finditer(text, lo, hi):
            width, height = int(rect.group("w")), int(rect.group("h"))
            if height <= width or not _within(question, height):
                continue
            value = DocValue(DocValueKind.LENGTH_MM, str(height), (height,), None, None)
            found = _Found(value, rect.start(), rect.end(), 30)
            items.append((_distance(anchor, found.start, found.end), found.start, found))
    if bare:
        bare_match = _BARE_RE.match(text, anchor[1])
        if (
            bare_match is not None
            and _bare_ok(text, bare_match)
            and not _is_elevation(text, bare_match)
        ):
            mm = _to_mm(bare_match.group("num"), bare_match.group("unit"))
            if _within(question, mm):
                value = DocValue(DocValueKind.LENGTH_MM, str(mm), (mm,), None, None)
                points = 30 if bare_match.group("unit") else 20
                found = _Found(value, bare_match.start("num"), bare_match.end(), points)
                items.append((0, found.start, found))
    items.sort(key=lambda item: (item[0], item[1]))
    result: list[_Found] = []
    seen: set[tuple[str, str | None]] = set()
    for _, _, found in items:
        key = (found.value.display, found.value.qualifier)
        if key not in seen:
            seen.add(key)
            result.append(found)
    return result[:_MAX_VALUES_PER_ANCHOR]


def _bare_ok(text: str, match: re.Match[str]) -> bool:
    """Число без единицы: дальше не буква, не процент и не «×» (иначе это не размер)."""
    if match.group("unit"):
        return True
    tail = text[match.end() : match.end() + 3].lstrip()
    return not tail or not (tail[0].isalpha() or tail[0] in "%×*²³")


def _range_found(question: DocQuestion, text: str, anchor: tuple[int, int]) -> list[_Found]:
    lo, hi = _window(text, anchor)
    items: list[tuple[int, int, _Found]] = []
    for match in _RANGE_RE.finditer(text, lo, hi):
        unit = match.group("unit")
        low, high = _to_mm(match.group("a"), unit), _to_mm(match.group("b"), unit)
        if low >= high or not _within(question, low, high):
            continue
        value = DocValue(DocValueKind.RANGE_MM, f"{low}-{high}", (low, high), None, None)
        found = _Found(value, match.start(), match.end(), 30)
        items.append((_distance(anchor, found.start, found.end), found.start, found))
    items.sort(key=lambda item: (item[0], item[1]))
    if items:
        return [found for _, _, found in items][:_MAX_VALUES_PER_ANCHOR]
    # Диапазона нет: одиночное число - менее полный ответ.
    return [
        replace(found, points=20) for found in _length_found(question, text, anchor, bare=False)
    ]


def _nearest_system(text: str, start: int) -> str | None:
    last: str | None = None
    for match in _SYSTEM_RE.finditer(text, max(0, start - 120), start):
        last = _SPACES_RE.sub("", match.group(0)).upper()
    return last


def _section_found(question: DocQuestion, text: str, anchor: tuple[int, int]) -> list[_Found]:
    lo, hi = _window(text, anchor)
    items: list[tuple[int, int, _Found]] = []
    with_system = question.code == DocQuestionCode.DUCT_SECTION
    for match in _RECT_RE.finditer(text, lo, hi):
        width, height = int(match.group("w")), int(match.group("h"))
        if not _within(question, width, height):
            continue
        system = _nearest_system(text, match.start()) if with_system else None
        size = f"{width}x{height}"
        value = DocValue(
            DocValueKind.SECTION_MM,
            size if system is None else f"{system}: {size}",
            (width, height),
            None,
            None,
        )
        found = _Found(value, match.start(), match.end(), 30)
        items.append((_distance(anchor, found.start, found.end), found.start, found))
    if with_system:
        for match in _ROUND_RE.finditer(text, lo, hi):
            diameter = int(match.group("d"))
            if not _within(question, diameter):
                continue
            system = _nearest_system(text, match.start())
            display = f"Ø{diameter}" if system is None else f"{system}: Ø{diameter}"
            value = DocValue(DocValueKind.SECTION_MM, display, (diameter,), None, "round")
            found = _Found(value, match.start(), match.end(), 30)
            items.append((_distance(anchor, found.start, found.end), found.start, found))
    items.sort(key=lambda item: (item[0], item[1]))
    return [found for _, _, found in items][:_MAX_VALUES_PER_ANCHOR]


def _floor_buildup_found(question: DocQuestion, text: str, anchor: tuple[int, int]) -> list[_Found]:
    """Тип пола «П-1.3а» и слои «NN мм» после якоря до основания (плиты) или следующего типа.

    Сумма слоёв («итого») - только если список закончился основанием: иначе слои могли не
    поместиться в окно, и сумма была бы заниженной.
    """
    hi = min(len(text), anchor[1] + _FLOOR_AFTER)
    type_match = _FLOOR_TYPE_RE.search(text, anchor[0], hi)
    layers_from = anchor[1] if type_match is None else max(anchor[1], type_match.end())
    layers_to = hi
    if type_match is not None:
        following = _FLOOR_TYPE_RE.search(text, layers_from, hi)
        if following is not None:
            layers_to = following.start()
    base = _BASE_SLAB_RE.search(text, layers_from, layers_to)
    complete = base is not None
    if base is not None:
        layers_to = base.start()
    layers: list[tuple[int, int, int]] = []
    for match in _LAYER_RE.finditer(text, layers_from, layers_to):
        mm = int(match.group("n"))
        if _within(question, mm):
            layers.append((mm, match.start(), match.end()))
    layers = layers[:8]
    if type_match is None:
        if not layers:
            return []
        numbers = tuple(item[0] for item in layers[:4])
        display = "толщина " + ", ".join(f"{n} мм" for n in numbers)
        value = DocValue(DocValueKind.TEXT, display, numbers, None, None)
        return [_Found(value, layers[0][1], layers[min(3, len(layers) - 1)][2], 30)]
    code = type_match.group("code")
    start, end = type_match.start(), type_match.end()
    if not layers:
        value = DocValue(DocValueKind.TEXT, f"тип П-{code}", (), None, None)
        return [_Found(value, start, end, 20)]
    end = layers[-1][2]
    parts = [item[0] for item in layers]
    listed = "+".join(str(n) for n in parts)
    if complete:
        total = sum(parts)
        display = f"тип П-{code}; слои {listed} мм, итого {total} мм"
        value = DocValue(DocValueKind.TEXT, display, (total,), None, "layers_sum")
        return [_Found(value, start, end, 30)]
    display = f"тип П-{code}; слои {listed} мм (список мог быть неполным)"
    value = DocValue(DocValueKind.TEXT, display, tuple(parts), None, "layers_partial")
    return [_Found(value, start, end, 20)]


def _sprinkler_found(text: str, anchor: tuple[int, int]) -> list[_Found]:
    lo, hi = max(0, anchor[0] - 60), min(len(text), anchor[1] + _AFTER)
    model = min(
        _SPRINKLER_MODEL_RE.finditer(text, lo, hi),
        key=lambda m: (_distance(anchor, m.start(), m.end()), m.start()),
        default=None,
    )
    rosette = min(
        _ROSETTE_RE.finditer(text, lo, hi),
        key=lambda m: (_distance(anchor, m.start(), m.end()), m.start()),
        default=None,
    )
    if model is None and rosette is None:
        return []
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    code: str | None = None
    if model is not None:
        parts.append(_SPACES_RE.sub("", model.group("model")).upper())
        spans.append((model.start(), model.end()))
    if rosette is not None:
        direction = (rosette.group("a") or rosette.group("b")).lower()
        parts.append(f"розеткой {direction}")
        code = "rosette_down" if direction == "вниз" else "rosette_up"
        spans.append((rosette.start(), rosette.end()))
    value = DocValue(DocValueKind.ENUM, "; ".join(parts), (), None, code)
    points = 30 if len(parts) == 2 else 20
    return [_Found(value, min(s[0] for s in spans), max(s[1] for s in spans), points)]


def _extract(
    question: DocQuestion, text: str, anchor: tuple[int, int], rule: DocAnchor
) -> list[_Found]:
    match question.extractor:
        case ExtractorKind.LENGTH:
            return _length_found(question, text, anchor, bare=rule.bare_number)
        case ExtractorKind.RANGE:
            return _range_found(question, text, anchor)
        case ExtractorKind.SECTION:
            return _section_found(question, text, anchor)
        case ExtractorKind.FLOOR_BUILDUP:
            return _floor_buildup_found(question, text, anchor)
        case ExtractorKind.SPRINKLER_MODEL:
            return _sprinkler_found(text, anchor)


# --------------------------------------------------------------------------- источник и цитата


def _source_rank(question: DocQuestion, page: DocSearchPage, *, customer: bool) -> int | None:
    """Позиция первого подходящего источника вопроса; None - страница вопросу не подходит."""
    passport = page.passport
    mark = None if passport is None or passport.section_mark is None else passport.section_mark
    kind = None if passport is None else passport.sheet_kind
    for rank, source in enumerate(question.sources):
        if source.customer:
            if customer:
                return rank
            continue
        if customer or mark is None:
            continue
        if normalize_mark(mark) not in {normalize_mark(item) for item in source.section_marks}:
            continue
        if source.sheet_kinds and kind is not None and kind not in source.sheet_kinds:
            continue
        return rank
    return None


def _anchor_applies(rule: DocAnchor, source: DocSource) -> bool:
    """Якорь с `labels` - только в названных источниках; эксклюзивный источник - только им."""
    if rule.labels:
        return source.label in rule.labels
    return not source.exclusive


def _quote(text: str, lo: int, hi: int, anchor_start: int) -> tuple[str, int]:
    """Цитата ≤ QUOTE_LIMIT вокруг [lo, hi): границы подтягиваются к пробелам; позиция якоря."""
    span = hi - lo
    if span >= QUOTE_LIMIT:
        start, end = lo, lo + QUOTE_LIMIT
    else:
        pad = (QUOTE_LIMIT - span) // 2
        start, end = max(0, lo - pad), min(len(text), hi + pad)
    if start > 0 and text[start - 1] != " ":
        cut = text.find(" ", start, lo)
        if cut != -1:
            start = cut + 1
    if end < len(text) and text[end] != " ":
        cut = text.rfind(" ", hi, end)
        if cut != -1:
            end = cut
    piece = text[start:end]
    lead = len(piece) - len(piece.lstrip())
    return piece.strip(), max(0, anchor_start - start - lead)


# --------------------------------------------------------------------------- поиск


def _sort_key(candidate: DocCandidate) -> tuple[int, int, str, int, str]:
    return (
        -candidate.score,
        candidate.source_rank,
        candidate.file_name,
        candidate.page_index,
        candidate.quote,
    )


def _search_question(
    question: DocQuestion, page: DocSearchPage, rank: int, text: str, search: str
) -> list[DocCandidate]:
    source = question.sources[rank]
    hits: list[tuple[int, int, int]] = []  # (начало, конец, номер якоря)
    for index, rule in enumerate(question.anchors):
        if not _anchor_applies(rule, source):
            continue
        hits.extend((m.start(), m.end(), index) for m in rule.pattern.finditer(search))
    if not hits:
        return []
    hits.sort(key=lambda hit: (-question.anchors[hit[2]].weight, hit[0], hit[1]))
    hits = hits[:_MAX_HITS_PER_PAGE]
    passport = page.passport
    scope = (
        DocScope()
        if passport is None
        else DocScope(passport.building, passport.section, passport.level_from, passport.level_to)
    )
    source_points = max(8, 40 - 8 * rank)
    result: list[DocCandidate] = []
    for start, end, index in hits:
        anchor = (start, end)
        rule = question.anchors[index]
        lo, hi = _window(search, anchor)
        has_context = any(pattern.search(search, lo, hi) for pattern in question.context)
        if question.context_required and not has_context and not rule.context_free:
            continue
        excluded = [
            (m.start(), m.end())
            for pattern in question.value_exclusions
            for m in pattern.finditer(search, lo, hi)
        ]
        weak = any(pattern.search(search, lo, end) for pattern in question.weak_markers)
        extras = {
            other
            for o_start, o_end, other in hits
            if other != index and o_start < hi and o_end > lo
        }
        evidence = min(10, 5 * len(extras) + (5 if has_context else 0))
        values = [
            found
            for found in _extract(question, search, anchor, rule)
            if not any(found.start < e_end and found.end > e_start for e_start, e_end in excluded)
        ]
        for position, found in enumerate(values):
            quote, focus = _quote(text, min(start, found.start), max(end, found.end), start)
            score = (
                source_points
                + rule.weight
                + evidence
                + found.points
                - (_WEAK_PENALTY if weak else 0)
            )
            result.append(
                DocCandidate(
                    question=question.code,
                    value=found.value,
                    quote=quote,
                    quote_focus=focus,
                    file_name=page.file_name,
                    revision_id=page.revision_id,
                    page_index=page.page_index,
                    page_label=page.label,
                    source_label=source.label,
                    source_rank=rank,
                    section_mark=None if passport is None else passport.section_mark,
                    sheet_kind=None if passport is None else passport.sheet_kind,
                    scope=scope,
                    score=max(0, min(100, score - _RANK_PENALTY * position)),
                )
            )
    return result


def search_page(
    page: DocSearchPage, questions: Sequence[DocQuestion] = DOC_QUESTIONS
) -> list[DocCandidate]:
    """Кандидаты по одной странице, без слияния и отбора."""
    customer = (
        page.is_customer_doc
        if page.is_customer_doc is not None
        else is_customer_document(page.file_name, page.text if page.page_index == 0 else None)
    )
    ranks = [(q, _source_rank(q, page, customer=customer)) for q in questions]
    applicable = [(q, rank) for q, rank in ranks if rank is not None]
    if not applicable:
        return []
    text = clean_text(page.text)[:_MAX_TEXT]
    if not text:
        return []
    search = text.translate(_SEARCH_TABLE)
    result: list[DocCandidate] = []
    for question, rank in applicable:
        result.extend(_search_question(question, page, rank, text, search))
    return result


def _merge(
    candidates: Iterable[DocCandidate],
    key: Callable[[DocCandidate], Hashable],
    *,
    count: bool = True,
) -> list[DocCandidate]:
    """Слияние находок с одинаковым ключом: остаётся лучшая, `occurrences` суммируются.

    `count=False` - слияние внутри одной страницы: несколько якорей на одно место - одна находка
    (число совпадений берётся максимальным, а не суммой).
    """
    best: dict[Hashable, DocCandidate] = {}
    counts: dict[Hashable, int] = {}
    for candidate in candidates:
        group = key(candidate)
        total = counts.get(group, 0)
        counts[group] = (
            total + candidate.occurrences if count else max(total, candidate.occurrences)
        )
        current = best.get(group)
        if current is None or _sort_key(candidate) < _sort_key(current):
            best[group] = candidate
    return [replace(candidate, occurrences=counts[group]) for group, candidate in best.items()]


def _same_page(candidate: DocCandidate) -> Hashable:
    return (
        candidate.question,
        candidate.value.key,
        candidate.revision_id or candidate.file_name,
        candidate.page_index,
    )


def _same_quote(candidate: DocCandidate) -> Hashable:
    return (candidate.question, candidate.quote.lower(), candidate.value.key)


def _same_place(candidate: DocCandidate) -> Hashable:
    """Одно значение в одном файле и одной области - один кандидат, сколько бы страниц ни было."""
    return (
        candidate.question,
        candidate.value.key,
        candidate.revision_id or candidate.file_name,
        candidate.scope.building,
        candidate.scope.section,
    )


def rank_candidates(
    candidates: Iterable[DocCandidate], top_n: int = DEFAULT_TOP_N
) -> list[DocCandidate]:
    """Дедуп (одинаковая цитата и значение; то же значение в том же файле и области), сортировка,
    top-N. Порядок входа на результат не влияет."""
    per_page = _merge(candidates, _same_page, count=False)
    merged = _merge(_merge(per_page, _same_quote), _same_place)
    merged.sort(key=_sort_key)
    return merged[:top_n]


def search_doc_questions(
    pages: Iterable[DocSearchPage],
    questions: Sequence[DocQuestion] = DOC_QUESTIONS,
    *,
    top_n: int = DEFAULT_TOP_N,
) -> tuple[DocQuestionResult, ...]:
    """Результат по каждому вопросу каталога: кандидаты либо not_found (+ норматив-допущение)."""
    collected: dict[DocQuestionCode, list[DocCandidate]] = {q.code: [] for q in questions}
    for page in pages:
        for candidate in search_page(page, questions):
            bucket = collected[candidate.question]
            bucket.append(candidate)
            if len(bucket) > _COMPACT_AT:
                collected[candidate.question] = rank_candidates(bucket, _COMPACT_KEEP)
    versions = doc_search_versions()
    results: list[DocQuestionResult] = []
    for question in questions:
        ranked = rank_candidates(collected[question.code], top_n)
        results.append(
            DocQuestionResult(
                question=question.code,
                status=DocSearchStatus.FOUND if ranked else DocSearchStatus.NOT_FOUND,
                candidates=tuple(ranked),
                assumption=None if ranked else question.assumption,
                versions=dict(versions),
            )
        )
    return tuple(results)
