"""Чтение одной страницы PDF через PyMuPDF: заливки стен, вершины векторов, слова."""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf
from numpy.typing import NDArray

from cad_mep.errors import MepError
from cad_mep.params import Params

PtList = list[tuple[float, float]]


@dataclass(frozen=True)
class WordPt:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class WallFill:
    pts: PtList
    bbox: tuple[float, float, float, float]


@dataclass
class PageData:
    width: float
    height: float
    wall_fills: list[WallFill] = field(default_factory=list)
    vertices: NDArray[np.float64] = field(default_factory=lambda: np.zeros((0, 2)))
    words: list[WordPt] = field(default_factory=list)


def item_points(items: list[Any]) -> PtList:
    """Вершины элементов пути (линии, прямоугольники, четырёхугольники, кривые) в порядке обхода.

    Элементы get_drawings — кортежи PyMuPDF разных видов, поэтому тип элемента здесь Any.
    """
    pts: PtList = []
    for it in items:
        kind = it[0]
        if kind == "l":
            if not pts:
                pts.append((float(it[1].x), float(it[1].y)))
            pts.append((float(it[2].x), float(it[2].y)))
        elif kind == "re":
            r = it[1]
            pts += [
                (float(r.x0), float(r.y0)),
                (float(r.x1), float(r.y0)),
                (float(r.x1), float(r.y1)),
                (float(r.x0), float(r.y1)),
            ]
        elif kind == "qu":
            q = it[1]
            pts += [(float(c.x), float(c.y)) for c in (q.ul, q.ur, q.lr, q.ll)]
        elif kind == "c":
            if not pts:
                pts.append((float(it[1].x), float(it[1].y)))
            pts.append((float(it[4].x), float(it[4].y)))
    return pts


def read_page(pdf: Path, page_index: int, params: Params) -> PageData:
    """Заливки цветов стены (белые — только небольшие), все вершины векторов и слова страницы."""
    try:
        doc = pymupdf.open(str(pdf))
    except (OSError, RuntimeError, ValueError) as exc:
        raise MepError("pdf_unreadable", f"PDF не открывается: {exc}") from exc
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise MepError(
                "page_out_of_range", f"страницы {page_index} нет (страниц: {doc.page_count})"
            )
        page = doc[page_index]
        wall_colors = {tuple(round(v, 2) for v in c) for c in params.colors("wall_fill_colors")}
        big_white = params.num("big_white_fill_pt2")
        data = PageData(float(page.rect.width), float(page.rect.height))
        verts = array("d")
        for dr in page.get_drawings():
            pts = item_points(dr["items"])
            for x, y in pts:
                verts.append(x)
                verts.append(y)
            fill = dr.get("fill")
            if dr["type"] != "f" or not fill:
                continue
            color = tuple(round(float(v), 2) for v in fill)
            if color not in wall_colors or len(pts) < 3:
                continue
            rect = dr["rect"]
            if color == (1.0, 1.0, 1.0) and rect.width * rect.height > big_white:
                continue
            data.wall_fills.append(
                WallFill(pts, (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
            )
        data.vertices = np.frombuffer(verts, dtype=np.float64).reshape(-1, 2).copy()
        seen: set[tuple[str, int, int]] = set()
        for w in page.get_text("words"):
            x0, y0, x1, y1, text = w[:5]
            key = (str(text), round(float(x0)), round(float(y0)))
            if key in seen:  # жирный шрифт рисуется дважды
                continue
            seen.add(key)
            data.words.append(WordPt(str(text), float(x0), float(y0), float(x1), float(y1)))
        return data
    finally:
        doc.close()


@dataclass
class Strokes:
    """Штрихи и заливки векторов страницы в рамке плана: пункты PDF, по одной строке на отрезок.

    Кривая Безье берётся хордой (начало -> конец), прямоугольник и четырёхугольник — четырьмя
    сторонами. Признаки цвета: black — ровно (0, 0, 0); dark — наибольший канал не выше dark_max;
    solid — линия без штриха.
    """

    seg: NDArray[np.float64]  # (n, 4): x1, y1, x2, y2
    width: NDArray[np.float64]
    black: NDArray[np.bool_]
    dark: NDArray[np.bool_]
    solid: NDArray[np.bool_]
    fills: list[tuple[PtList, tuple[float, ...]]]  # контур заливки и её цвет


def _fill_points(items: list[Any]) -> PtList:
    pts: PtList = []
    for it in items:
        if it[0] == "l":
            if not pts:
                pts.append((float(it[1].x), float(it[1].y)))
            pts.append((float(it[2].x), float(it[2].y)))
        elif it[0] == "re":
            q = it[1]
            pts += [(q.x0, q.y0), (q.x1, q.y0), (q.x1, q.y1), (q.x0, q.y1)]
        elif it[0] == "qu":
            q = it[1]
            pts += [(float(c.x), float(c.y)) for c in (q.ul, q.ur, q.lr, q.ll)]
    return pts


def _stroke_segments(items: list[Any]) -> list[tuple[float, float, float, float]]:
    out: list[tuple[float, float, float, float]] = []
    for it in items:
        if it[0] == "l":
            out.append((it[1].x, it[1].y, it[2].x, it[2].y))
        elif it[0] == "c":
            out.append((it[1].x, it[1].y, it[4].x, it[4].y))
        elif it[0] in ("re", "qu"):
            q = it[1]
            cs = (
                [(q.x0, q.y0), (q.x1, q.y0), (q.x1, q.y1), (q.x0, q.y1)]
                if it[0] == "re"
                else [(c.x, c.y) for c in (q.ul, q.ur, q.lr, q.ll)]
            )
            out += [(*cs[i], *cs[(i + 1) % 4]) for i in range(4)]
    return out


def read_strokes(
    pdf: Path, page_index: int, zone: tuple[float, float, float, float], dark_max: float
) -> Strokes:
    """Штрихи и заливки страницы, чьи рамки пересекают рамку плана zone (пт)."""
    try:
        doc = pymupdf.open(str(pdf))
    except (OSError, RuntimeError, ValueError) as exc:
        raise MepError("pdf_unreadable", f"PDF не открывается: {exc}") from exc
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise MepError(
                "page_out_of_range", f"страницы {page_index} нет (страниц: {doc.page_count})"
            )
        zx0, zy0, zx1, zy1 = zone
        rows: list[tuple[float, float, float, float, float, bool, bool, bool]] = []
        fills: list[tuple[PtList, tuple[float, ...]]] = []
        for dr in doc[page_index].get_drawings():
            r = dr["rect"]
            if r.x1 < zx0 or r.x0 > zx1 or r.y1 < zy0 or r.y0 > zy1:
                continue
            kind, fill, col = dr["type"], dr.get("fill"), dr.get("color")
            if kind in ("f", "fs") and fill:
                pts = _fill_points(dr["items"])
                if len(pts) >= 3:
                    fills.append((pts, tuple(round(float(v), 2) for v in fill)))
            if kind in ("s", "fs") and col:
                width = float(dr.get("width") or 0.0)
                c = tuple(round(float(v), 2) for v in col)
                flags = (
                    c == (0.0, 0.0, 0.0),
                    max(c) <= dark_max,
                    str(dr.get("dashes")) in ("[] 0", "None"),
                )
                rows += [(*s, width, *flags) for s in _stroke_segments(dr["items"])]
    finally:
        doc.close()
    arr = np.array(rows, dtype=np.float64).reshape(-1, 8)
    return Strokes(arr[:, :4], arr[:, 4], arr[:, 5] > 0, arr[:, 6] > 0, arr[:, 7] > 0, fills)
