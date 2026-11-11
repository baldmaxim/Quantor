"""Координационные оси здания по маркам-кружкам листа: текстовый слой и векторные пути PDF.

На плане оси подписаны кружками с маркой («3.1», «3.А», «12», «Б/2»). Линии осей не примыкают к
кружкам, поэтому положение оси берётся из центров кружков, а не из линий. Кружок принимается, если
это замкнутый почти круговой путь (ломаная из ≥10 отрезков или ≥4 кривых Безье) диаметром в
заданных пределах и в нём ровно одна марка допустимого вида. Кружки одного диаметра, выстроенные в
ряд (одинаковый y), задают вертикальные оси (положение — x центра); в колонку (одинаковый x) —
горизонтальные (положение — y центра). Диаметр, дающий больше всего выстроенных кружков, — марки
осей; прочие кружки с текстом (выноски, узлы) считаются в `rejected`.

Координаты — в точках PDF, начало в левом верхнем углу ОТОБРАЖАЕМОЙ страницы (как у `heights.py` и
у привязки кадра чертежа). PyMuPDF отдаёт пути и слова в системе неповёрнутой страницы, поэтому
центры кружков переводятся матрицей `page.rotation_matrix`; сопоставление марок и кружков идёт до
перевода, в одной системе. Скрипт ничего не измеряет: оси — только привязка этажей друг к другу.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pymupdf

from cad_walls.errors import WallsError
from cad_walls.params import Params

LABEL = re.compile(r"(?:\d{1,2}[.\-])?(?:\d{1,3}|[А-ЯЁA-Z]{1,2})(?:/\d{1,2})?")
LINE_OPS = frozenset({"l", "c"})


@dataclass(frozen=True)
class Bubble:
    """Кружок с маркой: центр и диаметр в системе страницы до поворота."""

    label: str
    cx: float
    cy: float
    d: float


def is_axis_label(text: str) -> bool:
    """Марка оси: необязательный номер секции («3.»), затем номер или буква(ы), доля через «/»."""
    return LABEL.fullmatch(text) is not None


def _missing(message: str) -> dict[str, object]:
    return {
        "status": "missing",
        "message": message,
        "diameter_pt": None,
        "items": [],
        "conflicts": [],
        "rejected": 0,
    }


def _r2(v: float) -> float:
    return round(v, 2)


def _circle_center(drawing: dict[str, object], p: Params) -> tuple[float, float, float] | None:
    """Центр и диаметр, если путь — замкнутый круг подходящего размера; иначе None."""
    rect = cast(pymupdf.Rect, drawing["rect"])
    w, h = rect.width, rect.height
    d = (w + h) / 2
    if not p.num("axis_bubble_min_d_pt") <= d <= p.num("axis_bubble_max_d_pt"):
        return None
    if abs(w - h) > p.num("axis_square_tol") * max(w, h):
        return None
    items = cast(Sequence[Sequence[object]], drawing["items"])
    if not items or any(it[0] not in LINE_OPS for it in items):
        return None
    n_line = sum(1 for it in items if it[0] == "l")
    n_curve = len(items) - n_line
    if n_line < p.count("axis_min_segments") and n_curve < p.count("axis_min_beziers"):
        return None
    points: list[pymupdf.Point] = []
    for it in items:
        points.append(cast(pymupdf.Point, it[1]))
        points.append(cast(pymupdf.Point, it[-1]))
    closed = bool(drawing.get("closePath")) or (
        math.dist((points[0].x, points[0].y), (points[-1].x, points[-1].y)) <= 0.05 * d
    )
    if not closed:
        return None
    cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
    radius = d / 2
    tol = p.num("axis_circle_dev") * radius
    if any(abs(math.dist((pt.x, pt.y), (cx, cy)) - radius) > tol for pt in points):
        return None
    return cx, cy, d


def _label_at(words: Sequence[Sequence[object]], cx: float, cy: float, reach: float) -> str | None:
    """Марка кружка: слова с центром не дальше `reach` от центра кружка, склеенные без пробелов."""
    inside: list[tuple[float, float, str]] = []
    for word in words:
        x0, y0, x1, y1 = (float(cast(float, v)) for v in word[:4])
        if math.dist(((x0 + x1) / 2, (y0 + y1) / 2), (cx, cy)) <= reach:
            inside.append((round(y0, 0), x0, str(word[4])))
    if not inside:
        return None
    text = "".join(t for _, _, t in sorted(inside))
    return text if is_axis_label(text) else None


def _chains(values: Sequence[float], tol: float) -> list[list[int]]:
    """Индексы значений, сгруппированные цепочками: соседи в отсортированном ряду ближе `tol`."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and values[i] - values[groups[-1][-1]] <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def _by_diameter(bubbles: Sequence[Bubble], rel_tol: float) -> list[list[Bubble]]:
    """Группы кружков одного диаметра: от наименьшего, отклонение от первого в группе ≤ rel_tol."""
    out: list[list[Bubble]] = []
    for b in sorted(bubbles, key=lambda x: x.d):
        if out and b.d - out[-1][0].d <= rel_tol * out[-1][0].d:
            out[-1].append(b)
        else:
            out.append([b])
    return out


@dataclass(frozen=True)
class Aligned:
    """Кружок, выстроенный в ряд (vertical, положение — x) или в колонку (horizontal — y)."""

    bubble: Bubble
    orient: str
    pos: float


