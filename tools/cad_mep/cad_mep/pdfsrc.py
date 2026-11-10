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
