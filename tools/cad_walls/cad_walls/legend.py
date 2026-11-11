"""Материал стен из условных обозначений листа: текстовый слой PDF, без OCR и растра.

Строки легенды («Внутренние не несущие стены из … блоков 100 мм») читаются из текстового слоя
страницы, материал определяется по ключевым словам, толщина — по «NNN мм». Результат — подсказка
материала для конструкций: проверяемая запись с цитатой строки и её координатами в точках PDF,
а не решение. Конструкции не меняются; сопоставление детерминировано.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, cast

import pymupdf

from cad_walls.constructions import Construction
from cad_walls.errors import WallsError

Bbox = tuple[float, float, float, float]
HintStatus = Literal["matched", "not_in_legend", "conflict", "no_legend"]

MAX_EVIDENCE_CHARS = 200
BBOX_LEN = 4
MIN_THICKNESS_MM = 40
MAX_THICKNESS_MM = 700
# Окно легенды под заголовком: доли размеров страницы (вертикаль вниз, ширина вправо от заголовка).
BLOCK_HEIGHT_RATIO = 0.5
BLOCK_WIDTH_RATIO = 0.45
BLOCK_LEFT_MARGIN_PT = 30.0
# Сдвиг границ окна: строка попадает в него, если её верх не выше низа заголовка минус допуск.
BLOCK_TOP_TOL_PT = 3.0

_HEADING = re.compile(r"условн\w*\s+обозначен")
_THICKNESS = re.compile(r"(?<!\d)(\d{2,3})\s*мм")
_WALL_WORD = re.compile(r"стен|перегород|кладк")

# Порядок важен: более специфичные ключевые слова раньше общих.
_MATERIALS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gypsum_tongue_groove", re.compile(r"гипсов\w*\s+блок|пазогреб|\bпгп\b")),
    ("expanded_clay_block", re.compile(r"керамзит")),
    ("ceramic_block", re.compile(r"керамическ\w*\s+(?:камн|блок)|поризован")),
    ("aerated_concrete", re.compile(r"газобетон|ячеист")),
    ("silicate_block", re.compile(r"силикатн")),
)
_BRICK = re.compile(r"кирпич")
_BRICK_HOLLOW = re.compile(r"пустотел|щелев")
_BRICK_SOLID = re.compile(r"полнотел")
_MONOLITH = re.compile(r"монолит|железобетон")
MONOLITH_CODE = "monolith_concrete"


@dataclass(frozen=True)
class Evidence:
    """Цитата строки легенды: текст (до 200 знаков), страница и рамка в точках PDF."""

    text: str
    page_index: int
    bbox: Bbox

    def to_json(self) -> dict[str, object]:
        return {
            "text": self.text,
            "page_index": self.page_index,
            "bbox": [round(v, 1) for v in self.bbox],
        }


@dataclass(frozen=True)
class LegendLine:
    """Строка текстового слоя (возможно, склеенная из двух) с рамкой."""

    text: str
    page_index: int
    bbox: Bbox
    block: int = -1

    def evidence(self) -> Evidence:
        return Evidence(self.text[:MAX_EVIDENCE_CHARS], self.page_index, self.bbox)


@dataclass(frozen=True)
class LegendEntry:
    code: str
    thickness_mm: int | None
    evidence: Evidence

    def to_json(self) -> dict[str, object]:
        return {
            "code": self.code,
            "thickness_mm": self.thickness_mm,
            "evidence": self.evidence.to_json(),
        }


@dataclass(frozen=True)
class Legend:
    """Материалы стен из легенды листа."""

    masonry: dict[int, LegendEntry] = field(default_factory=dict)
    monolith: LegendEntry | None = None
    conflicts: dict[int, list[LegendEntry]] = field(default_factory=dict)
    unparsed: list[LegendLine] = field(default_factory=list)
    heading_found: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.masonry and not self.conflicts and self.monolith is None

    def to_json(self) -> dict[str, object]:
        return {
            "heading_found": self.heading_found,
            "masonry": {str(t): e.to_json() for t, e in sorted(self.masonry.items())},
            "monolith": None if self.monolith is None else self.monolith.to_json(),
            "conflicts": {
                str(t): [e.to_json() for e in entries]
                for t, entries in sorted(self.conflicts.items())
            },
            "unparsed": [
                {"text": u.text[:MAX_EVIDENCE_CHARS], "bbox": [round(v, 1) for v in u.bbox]}
                for u in self.unparsed
            ],
        }


@dataclass(frozen=True)
class MaterialHint:
    """Подсказка материала конструкции из легенды."""

    value: str | None
    source: str
    status: HintStatus
    evidence: list[Evidence]

    def to_json(self) -> dict[str, object]:
        return {
            "value": self.value,
            "source": self.source,
            "status": self.status,
            "evidence": [e.to_json() for e in self.evidence],
        }


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def _classify(text: str) -> tuple[str | None, bool]:
    """Код материала и признак «кирпич без уточнения». Нет ключевого слова — (None, False)."""
    low = _norm(text)
    for code, pattern in _MATERIALS:
        if pattern.search(low):
            return code, False
    if _BRICK.search(low):
        if _BRICK_HOLLOW.search(low):
            return "brick_hollow", False
        if _BRICK_SOLID.search(low):
            return "brick_solid", False
        return None, True
    if _MONOLITH.search(low):
        return MONOLITH_CODE, False
    return None, False


def _thickness(text: str) -> int | None:
    match = _THICKNESS.search(_norm(text))
    if match is None:
        return None
    value = int(match.group(1))
    return value if MIN_THICKNESS_MM <= value <= MAX_THICKNESS_MM else None


def _has_material(text: str) -> bool:
    code, ambiguous = _classify(text)
    return code is not None or ambiguous


def _is_complete(text: str) -> bool:
    """Строка законченная: код материала с толщиной либо монолит (ему толщина не нужна).

    «Кирпич без уточнения» незаконченный: уточнение может стоять в соседней строке блока.
    """
    code, _ = _classify(text)
    if code == MONOLITH_CODE:
        return True
    return code is not None and _thickness(text) is not None


def _union(a: Bbox, b: Bbox) -> Bbox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


class _Rect(Protocol):
    width: float
    height: float


class _Page(Protocol):
    rect: _Rect

    def get_text(self, option: str, /) -> dict[str, object]: ...


class _PdfDoc(Protocol):
    page_count: int

    def __getitem__(self, index: int, /) -> _Page: ...

    def close(self) -> None: ...


# Аннотации PyMuPDF неполны: типизированная граница, дальше код работает с Protocol.
_open_pdf = cast(Callable[[str], _PdfDoc], pymupdf.open)


def _dicts(value: object) -> list[dict[str, object]]:
    """Элементы-словари списка; прочее (в том числе не список) отбрасывается."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _number(value: object, default: float = 0.0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _read_page(pdf_path: Path, page_index: int) -> tuple[list[LegendLine], float, float]:
    """Строки текстового слоя страницы в порядке чтения и размер страницы в точках."""
    try:
        doc = _open_pdf(str(pdf_path))
    except (OSError, RuntimeError, ValueError) as exc:
        raise WallsError("pdf_unreadable", f"PDF не открывается: {exc}") from exc
    try:
        if not 0 <= page_index < doc.page_count:
            raise WallsError("bad_page", f"в PDF нет страницы с индексом {page_index}")
        page = doc[page_index]
        data = page.get_text("dict")
        width, height = float(page.rect.width), float(page.rect.height)
    finally:
        doc.close()
    out: list[LegendLine] = []
    for block in _dicts(data.get("blocks")):
        if block.get("type") != 0:
            continue
        number = round(_number(block.get("number"), -1))
        for line in _dicts(block.get("lines")):
            spans = _dicts(line.get("spans"))
            text = " ".join("".join(str(span.get("text", "")) for span in spans).split())
            box = line.get("bbox")
            if not text or not isinstance(box, list | tuple) or len(box) != BBOX_LEN:
                continue
            x0, y0, x1, y1 = (_number(v) for v in box)
            out.append(LegendLine(text, page_index, (x0, y0, x1, y1), number))
    return out, width, height