def _align(group: Sequence[Bubble], p: Params) -> list[Aligned]:
    """Ряды и колонки группы; кружок — к большему из своих ряда и колонки (равны — к ряду)."""
    d = sum(b.d for b in group) / len(group)
    tol = p.num("axis_align_tol_ratio") * d
    need = p.count("axis_min_in_line")
    rows: dict[int, int] = {}
    cols: dict[int, int] = {}
    for chain in _chains([b.cy for b in group], tol):
        for i in chain:
            rows[i] = len(chain)
    for chain in _chains([b.cx for b in group], tol):
        for i in chain:
            cols[i] = len(chain)
    out: list[Aligned] = []
    for i, b in enumerate(group):
        n_row, n_col = rows[i], cols[i]
        if max(n_row, n_col) < need:
            continue
        if n_row >= n_col:
            out.append(Aligned(b, "vertical", b.cx))
        else:
            out.append(Aligned(b, "horizontal", b.cy))
    return out


def _merge(aligned: Sequence[Aligned], tol: float) -> tuple[list[dict[str, object]], list[str]]:
    """Одна запись на (марка, ориентация); дубли дальше `tol` — конфликт, марка выпадает."""
    keyed: dict[tuple[str, str], list[Aligned]] = {}
    for a in aligned:
        keyed.setdefault((a.bubble.label, a.orient), []).append(a)
    items: list[dict[str, object]] = []
    conflicts: set[str] = set()
    for (label, orient), found in keyed.items():
        positions = [a.pos for a in found]
        if max(positions) - min(positions) > tol:
            conflicts.add(label)
            continue
        centers = sorted({(_r2(a.bubble.cx), _r2(a.bubble.cy)) for a in found})
        items.append(
            {
                "label": label,
                "orient": orient,
                "pos_pt": _r2(sum(positions) / len(positions)),
                "bubbles_pt": [[x, y] for x, y in centers],
            }
        )
    items.sort(key=lambda it: (it["orient"] != "vertical", cast(float, it["pos_pt"])))
    return items, sorted(conflicts)


def _to_display(page: pymupdf.Page, bubbles: Sequence[Bubble]) -> list[Bubble]:
    """Центры кружков — в системе отображаемой страницы (с учётом /Rotate)."""
    if not page.rotation:
        return list(bubbles)
    out: list[Bubble] = []
    for b in bubbles:
        pt = pymupdf.Point(b.cx, b.cy) * page.rotation_matrix
        out.append(Bubble(b.label, pt.x, pt.y, b.d))
    return out


def _find_bubbles(page: pymupdf.Page, p: Params) -> list[Bubble]:
    words = cast(Sequence[Sequence[object]], page.get_text("words"))
    found: list[Bubble] = []
    for drawing in page.get_drawings():
        circle = _circle_center(drawing, p)
        if circle is None:
            continue
        cx, cy, d = circle
        label = _label_at(words, cx, cy, p.num("axis_label_reach_ratio") * d / 2)
        if label is not None:
            found.append(Bubble(label, cx, cy, d))
    return found


def read_axes_page(page: pymupdf.Page, p: Params) -> dict[str, object]:
    """Блок `axes` по открытой странице (см. `read_axes`)."""
    bubbles = _to_display(page, _find_bubbles(page, p))
    if not bubbles:
        return _missing("На листе не найдены марки осей (кружки с номером или буквой)")
    best: list[Aligned] = []
    best_d = 0.0
    for group in _by_diameter(bubbles, p.num("axis_diameter_tol")):
        aligned = _align(group, p)
        if len(aligned) > len(best):
            best, best_d = aligned, sum(b.d for b in group) / len(group)
    if not best:
        return _missing("Кружки с марками есть, но не выстроены в ряды или колонки: оси не найдены")
    rejected = len(bubbles) - len(best)
    items, conflicts = _merge(best, p.num("axis_align_tol_ratio") * best_d)
    n_v = sum(1 for it in items if it["orient"] == "vertical")
    n_h = len(items) - n_v
    message: str | None = None
    status = "found"
    if n_v == 0 or n_h == 0:
        status = "partial" if items else "missing"
        side = "горизонтальные" if n_v else "вертикальные"
        message = (
            f"Найдены только оси одного направления: не найдены {side}"
            if items
            else "Все найденные оси конфликтуют по положению"
        )
    if conflicts:
        tail = f"Марки с конфликтом положения исключены: {', '.join(conflicts)}"
        message = f"{message}. {tail}" if message else tail
    return {
        "status": status,
        "message": message,
        "diameter_pt": _r2(best_d) if items else None,
        "items": items,
        "conflicts": conflicts,
        "rejected": rejected,
    }


def read_axes(pdf: Path | None, page: int | None, p: Params) -> dict[str, object]:
    """Блок `axes`; без PDF — статус `missing` с текстом, нечитаемый PDF — ошибка входа."""
    if pdf is None or page is None:
        return _missing("PDF плана не передан: оси не определены")
    try:
        doc = pymupdf.open(str(pdf))
    except (OSError, RuntimeError, ValueError) as exc:
        raise WallsError("pdf_unreadable", f"PDF не открывается: {exc}") from exc
    try:
        if not 0 <= page < doc.page_count:
            raise WallsError("bad_page", f"в PDF нет страницы с индексом {page}")
        return read_axes_page(doc[page], p)
    finally:
        doc.close()
