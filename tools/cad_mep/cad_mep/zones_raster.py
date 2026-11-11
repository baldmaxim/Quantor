"""Тонкий растр зон помещений: препятствия, метки областей, барьеры линий границ.

Массивы индексируются [iy, ix]; клетка (iy, ix) покрывает x in [ix*f, (ix+1)*f) в локальных мм.
Метки в поле g: -1 — препятствие или рамка, 0 — свободно, > 0 — область (помещение или его часть).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from shapely import make_valid
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from cad_mep import zones_const as zc
from cad_mep.pdfsrc import PtList
from cad_mep.raster import BoolArr, FloatArr, Grid, IntArr, raster_polys
from cad_mep.zones_lines import Line, Segs

Window = tuple[int, int, int, int]  # wx0, wy0, wx1, wy1 в клетках тонкого растра


@dataclass
class Field:
    f: float  # шаг тонкого растра, мм
    k: int  # клеток тонкого растра на клетку детектора помещений
    nx: int
    ny: int
    obst: BoolArr  # препятствия: заливки и тёмные штрихи
    fill: BoolArr  # только заливки (стены, колонны, остекление)
    g: IntArr  # (ny + 2, nx + 2) метки областей, рамка -1

    @property
    def gi(self) -> IntArr:
        """Поле меток без рамки (представление, не копия)."""
        view: IntArr = self.g[1:-1, 1:-1]
        return view


def draw_segments(
    mask: BoolArr, f: float, x1: FloatArr, y1: FloatArr, x2: FloatArr, y2: FloatArr
) -> None:
    """Тонкие линии толщиной в клетку: клетки, через которые проходит отрезок (шаг выборки f/2)."""
    if len(x1) == 0:
        return
    ny, nx = mask.shape
    length = np.hypot(x2 - x1, y2 - y1)
    n = np.maximum(2, np.ceil(length / (f / 2)).astype(np.int64)) + 1
    seg = np.repeat(np.arange(len(x1)), n)
    start = np.repeat(np.cumsum(n) - n, n)
    t = (np.arange(int(n.sum())) - start) / np.repeat(n - 1, n)
    px = x1[seg] + (x2 - x1)[seg] * t
    py = y1[seg] + (y2 - y1)[seg] * t
    ix = (px // f).astype(np.int64)
    iy = (py // f).astype(np.int64)
    ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
    mask[iy[ok], ix[ok]] = True


def build_obstacles(
    f: float,
    nx: int,
    ny: int,
    wall_polys: list[Polygon],
    fills: list[PtList],
    seg: Segs,
    ink_skip: BoolArr,
) -> tuple[BoolArr, BoolArr]:
    """(препятствия, заливки): стены детектора и заливки PDF + тёмные сплошные штрихи плана.

    ink_skip — штрихи, не считающиеся препятствиями (дуги дверей, оси, буквы подписей).
    """
    grid = Grid(f, nx, ny)
    polys: list[BaseGeometry] = [p for p in wall_polys if not p.is_empty]
    outline: BoolArr = np.zeros((ny, nx), dtype=np.bool_)
    for pts in fills:
        poly = Polygon(pts)
        # самопересечения и вырожденные заливки: чётно-нечётная заливка плюс контур тонкой линией
        polys.append(poly if poly.is_valid else make_valid(poly))
        xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
        draw_segments(outline, f, xs, ys, np.roll(xs, -1), np.roll(ys, -1))
    fill = raster_polys(grid, polys) | outline
    ink: BoolArr = np.zeros((ny, nx), dtype=np.bool_)
    sel = seg.dark & seg.solid & (seg.width >= zc.INK_WIDTH_MIN_PT) & ~ink_skip
    draw_segments(ink, f, seg.x1[sel], seg.y1[sel], seg.x2[sel], seg.y2[sel])
    return fill | ink, fill


def start_field(f: float, k: int, lab: IntArr, obst: BoolArr, fill: BoolArr) -> Field:
    """Стартовая разметка: клетки детектора помещений на тонком растре, вне препятствий."""
    ny, nx = obst.shape
    g: IntArr = np.full((ny + 2, nx + 2), -1, dtype=np.int32)
    inner = g[1:-1, 1:-1]
    inner[:] = np.where(obst, -1, 0)
    seeds = np.repeat(np.repeat(lab, k, axis=0), k, axis=1)
    inner[seeds > 0] = seeds[seeds > 0]
    return Field(f, k, nx, ny, obst, fill, g)


def extend_end(line: Line, fld: Field) -> Line:
    """Концы линии границы продлеваются до ближайшего препятствия, иначе чуть-чуть."""
    dx, dy = line[2] - line[0], line[3] - line[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    f = fld.f
    res: list[float] = []
    for px, py, sgn in ((line[0], line[1], -1), (line[2], line[3], 1)):
        got: float | None = None
        d = 10.0
        while d <= zc.EXTEND_MAX_MM:
            ix, iy = int((px + sgn * ux * d) // f), int((py + sgn * uy * d) // f)
            if 0 <= iy < fld.ny and 0 <= ix < fld.nx and fld.obst[iy, ix]:
                got = d + f
                break
            d += f
        res.append(got if got is not None else zc.EXTEND_DEFAULT_MM)
    return (
        line[0] - ux * res[0],
        line[1] - uy * res[0],
        line[2] + ux * res[1],
        line[3] + uy * res[1],
    )


def barrier_mask(lines: list[Line], win: Window, fld: Field) -> BoolArr:
    """Полосы шириной 2 x BARRIER_HALF_MM вдоль линий границ (концы продлены) в окне win."""
    wx0, wy0, wx1, wy1 = win
    f = fld.f
    out: BoolArr = np.zeros((wy1 - wy0, wx1 - wx0), dtype=np.bool_)
    half = max(1, round(2 * zc.BARRIER_HALF_MM / f)) * f / 2
    for ln in lines:
        ax, ay, bx, by = extend_end(ln, fld)
        length = math.hypot(bx - ax, by - ay)
        if length <= 0:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length
        ix0 = max(int((min(ax, bx) - half) // f) - wx0, 0)
        ix1 = min(int((max(ax, bx) + half) // f) + 1 - wx0, out.shape[1])
        iy0 = max(int((min(ay, by) - half) // f) - wy0, 0)
        iy1 = min(int((max(ay, by) + half) // f) + 1 - wy0, out.shape[0])
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        cx = (np.arange(ix0, ix1) + wx0 + 0.5) * f - ax
        cy = ((np.arange(iy0, iy1) + wy0 + 0.5) * f - ay)[:, None]
        along = cx[None, :] * ux + cy * uy
        across = np.abs(-cx[None, :] * uy + cy * ux)
        out[iy0:iy1, ix0:ix1] |= (along >= 0) & (along <= length) & (across <= half)
    return out


def part_areas(lab: NDArray[np.int32], n: int, f: float) -> FloatArr:
    """Площадь (м²) каждой метки 0..n."""
    return np.bincount(lab.ravel(), minlength=n + 1).astype(np.float64) * (f * f / 1e6)
