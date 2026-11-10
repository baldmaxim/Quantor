"""Растры, метки связности и расстояния — на numpy, без scipy.

Массивы индексируются [iy, ix]; клетка (iy, ix) покрывает x in [ix*step, (ix+1)*step), y аналогично.
Координаты — локальные (сдвинуты так, чтобы рамка плана лежала в первой четверти).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

BoolArr = NDArray[np.bool_]
IntArr = NDArray[np.int32]
FloatArr = NDArray[np.float64]


@dataclass(frozen=True)
class Grid:
    step: float
    nx: int
    ny: int

    def ij(self, x: float, y: float) -> tuple[int, int]:
        return int(y // self.step), int(x // self.step)

    def xy(self, iy: int, ix: int) -> tuple[float, float]:
        return ((ix + 0.5) * self.step, (iy + 0.5) * self.step)

    def inside(self, iy: int, ix: int) -> bool:
        return 0 <= iy < self.ny and 0 <= ix < self.nx


def make_grid(step: float, w: float, h: float) -> Grid:
    return Grid(step, int(w // step) + 1, int(h // step) + 1)


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [] if geom.is_empty else [geom]
    if isinstance(geom, MultiPolygon) or hasattr(geom, "geoms"):
        out: list[Polygon] = []
        for part in getattr(geom, "geoms", []):
            out.extend(_polygons(part))
        return out
    return []


def _mark_ring(g: Grid, coords: FloatArr, mask: BoolArr) -> None:
    """Отметить клетки вдоль контура (как контур заливки в растровых библиотеках)."""
    if len(coords) < 2:
        return
    a, b = coords[:-1], coords[1:]
    length = np.hypot(*(b - a).T)
    n = np.maximum(2, np.ceil(length / (g.step / 2)).astype(np.int64)) + 1
    seg = np.repeat(np.arange(len(a)), n)
    start = np.repeat(np.cumsum(n) - n, n)
    t = (np.arange(int(n.sum())) - start) / np.repeat(n - 1, n)
    pts = a[seg] + (b - a)[seg] * t[:, None]
    ix = np.clip((pts[:, 0] // g.step).astype(np.int64), 0, g.nx - 1)
    iy = np.clip((pts[:, 1] // g.step).astype(np.int64), 0, g.ny - 1)
    mask[iy, ix] = True


def raster_polys(g: Grid, geoms: Iterable[BaseGeometry]) -> BoolArr:
    """Заливка многоугольников (с дырками): клетки, чей центр внутри, плюс клетки вдоль контура."""
    mask: BoolArr = np.zeros((g.ny, g.nx), dtype=np.bool_)
    for geom in geoms:
        for poly in _polygons(geom):
            x0, y0, x1, y1 = poly.bounds
            ix0, ix1 = max(int(x0 // g.step), 0), min(int(x1 // g.step) + 1, g.nx)
            iy0, iy1 = max(int(y0 // g.step), 0), min(int(y1 // g.step) + 1, g.ny)
            if ix0 >= ix1 or iy0 >= iy1:
                continue
            xs = (np.arange(ix0, ix1) + 0.5) * g.step
            ys = (np.arange(iy0, iy1) + 0.5) * g.step
            gx, gy = np.meshgrid(xs, ys)
            shapely.prepare(poly)
            inside = shapely.contains_xy(poly, gx.ravel(), gy.ravel()).reshape(gx.shape)
            mask[iy0:iy1, ix0:ix1] |= inside
            _mark_ring(g, np.asarray(poly.exterior.coords, dtype=np.float64), mask)
            for ring in poly.interiors:
                _mark_ring(g, np.asarray(ring.coords, dtype=np.float64), mask)
    return mask


def dilate(mask: BoolArr, iterations: int = 1) -> BoolArr:
    """Расширение «крестом» (4-связность)."""
    out = mask.copy()
    for _ in range(iterations):
        prev = out.copy()
        out[1:, :] |= prev[:-1, :]
        out[:-1, :] |= prev[1:, :]
        out[:, 1:] |= prev[:, :-1]
        out[:, :-1] |= prev[:, 1:]
    return out


def erode(mask: BoolArr) -> BoolArr:
    """Сужение «крестом»; за краем массива — пусто."""
    out = mask.copy()
    out[1:, :] &= mask[:-1, :]
    out[0, :] = False
    out[:-1, :] &= mask[1:, :]
    out[-1, :] = False
    out[:, 1:] &= mask[:, :-1]
    out[:, 0] = False
    out[:, :-1] &= mask[:, 1:]
    out[:, -1] = False
    return out


def closing(mask: BoolArr) -> BoolArr:
    return erode(dilate(mask))


def _find(parent: list[int], a: int) -> int:
    root = a
    while parent[root] != root:
        root = parent[root]
    while parent[a] != root:
        parent[a], a = root, parent[a]
    return root


def label(mask: BoolArr, diagonal: bool = False) -> tuple[IntArr, int]:
    """Метки связных областей; нумерация — по первой клетке в построчном обходе (как у scipy)."""
    ny, nx = mask.shape
    lab: IntArr = np.zeros((ny, nx), dtype=np.int32)
    if not mask.any():
        return lab, 0
    left = np.zeros_like(mask)
    left[:, 1:] = mask[:, :-1]
    starts = mask & ~left
    run_id = np.cumsum(starts.ravel()).reshape(ny, nx).astype(np.int64) - 1
    n_runs = int(starts.sum())
    pairs: list[NDArray[np.int64]] = []

    def collect(a_sel: BoolArr, a_ids: NDArray[np.int64], b_ids: NDArray[np.int64]) -> None:
        if a_sel.any():
            pairs.append(np.stack([a_ids[a_sel], b_ids[a_sel]], axis=1))

    both = mask[:-1, :] & mask[1:, :]
    collect(both, run_id[:-1, :], run_id[1:, :])
    if diagonal:
        d1 = mask[:-1, :-1] & mask[1:, 1:]
        collect(d1, run_id[:-1, :-1], run_id[1:, 1:])
        d2 = mask[:-1, 1:] & mask[1:, :-1]
        collect(d2, run_id[:-1, 1:], run_id[1:, :-1])
    parent = list(range(n_runs))
    if pairs:
        uniq = np.unique(np.concatenate(pairs, axis=0), axis=0)
        for a, b in uniq.tolist():
            ra, rb = _find(parent, int(a)), _find(parent, int(b))
            if ra != rb:
                if ra < rb:
                    parent[rb] = ra
                else:
                    parent[ra] = rb
    roots = np.array([_find(parent, i) for i in range(n_runs)], dtype=np.int64)
    _, compact = np.unique(roots, return_inverse=True)
    # корень — минимальный номер рана, значит порядок корней = порядок первой клетки
    table = (compact + 1).astype(np.int32)
    lab[mask] = table[run_id[mask]]
    return lab, int(compact.max()) + 1


@dataclass(frozen=True)
class CompStats:
    ids: IntArr
    counts: NDArray[np.int64]
    cx: FloatArr
    cy: FloatArr
    x0: IntArr
    y0: IntArr
    x1: IntArr
    y1: IntArr


def comp_stats(lab: IntArr, n: int) -> CompStats:
    """Площадь (клетки), центроид и рамка (в клетках) каждой метки 1..n."""
    ys, xs = np.nonzero(lab)
    ids = lab[ys, xs]
    order = np.argsort(ids, kind="stable")
    ids_s, ys_s, xs_s = ids[order], ys[order].astype(np.int64), xs[order].astype(np.int64)
    counts = np.bincount(ids_s, minlength=n + 1)[1:]
    ends = np.cumsum(counts)
    starts = ends - counts
    nonempty = counts > 0
    idx = starts[nonempty]
    sum_x = np.add.reduceat(xs_s, idx)
    sum_y = np.add.reduceat(ys_s, idx)
    cx = np.zeros(n)
    cy = np.zeros(n)
    cx[nonempty] = sum_x / counts[nonempty]
    cy[nonempty] = sum_y / counts[nonempty]

    def reduce(arr: NDArray[np.int64], fn: np.ufunc) -> IntArr:
        out: IntArr = np.zeros(n, dtype=np.int32)
        out[nonempty] = fn.reduceat(arr, idx)
        return out

    return CompStats(
        np.arange(1, n + 1, dtype=np.int32),
        counts,
        cx,
        cy,
        reduce(xs_s, np.minimum),
        reduce(ys_s, np.minimum),
        reduce(xs_s, np.maximum),
        reduce(ys_s, np.maximum),
    )


@dataclass(frozen=True)
class Nearest:
    """Ближайшая целевая клетка: dist — в клетках (rmax+1, если дальше rmax), iy/ix — её индексы."""

    dist: FloatArr
    iy: NDArray[np.int32]
    ix: NDArray[np.int32]


def nearest_true(target: BoolArr, rmax: int) -> Nearest:
    """Евклидово расстояние до ближайшей клетки target, точное в пределах rmax клеток.

    Двухпроходная схема (столбцы, затем строки) со сдвигами массивов: O(rmax) операций над массивом.
    """
    ny, nx = target.shape
    big = np.int32(1 << 28)
    g = np.full((ny, nx), big, dtype=np.int32)
    gy = np.zeros((ny, nx), dtype=np.int32)
    rows = np.arange(ny, dtype=np.int32)[:, None]
    g[target] = 0
    gy[:] = np.where(target, rows, 0)
    for dy in range(1, min(rmax, ny - 1) + 1):
        sq = np.int32(dy * dy)
        # источник строкой выше (iy-dy) для клеток iy >= dy
        upd = target[:-dy, :] & (g[dy:, :] == big)
        g[dy:, :][upd] = sq
        gy[dy:, :] = np.where(upd, rows[:-dy, :], gy[dy:, :])
        # источник строкой ниже (iy+dy) для клеток iy < ny-dy
        upd = target[dy:, :] & (g[:-dy, :] == big)
        g[:-dy, :][upd] = sq
        gy[:-dy, :] = np.where(upd, rows[dy:, :], gy[:-dy, :])
    out = g.copy()
    best_dx = np.zeros((ny, nx), dtype=np.int32)
    for dx in range(1, min(rmax, nx - 1) + 1):
        add = np.int32(dx * dx)
        # источник левее (ix-dx)
        cand = g[:, :-dx] + add
        sel = cand < out[:, dx:]
        out[:, dx:] = np.where(sel, cand, out[:, dx:])
        best_dx[:, dx:] = np.where(sel, -dx, best_dx[:, dx:])
        # источник правее (ix+dx)
        cand = g[:, dx:] + add
        sel = cand < out[:, :-dx]
        out[:, :-dx] = np.where(sel, cand, out[:, :-dx])
        best_dx[:, :-dx] = np.where(sel, dx, best_dx[:, :-dx])
    far = out > rmax * rmax
    dist = np.sqrt(np.where(far, (rmax + 1) ** 2, out).astype(np.float64))
    cols = np.arange(nx, dtype=np.int32)[None, :]
    src_x = np.clip(cols + best_dx, 0, nx - 1)
    src_y = np.take_along_axis(gy, src_x.astype(np.int64), axis=1)
    return Nearest(dist, src_y.astype(np.int32), src_x.astype(np.int32))


def dist_to_background(mask: BoolArr, rmax: int) -> FloatArr:
    """Аналог EDT: для клеток mask — расстояние (в клетках) до ближайшей клетки вне mask."""
    return np.where(mask, nearest_true(~mask, rmax).dist, 0.0)


def lookup_mask(lab: IntArr, ids: Sequence[int]) -> BoolArr:
    """Клетки, чья метка входит в ids (быстрее np.isin на больших растрах)."""
    table = np.zeros(int(lab.max()) + 1 if lab.size else 1, dtype=np.bool_)
    for i in ids:
        if 0 <= i < len(table):
            table[i] = True
    out: BoolArr = table[lab]
    return out


def ceil_div(a: float, b: float) -> int:
    return math.ceil(a / b)
