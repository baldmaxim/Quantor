"""Трассировка по сетке: кратчайшие пути Дейкстры (heapq) со стоимостью «к оси / прочь от стен»."""

from __future__ import annotations

import contextlib
import heapq
import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
from numpy.typing import NDArray
from shapely.errors import GEOSException
from shapely.geometry import LineString

from cad_mep.dxfin import Door
from cad_mep.params import Params
from cad_mep.raster import (
    BoolArr,
    FloatArr,
    dist_to_background,
    lookup_mask,
    nearest_true,
    raster_polys,
)
from cad_mep.rooms import Model

IdxArr = NDArray[np.int64]
# направления (dy, dx): E, N, W, S
DIRS = ((0, 1), (1, 0), (0, -1), (-1, 0))


@dataclass
class RouteGrid:
    step: float
    pas: BoolArr
    d: FloatArr  # расстояние до непроходимого, мм (не больше предела расчёта)
    idx: IdxArr  # номер узла или -1
    xy: FloatArr  # (N, 2) центры узлов, мм
    comp_of: NDArray[np.int32]  # номер помещения в клетке (0 — проём/нет)
    mop: BoolArr  # клетка МОП
    nbr: list[list[int]]  # nbr[k][узел] — сосед в направлении k или -1
    weight: list[float]  # вес узла
    turn: float

    def node(
        self,
        x: float,
        y: float,
        r_mm: float = 600.0,
        only_mop: bool = False,
        comp: int | None = None,
    ) -> int | None:
        """Ближайший узел в радиусе; only_mop — только в МОП, comp — только в этом помещении."""
        iy, ix = int(y // self.step), int(x // self.step)
        r = int(r_mm // self.step)
        y0, y1 = max(iy - r, 0), min(iy + r + 1, self.pas.shape[0])
        x0, x1 = max(ix - r, 0), min(ix + r + 1, self.pas.shape[1])
        sub = self.idx[y0:y1, x0:x1]
        ok = sub >= 0
        if only_mop:
            ok &= self.mop[y0:y1, x0:x1]
        if comp is not None:
            ok &= self.comp_of[y0:y1, x0:x1] == comp
        ys, xs = np.nonzero(ok)
        if len(ys) == 0:
            return None
        dd = (ys + y0 - iy) ** 2 + (xs + x0 - ix) ** 2
        k = int(np.argmin(dd))
        return int(sub[ys[k], xs[k]])


def build_grid(m: Model, doors: list[Door], params: Params) -> RouteGrid:
    step = params.num("grid_route_mm")
    fine = m.gr.step
    ratio = round(step / fine)
    allowed = [c.id for c in m.comps.values() if c.kind == "mop" or c.apt]
    pas_f = lookup_mask(m.lab, allowed)
    zone = raster_polys(m.gr, [d.barrier(0.0, params.num("door_zone_half_t_mm")) for d in doors])
    pas_f |= zone & m.foot
    m.virtual_openings = _virtual_openings(m, params, pas_f)
    ny, nx = (pas_f.shape[0] // ratio) * ratio, (pas_f.shape[1] // ratio) * ratio
    p = pas_f[:ny, :nx]
    pas = np.ones((ny // ratio, nx // ratio), dtype=np.bool_)
    for oy in range(ratio):
        for ox in range(ratio):
            pas &= p[oy::ratio, ox::ratio]
    lab = m.lab[:ny, :nx][0::ratio, 0::ratio]
    comp_of = np.where(pas, lab, 0).astype(np.int32)
    mop = lookup_mask(comp_of, [c.id for c in m.comps.values() if c.kind == "mop"])
    pull = params.num("axis_pull_mm")
    clear = params.num("wall_clear_mm")
    rmax = math.ceil(max(pull, clear) / step) + 1
    d = dist_to_background(pas, rmax) * step
    idx = -np.ones(pas.shape, dtype=np.int64)
    ys, xs = np.nonzero(pas)
    idx[ys, xs] = np.arange(len(ys))
    xy = np.c_[(xs + 0.5) * step, (ys + 0.5) * step]
    # вес клетки: штраф за близость к стене (< wall_clear) и притяжение к оси (сильнее в МОП)
    w = (
        1.0
        + params.num("wall_penalty") * np.clip((clear - d) / clear, 0, 1)
        + np.where(mop, params.num("axis_weight_mop"), params.num("axis_weight_other"))
        * np.clip((pull - d) / pull, 0, 1)
    )
    padded = -np.ones((pas.shape[0] + 2, pas.shape[1] + 2), dtype=np.int64)
    padded[1:-1, 1:-1] = idx
    nbr = [padded[ys + 1 + dy, xs + 1 + dx].tolist() for dy, dx in DIRS]
    return RouteGrid(
        step, pas, d, idx, xy, comp_of, mop, nbr, w[ys, xs].tolist(), params.num("turn_penalty_mm")
    )


def _virtual_openings(m: Model, params: Params, pas: BoolArr) -> list[dict[str, object]]:
    """Помещения квартиры без двери к остальным (проём без створа): проход по кратчайшему зазору."""
    out: list[dict[str, object]] = []
    gap_max = params.num("virtual_max_gap_mm")
    half = params.num("virtual_strip_half_mm")
    step = m.gr.step
    r = math.ceil(gap_max / step)
    for ap in m.apts.values():
        for grp in ap.detached:
            a_mask = lookup_mask(m.lab, grp)
            b_mask = lookup_mask(m.lab, [c for c in ap.comps if c not in grp])
            both = np.nonzero(a_mask | b_mask)
            y0, y1 = max(int(both[0].min()) - r - 1, 0), int(both[0].max()) + r + 2
            x0, x1 = max(int(both[1].min()) - r - 1, 0), int(both[1].max()) + r + 2
            near = nearest_true(b_mask[y0:y1, x0:x1], r)
            dd = np.where(a_mask[y0:y1, x0:x1], near.dist, 1e9)
            k = np.unravel_index(int(np.argmin(dd)), dd.shape)
            p0 = m.gr.xy(int(k[0]) + y0, int(k[1]) + x0)
            p1 = m.gr.xy(int(near.iy[k]) + y0, int(near.ix[k]) + x0)
            gap = float(dd[k]) * step
            if gap <= gap_max:
                strip = raster_polys(m.gr, [LineString([p0, p1]).buffer(half, cap_style="flat")])
                pas |= strip & m.foot
                out.append(
                    {
                        "apt": ap.idx,
                        "from": [round(v) for v in p0],
                        "to": [round(v) for v in p1],
                        "gap_mm": round(gap),
                    }
                )
    return out


class Tree:
    """Дерево кратчайших путей из одной или нескольких клеток (расстояния и предшественники)."""

    def __init__(self, dist4: list[float], pred: list[int], sources: list[int]) -> None:
        self.dist4 = dist4
        self.pred = pred
        self.sources = sources

    def __getitem__(self, i: int) -> float:
        return min(self.dist4[4 * i : 4 * i + 4])


def spt(
    rg: RouteGrid,
    sources: Sequence[int],
    targets: Collection[int] | None = None,
    first: bool = False,
) -> Tree:
    """Дейкстра по состояниям (клетка, направление): ход вперёд и поворот на 90° со штрафом.

    Несколько источников — одно «лесное» дерево: путь к цели идёт от ближайшего источника.
    Обход прекращается, когда достигнуты все targets (значения в остальных клетках не итоговые);
    first — уже на первой достигнутой цели, то есть на ближайшей к источникам.
    """
    n = len(rg.weight)
    inf = math.inf
    dist = [inf] * (4 * n)
    pred = [-1] * (4 * n)
    heap: list[tuple[float, int]] = []
    for src in sources:
        for k in range(4):
            dist[src * 4 + k] = 0.0
            heap.append((0.0, src * 4 + k))
    heapq.heapify(heap)
    remaining = set(targets) if targets else None
    nbr, wgt, turn = rg.nbr, rg.weight, rg.turn
    pop, push = heapq.heappop, heapq.heappush
    half = rg.step * 0.5
    while heap:
        d, s = pop(heap)
        if d > dist[s]:
            continue
        c, k = s >> 2, s & 3
        if remaining is not None and c in remaining:
            remaining.discard(c)
            if first or not remaining:
                break
        nb = nbr[k][c]
        if nb >= 0:
            nd = d + half * (wgt[c] + wgt[nb])
            t = nb * 4 + k
            if nd < dist[t]:
                dist[t] = nd
                pred[t] = s
                push(heap, (nd, t))
        nd = d + turn
        t = c * 4 + ((k + 1) & 3)
        if nd < dist[t]:
            dist[t] = nd
            pred[t] = s
            push(heap, (nd, t))
        t = c * 4 + ((k + 3) & 3)
        if nd < dist[t]:
            dist[t] = nd
            pred[t] = s
            push(heap, (nd, t))
    return Tree(dist, pred, list(sources))


def node_path(tree: Tree, target: int) -> list[int]:
    """Путь от ближайшего источника до target (узлы сетки); пусто, если цель недостижима."""
    if not math.isfinite(tree[target]):
        return []
    four = tree.dist4[4 * target : 4 * target + 4]
    s = int(np.argmin(four)) + 4 * target
    out: list[int] = []
    while s >= 0:
        cell = s // 4
        if not out or out[-1] != cell:
            out.append(cell)
        s = tree.pred[s]
    return out[::-1]


def tree_chains(
    rg: RouteGrid, paths: Sequence[list[int]], tol_mm: float
) -> list[list[tuple[float, float]]]:
    """Объединить пути (без дублей общих участков), разбить на цепочки между ветвлениями."""
    adj: dict[int, set[int]] = {}
    keep: set[int] = set()
    for p in paths:
        if not p:
            continue
        keep.add(p[0])
        keep.add(p[-1])
        for a, b in pairwise(p):
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    special = sorted({n for n, s in adj.items() if len(s) != 2} | keep)
    special_set = set(special)
    seen: set[tuple[int, int]] = set()
    chains: list[list[tuple[float, float]]] = []
    for s in special:
        for nb in sorted(adj.get(s, ())):
            if (s, nb) in seen:
                continue
            chain = [s, nb]
            seen.add((s, nb))
            while chain[-1] not in special_set:
                nxt = sorted(q for q in adj[chain[-1]] if q != chain[-2])
                if not nxt:
                    break
                chain.append(nxt[0])
            seen.add((chain[-1], chain[-2]))
            pts = [(float(rg.xy[n][0]), float(rg.xy[n][1])) for n in chain]
            line = LineString(pts)
            if tol_mm and len(pts) > 2:
                with contextlib.suppress(GEOSException):
                    simple = line.simplify(tol_mm, preserve_topology=False)
                    if isinstance(simple, LineString):
                        line = simple
            chains.append([(float(x), float(y)) for x, y in line.coords])
    return chains