def read_lines(pdf_path: Path, page_index: int) -> list[LegendLine]:
    """Строки текстового слоя страницы в порядке чтения: блок, затем строка внутри блока."""
    return _read_page(pdf_path, page_index)[0]


def _merge_broken(lines: Sequence[LegendLine]) -> list[LegendLine]:
    """Склеивает соседние строки одного блока, если лишь вместе они дают материал и толщину."""
    out: list[LegendLine] = []
    i = 0
    while i < len(lines):
        a = lines[i]
        b = lines[i + 1] if i + 1 < len(lines) else None
        if (
            b is not None
            and a.block == b.block
            and not _is_complete(a.text)
            and not _is_complete(b.text)
        ):
            joined = f"{a.text} {b.text}"
            if _is_complete(joined):
                out.append(LegendLine(joined, a.page_index, _union(a.bbox, b.bbox), a.block))
                i += 2
                continue
        out.append(a)
        i += 1
    return out


def _headings(lines: Iterable[LegendLine]) -> list[LegendLine]:
    return [ln for ln in lines if _HEADING.search(_norm(ln.text))]


def _in_block(line: LegendLine, heading: LegendLine, width: float, height: float) -> bool:
    left = heading.bbox[0] - BLOCK_LEFT_MARGIN_PT
    right = heading.bbox[0] + width * BLOCK_WIDTH_RATIO
    top = heading.bbox[3] - BLOCK_TOP_TOL_PT
    bottom = heading.bbox[3] + height * BLOCK_HEIGHT_RATIO
    return line.bbox[0] >= left and line.bbox[0] <= right and top <= line.bbox[1] <= bottom


