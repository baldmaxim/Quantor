"""Отметка пола и высота этажа из текста документации (заголовки планов этажей).

Отметка — `observed`: из заголовка плана выбранной страницы («План 15 этажа на отм. +50,900»).
Высота — `derived`: разность отметок соседних этажей того же корпуса/секции по всему PDF.
Не определилось — ошибка входа с просьбой ввести вручную; молчаливых умолчаний нет. Значение,
введённое человеком, остаётся основным, а расхождение с документацией — замечание.
Правила разбора заголовков (регулярные выражения, допуски) лежат в params/v1.json.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from cad_mep.errors import MepError
from cad_mep.params import Params

ELEVATION_LIMIT_MM = 1_000_000
EVIDENCE_LIMIT = 160

_RANGE = re.compile(r"^(-?\d+)\s*[–-]\s*(\d+)$")
_MAX_RANGE_FLOORS = 80


@dataclass(frozen=True)
class TextLine:
    page: int
    text: str
    cx: float
    cy: float


@dataclass(frozen=True)
class Title:
    """Заголовок плана: этажи (пусто — промежуточный уровень), отметки, корпус и секция."""

    page: int
    text: str
    floors: tuple[int, ...]
    marks: tuple[int, ...]
    corps: str | None
    section: str | None
    cx: float
    cy: float

    @property
    def pairs(self) -> tuple[tuple[int, int], ...]:
        """(этаж, отметка), когда число этажей и отметок совпало, иначе пусто."""
        if self.floors and len(self.floors) == len(self.marks):
            return tuple(zip(self.floors, self.marks, strict=True))
        return ()


@dataclass(frozen=True)
class Value:
    value_mm: int
    source: str  # observed | derived | operator
    evidence: str


@dataclass(frozen=True)
class Resolved:
    elevation: Value
    height: Value
    issues: tuple[tuple[str, str], ...]


def fmt_mark(mm: int) -> str:
    """4760 мм -> «+4,760» (метры, запятая, знак)."""
    return f"{mm / 1000:+.3f}".replace(".", ",")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_lines(pdf: Path, params: Params) -> list[TextLine]:
    """Строки текста всех страниц; продолжение заголовка в следующей строке блока склеивается."""
    cont = re.compile(params.text("title_continuation_regex"), re.IGNORECASE)
    max_merge = params.count("title_max_merge_lines")
    try:
        doc = pymupdf.open(str(pdf))
    except (OSError, RuntimeError, ValueError) as exc:
        raise MepError("pdf_unreadable", f"PDF не открывается: {exc}") from exc
    out: list[TextLine] = []
    try:
        for index in range(doc.page_count):
            page = doc[index]
            # «blocks» втрое быстрее «dict»; позиция строки — центр её блока
            for x0, y0, x1, y1, raw, _no, kind in page.get_text("blocks"):
                if kind != 0:
                    continue
                rows = [row for row in str(raw).split("\n") if row.strip()]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                i = 0
                while i < len(rows):
                    text = rows[i]
                    merged = 0
                    while cont.search(text) and i + 1 < len(rows) and merged < max_merge:
                        i += 1
                        merged += 1
                        text = f"{text} {rows[i]}"
                    i += 1
                    text = _clean(text)
                    if text:
                        out.append(TextLine(page.number, text, cx, cy))
    finally:
        doc.close()
    return out


def parse_floors(raw: str) -> tuple[int, ...]:
    """«14» -> (14,); «-2» -> (-2,); «3, 4, 5, 7» -> …; «5-13» -> (5…13)."""
    floors: list[int] = []
    for token in raw.split(","):
        part = token.strip()
        m = _RANGE.match(part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b and b - a < _MAX_RANGE_FLOORS:
                floors.extend(range(a, b + 1))
        elif re.fullmatch(r"-?\d+", part):
            floors.append(int(part))
    return tuple(dict.fromkeys(floors))


def parse_marks(tail: str, params: Params) -> tuple[int, ...]:
    """Отметки из хвоста заголовка после «отм.», мм, в порядке текста, без повторов."""
    mark_re = re.compile(params.text("title_mark_regex"))
    marks: list[int] = []
    for sign, whole, frac in mark_re.findall(tail.split("(")[0]):
        mm = int(whole) * 1000 + int(frac)
        marks.append(-mm if sign == "-" else mm)
    return tuple(dict.fromkeys(marks))


def parse_titles(lines: list[TextLine], params: Params) -> list[Title]:
    plan_re = re.compile(params.text("plan_title_regex"), re.IGNORECASE)
    level_re = re.compile(params.text("plan_level_title_regex"), re.IGNORECASE)
    corps_re = re.compile(params.text("title_corps_regex"), re.IGNORECASE)
    section_re = re.compile(params.text("title_section_regex"), re.IGNORECASE)
    raw: list[Title] = []
    for ln in lines:
        m = plan_re.search(ln.text)
        floors: tuple[int, ...] = ()
        if m:
            floors = parse_floors(m.group("f1") or m.group("f2"))
        else:
            m = level_re.search(ln.text)
        if m is None:
            continue
        om = re.search(r"отм\.?", ln.text[m.end() :], re.IGNORECASE)
        marks = parse_marks(ln.text[m.end() :][om.end() :], params) if om else ()
        cm, sm = corps_re.search(ln.text), section_re.search(ln.text)
        raw.append(
            Title(
                ln.page,
                ln.text,
                floors,
                marks,
                cm.group(1) if cm else None,
                re.sub(r"\s+", "", sm.group(1)) if sm else None,
                ln.cx,
                ln.cy,
            )
        )
    # заголовок без корпуса/секции наследует их, если на странице они однозначны
    keys: dict[int, set[tuple[str | None, str | None]]] = {}
    for t in raw:
        if t.corps or t.section:
            keys.setdefault(t.page, set()).add((t.corps, t.section))
    out: list[Title] = []
    for t in raw:
        found = keys.get(t.page, set())
        if not (t.corps or t.section) and len(found) == 1:
            corps, section = next(iter(found))
            t = Title(t.page, t.text, t.floors, t.marks, corps, section, t.cx, t.cy)
        out.append(t)
    return out


def _same_building(a: Title, b: Title) -> bool:
    """Корпус/секция не противоречат и хотя бы одно из них известно и совпало."""
    known = False
    for x, y in ((a.corps, b.corps), (a.section, b.section)):
        if x is not None and y is not None:
            if x != y:
                return False
            known = True
    return known or not (a.corps or a.section or b.corps or b.section)


def _nearest(titles: list[Title], at: tuple[float, float]) -> Title:
    return min(titles, key=lambda t: (t.cx - at[0]) ** 2 + (t.cy - at[1]) ** 2)


def _evidence(title: Title) -> str:
    text = title.text if len(title.text) <= EVIDENCE_LIMIT else title.text[:EVIDENCE_LIMIT] + "…"
    return f'стр. {title.page + 1}: "{text}"'


def _observed_elevation(titles: list[Title], page: int, at: tuple[float, float]) -> Value:
    on_page = [t for t in titles if t.page == page and t.floors and t.marks]
    if not on_page:
        raise MepError(
            "elevation_not_found",
            "отметка пола не найдена: на листе нет заголовка плана вида «План N этажа на отм. …»; "
            "введите отметку вручную",
        )
    single = [t for t in on_page if len(t.pairs) == 1 and len(t.floors) == 1]
    if not single:
        raise MepError(
            "elevation_not_found",
            "отметка пола не определена однозначно: заголовок плана относится к нескольким "
            f"этажам или отметкам ({_evidence(on_page[0])}); введите отметку вручную",
        )
    title = _nearest(single, at)
    mark = title.marks[0]
    if abs(mark) > ELEVATION_LIMIT_MM:
        raise MepError(
            "elevation_not_found", f"отметка в заголовке {fmt_mark(mark)} вне допустимого"
        )
    return Value(mark, "observed", _evidence(title))


def _anchor(titles: list[Title], page: int, at: tuple[float, float]) -> Title | None:
    on_page = [t for t in titles if t.page == page and t.floors]
    return _nearest(on_page, at) if on_page else None


def _derived_height(
    titles: list[Title], anchor: Title | None, elevation_mm: int | None, params: Params
) -> Value:
    lo, hi = params.count("floor_height_min_mm"), params.count("floor_height_max_mm")
    not_found = "высота этажа не определена по документации; введите высоту вручную"
    if anchor is None:
        raise MepError("floor_height_not_found", not_found)
    floor_no: int | None = None
    mark: int | None = None
    if len(anchor.pairs) == 1:
        floor_no, mark = anchor.pairs[0]
    elif elevation_mm is not None:
        for f, m in anchor.pairs:
            if m == elevation_mm:
                floor_no, mark = f, m
    if floor_no is None or mark is None:
        raise MepError("floor_height_not_found", not_found)

    per_page = Counter(t.page for t in titles)
    table: dict[int, set[tuple[int, int]]] = {}  # этаж -> {(отметка, страница)}
    levels: set[int] = set()
    for t in titles:
        if not _same_building(anchor, t):
            continue
        if t.pairs:
            for f, m in t.pairs:
                table.setdefault(f, set()).add((m, t.page))
        elif not t.floors:
            levels.update(t.marks)
    # источник этажа — страницы с наименьшим числом заголовков (лист плана, а не ведомость
    # листов); две разные отметки на таких страницах — этаж считается неопределённым
    known: dict[int, tuple[int, int]] = {}
    for f, entries in table.items():
        fewest = min(per_page[page] for _, page in entries)
        best = sorted((page, m) for m, page in entries if per_page[page] == fewest)
        if len({m for _, m in best}) == 1:
            known[f] = (best[0][1], best[0][0])
    own_page = anchor.page

    def step(n: int, direction: int) -> int:
        nxt = n + direction
        return nxt + direction if nxt == 0 else nxt  # этажа 0 нет: …, -1, 1, 2, …

    up = known.get(step(floor_no, 1))
    if up is not None:
        height = up[0] - mark
        between = any(mark < lv < up[0] for lv in levels)
        if lo <= height <= hi and not between:
            return Value(
                height,
                "derived",
                f"стр. {own_page + 1} {fmt_mark(mark)} → стр. {up[1] + 1} {fmt_mark(up[0])}",
            )
    down = known.get(step(floor_no, -1))
    if down is not None:
        height = mark - down[0]
        between = any(down[0] < lv < mark for lv in levels)
        if lo <= height <= hi and not between:
            return Value(
                height,
                "derived",
                f"стр. {down[1] + 1} {fmt_mark(down[0])} → стр. {own_page + 1} {fmt_mark(mark)}",
            )
    raise MepError("floor_height_not_found", not_found)


def resolve(
    pdf: Path,
    page_index: int,
    at: tuple[float, float],
    params: Params,
    given_elevation_mm: int | None,
    given_height_mm: int | None,
) -> Resolved:
    """Отметка и высота: ввод человека — основа, документация — источник и сверка.

    `at` — центр зоны вида в пунктах листа: из нескольких заголовков берётся ближайший.
    """
    titles = parse_titles(read_lines(pdf, params), params)
    issues: list[tuple[str, str]] = []

    doc_elevation: Value | None
    if given_elevation_mm is None:
        doc_elevation = elevation = _observed_elevation(titles, page_index, at)
    else:
        try:
            doc_elevation = _observed_elevation(titles, page_index, at)
        except MepError:
            doc_elevation = None
        elevation = Value(given_elevation_mm, "operator", "введено вручную")
        if doc_elevation is not None and doc_elevation.value_mm != given_elevation_mm:
            issues.append(
                (
                    "elevation_mismatch",
                    f"введённая отметка пола {fmt_mark(given_elevation_mm)} м не совпадает с "
                    f"отметкой по документации {fmt_mark(doc_elevation.value_mm)} м "
                    f"({doc_elevation.evidence})",
                )
            )

    anchor = _anchor(titles, page_index, at)
    doc_height: Value | None
    if given_height_mm is None:
        doc_height = height = _derived_height(titles, anchor, elevation.value_mm, params)
    else:
        try:
            doc_height = _derived_height(titles, anchor, elevation.value_mm, params)
        except MepError:
            doc_height = None
        height = Value(given_height_mm, "operator", "введено вручную")
        if doc_height is not None and doc_height.value_mm != given_height_mm:
            issues.append(
                (
                    "floor_height_mismatch",
                    f"введённая высота этажа {given_height_mm} мм не совпадает с высотой по "
                    f"документации {doc_height.value_mm} мм ({doc_height.evidence})",
                )
            )
    return Resolved(elevation, height, tuple(issues))