def _reading_order(lines: Iterable[LegendLine]) -> list[LegendLine]:
    return sorted(lines, key=lambda ln: (round(ln.bbox[1], 1), round(ln.bbox[0], 1), ln.text))


def _material_lines(lines: Sequence[LegendLine]) -> list[LegendLine]:
    return [ln for ln in lines if _has_material(ln.text)]


def _collect(candidates: Sequence[LegendLine], heading_found: bool) -> Legend:
    masonry_all: dict[int, dict[str, LegendEntry]] = {}
    monolith: LegendEntry | None = None
    unparsed: list[LegendLine] = []
    for ln in _reading_order(candidates):
        code, _ = _classify(ln.text)
        thickness = _thickness(ln.text)
        if code is None:
            unparsed.append(ln)
        elif code == MONOLITH_CODE:
            if monolith is None:
                monolith = LegendEntry(code, thickness, ln.evidence())
        elif thickness is None:
            unparsed.append(ln)
        else:
            masonry_all.setdefault(thickness, {}).setdefault(
                code, LegendEntry(code, thickness, ln.evidence())
            )
    masonry: dict[int, LegendEntry] = {}
    conflicts: dict[int, list[LegendEntry]] = {}
    for thickness in sorted(masonry_all):
        entries = list(masonry_all[thickness].values())
        if len(entries) == 1:
            masonry[thickness] = entries[0]
        else:
            conflicts[thickness] = entries
    return Legend(masonry, monolith, conflicts, unparsed, heading_found)


def parse_legend(lines: Sequence[LegendLine], page_width: float, page_height: float) -> Legend:
    """Легенда по строкам страницы (чистая функция, без чтения файла)."""
    heading_lines = _headings(lines)
    if heading_lines:
        in_block = [
            ln
            for ln in lines
            if any(_in_block(ln, h, page_width, page_height) for h in heading_lines)
        ]
        block_lines = _material_lines(_merge_broken(in_block))
        if block_lines:
            return _collect(block_lines, True)
    page_lines = [
        ln for ln in _material_lines(_merge_broken(lines)) if _WALL_WORD.search(_norm(ln.text))
    ]
    return _collect(page_lines, bool(heading_lines))


def read_legend(pdf_path: Path, page_index: int) -> Legend:
    """Легенда страницы: материалы стен и монолит по текстовому слою PDF."""
    lines, width, height = _read_page(pdf_path, page_index)
    return parse_legend(lines, width, height)


def _entries_for_thickness(legend: Legend, thickness: int) -> tuple[HintStatus, list[LegendEntry]]:
    if thickness in legend.conflicts:
        return "conflict", legend.conflicts[thickness]
    if thickness in legend.masonry:
        return "matched", [legend.masonry[thickness]]
    return "not_in_legend", []


def _nearest_thickness(legend: Legend, measured: float, tol: float) -> int | None:
    known = sorted({*legend.masonry, *legend.conflicts})
    near = [t for t in known if abs(t - measured) <= tol]
    return min(near, key=lambda t: (abs(t - measured), t)) if near else None


def _masonry_hint(c: Construction, legend: Legend, tol: float) -> MaterialHint:
    if c.thickness_nominal is not None:
        thickness: int | None = round(c.thickness_nominal)
    else:
        thickness = _nearest_thickness(legend, c.thickness_measured, tol)
    if thickness is None:
        return MaterialHint(None, "legend", "not_in_legend", [])
    status, entries = _entries_for_thickness(legend, thickness)
    value = entries[0].code if status == "matched" else None
    return MaterialHint(value, "legend", status, [e.evidence for e in entries])


def material_hints(
    constructions: Sequence[Construction], legend: Legend, tolerance_mm: float
) -> dict[str, MaterialHint]:
    """Подсказки материала по id конструкции: кладка — по толщине, монолит — из легенды.

    Другие виды (каркасные перегородки) подсказки не получают. Конструкции не меняются.
    """
    out: dict[str, MaterialHint] = {}
    for c in sorted(constructions, key=lambda item: item.id):
        if c.kind == "masonry":
            hint = (
                MaterialHint(None, "legend", "no_legend", [])
                if legend.is_empty
                else _masonry_hint(c, legend, tolerance_mm)
            )
        elif c.kind.startswith("monolith"):
            if legend.monolith is not None:
                hint = MaterialHint(
                    legend.monolith.code, "legend", "matched", [legend.monolith.evidence]
                )
            else:
                status: HintStatus = "no_legend" if legend.is_empty else "not_in_legend"
                hint = MaterialHint(None, "legend", status, [])
        else:
            continue
        out[c.id] = hint
    return out


def hints_to_json(hints: dict[str, MaterialHint]) -> dict[str, object]:
    """JSON-представление подсказок в порядке id."""
    return {cid: hints[cid].to_json() for cid in sorted(hints)}
