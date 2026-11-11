"""Разбиение связного куска заливки на участки одной толщины хордовой осью (chordal axis).

Граница спрямляется с шагом `segmentize_step_mm`, полигон разбивается ограниченной триангуляцией
Делоне. Треугольник с одним внутренним ребром — концевой, с двумя — рукав, с тремя — узел.
Цепочки рукавов — участки стены; локальная ширина — длина внутренних хорд. Цепочка рвётся там,
где меняется номинал ширины (медиана по окну) или направление оси. Узлы отдаются соседнему
участку с наибольшей толщиной, мелкие остатки — соседу по самой длинной общей границе.
Затем соседние участки одной толщины склеиваются через изломы и узлы (Г, П, Т, крест, кольцо):
связная область одного вида и одной толщины — одна конструкция; разрыв остаётся только при смене
номинала. Каждая линия оси помнит полигон своего участка до склейки: по ним ищутся торцы и проёмы.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
import numpy.typing as npt
import shapely
from shapely.geometry import LineString, Polygon

from cad_walls.params import Params

Pt = tuple[float, float]
FloatArr = npt.NDArray[np.float64]


@dataclass
class RawPiece:
    """Участок до назначения номинала: полигон, оси и поперечные ширины его рукавов."""

    polygon: Polygon
    axis: list[list[Pt]]
    widths: list[float]
    # параллельно axis: полигон участка, которому принадлежала линия до склейки одной толщины
    axis_parts: list[Polygon] = field(default_factory=list)


@dataclass
class _Mesh:
    tri: FloatArr  # (n, 3, 2)
    area: FloatArr  # (n,)
    edge_mid: FloatArr  # (m, 2) внутренние рёбра
    edge_len: FloatArr  # (m,)
    edge_vec: FloatArr  # (m, 2) вектор ребра
    edge_tris: list[tuple[int, int]]
    tri_edges: list[list[int]]  # внутренние рёбра треугольника
    apex: list[Pt | None]  # у концевого — вершина против внутреннего ребра


def _build_mesh(poly: Polygon, step: float) -> _Mesh:
    tris = shapely.constrained_delaunay_triangles(shapely.segmentize(poly, step))
    coords = np.array(
        [np.asarray(g.exterior.coords, dtype=np.float64)[:3, :2] for g in tris.geoms],
        dtype=np.float64,
    )
    ids: dict[tuple[float, float], int] = {}
    vid = np.zeros((len(coords), 3), dtype=np.int64)
    for t in range(len(coords)):
        for k in range(3):
            key = (round(float(coords[t, k, 0]), 3), round(float(coords[t, k, 1]), 3))
            vid[t, k] = ids.setdefault(key, len(ids))
    owners: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for t in range(len(coords)):
        for a in range(3):
            i, j = int(vid[t, a]), int(vid[t, (a + 1) % 3])
            owners.setdefault((min(i, j), max(i, j)), []).append((t, a))
    mids: list[FloatArr] = []
    lens: list[float] = []
    vecs: list[FloatArr] = []
    edge_tris: list[tuple[int, int]] = []
    tri_edges: list[list[int]] = [[] for _ in range(len(coords))]
    apex: list[Pt | None] = [None] * len(coords)
    opposite: dict[int, int] = {}
    for key in sorted(owners):
        sides = owners[key]
        if len(sides) != 2:
            continue
        (t1, a1), (t2, a2) = sides
        eid = len(lens)
        p, q = coords[t1, a1], coords[t1, (a1 + 1) % 3]
        mids.append((p + q) / 2)
        lens.append(float(np.hypot(*(p - q))))
        vecs.append(q - p)
        edge_tris.append((t1, t2))
        tri_edges[t1].append(eid)
        tri_edges[t2].append(eid)
        opposite[t1] = (a1 + 2) % 3
        opposite[t2] = (a2 + 2) % 3
    for t, edges in enumerate(tri_edges):
        if len(edges) == 1:
            ap = coords[t, opposite[t]]
            apex[t] = (float(ap[0]), float(ap[1]))
    area = 0.5 * np.abs(
        (coords[:, 1, 0] - coords[:, 0, 0]) * (coords[:, 2, 1] - coords[:, 0, 1])
        - (coords[:, 2, 0] - coords[:, 0, 0]) * (coords[:, 1, 1] - coords[:, 0, 1])
    )
    return _Mesh(
        coords,
        area,
        np.array(mids, dtype=np.float64).reshape(-1, 2),
        np.array(lens, dtype=np.float64),
        np.array(vecs, dtype=np.float64).reshape(-1, 2),
        edge_tris,
        tri_edges,
        apex,
    )


@dataclass
class _Chain:
    tris: list[int]
    points: list[Pt]  # len(tris)+1 точек оси: границы между треугольниками и концы
    widths: list[float]  # локальная ширина каждого треугольника


def _other(mesh: _Mesh, eid: int, t: int) -> int:
    a, b = mesh.edge_tris[eid]
    return b if a == t else a


def _chains(mesh: _Mesh) -> list[_Chain]:
    n = len(mesh.tri)
    junction = [len(e) >= 3 for e in mesh.tri_edges]
    seen = [False] * n
    out: list[_Chain] = []

    def links(t: int) -> list[tuple[int, int]]:
        res = [(_other(mesh, e, t), e) for e in mesh.tri_edges[t]]
        return sorted((o, e) for o, e in res if not junction[o])

    for root in range(n):
        if seen[root] or junction[root]:
            continue
        comp: list[int] = []
        queue = deque([root])
        seen[root] = True
        while queue:
            t = queue.popleft()
            comp.append(t)
            for o, _ in links(t):
                if not seen[o]:
                    seen[o] = True
                    queue.append(o)
        ends = sorted(t for t in comp if len(links(t)) <= 1)
        start = ends[0] if ends else min(comp)
        order = [start]
        conn: list[int] = []
        closed = False
        prev, cur = -1, start
        while True:
            cand = [(o, e) for o, e in links(cur) if o != prev]
            if not cand:
                break
            o, e = cand[0]
            conn.append(e)
            if o == start:
                closed = True
                break
            order.append(o)
            prev, cur = cur, o
        out.append(_chain_geometry(mesh, order, conn, closed))
    return out


def _end_point(mesh: _Mesh, t: int, used: set[int]) -> tuple[Pt, float]:
    """Точка оси на конце цепочки: середина ребра к узлу либо вершина концевого треугольника."""
    free = [e for e in mesh.tri_edges[t] if e not in used]
    if free:
        m = mesh.edge_mid[free[0]]
        return (float(m[0]), float(m[1])), float(mesh.edge_len[free[0]])
    ap = mesh.apex[t]
    if ap is not None:
        return ap, 0.0
    c = mesh.tri[t].mean(axis=0)
    return (float(c[0]), float(c[1])), 0.0


def _chain_geometry(mesh: _Mesh, order: list[int], conn: list[int], closed: bool) -> _Chain:
    mid = [(float(mesh.edge_mid[e][0]), float(mesh.edge_mid[e][1])) for e in conn]
    if closed:
        points = [mid[-1], *mid[:-1], mid[-1]]
    else:
        first, _ = _end_point(mesh, order[0], set(conn))
        last, _ = _end_point(mesh, order[-1], set(conn))
        points = [first, *mid, last]
    widths: list[float] = []
    for i, t in enumerate(order):
        edges = mesh.tri_edges[t]
        step = np.asarray(points[i + 1], dtype=np.float64) - np.asarray(points[i], dtype=np.float64)
        norm = float(np.hypot(*step))
        if not edges:
            widths.append(0.0)
        elif norm < 1e-6:
            widths.append(float(np.mean([mesh.edge_len[e] for e in edges])))
        else:
            # ширина — поперечная к оси составляющая хорды: косая хорда зигзага длиннее ширины
            cross = [
                abs(mesh.edge_vec[e][0] * step[1] - mesh.edge_vec[e][1] * step[0]) / norm
                for e in edges
            ]
            widths.append(float(np.mean(cross)))
    return _Chain(order, points, widths)


def _smooth(values: list[float], window: int) -> list[float]:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 3 or window < 3:
        return list(map(float, arr))
    half = window // 2
    padded = np.pad(arr, half, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
    return [float(x) for x in np.median(view, axis=1)]


def _label(width: float, nominals: tuple[float, ...], tol: float) -> int:
    best, best_d = -1, tol + 1e-9
    for i, nom in enumerate(nominals):
        d = abs(width - nom)
        if d < best_d:
            best, best_d = i, d
    return best


def _bend_cuts(points: list[Pt], window: float, split_deg: float) -> list[int]:
    """Индексы точек оси (1..n-1), где направление ломается больше порога; по одному на излом."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 4:
        return []
    seg = np.hypot(*(pts[1:] - pts[:-1]).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    k = np.arange(1, len(pts) - 1)
    j = np.searchsorted(s, s[k] - window, side="left")
    ahead = np.searchsorted(s, s[k] + window, side="right") - 1
    ok = ((s[k] - s[j]) >= window / 2) & ((s[ahead] - s[k]) >= window / 2)
    v1 = pts[k] - pts[j]
    v2 = pts[ahead] - pts[k]
    norm = np.hypot(*v1.T) * np.hypot(*v2.T)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos = np.where(norm > 0, (v1 * v2).sum(axis=1) / norm, 1.0)
    ang = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    ang = np.where(ok, ang, 0.0)
    cand = [int(i) for i in np.argsort(-ang, kind="stable") if ang[i] > split_deg]
    taken: list[int] = []
    for i in cand:
        if all(abs(s[k[i]] - s[k[x]]) >= window for x in taken):
            taken.append(i)
    return sorted(int(k[i]) for i in taken)


@dataclass
class _Segment:
    tris: list[int]
    points: list[Pt]
    widths: list[float]
    smooth: float  # медиана сглаженной ширины
    label: int = -1


def _segments(chain: _Chain, nominals: tuple[float, ...], tol: float, p: Params) -> list[_Segment]:
    smooth = _smooth(chain.widths, p.count("width_median_window"))
    labels = [_label(w, nominals, tol) for w in smooth]
    window = max(p.num("bend_window_mm"), float(np.median(smooth)) if smooth else 0.0)
    cuts = {i for i in range(1, len(labels)) if labels[i] != labels[i - 1]}
    cuts |= set(_bend_cuts(chain.points, window, p.num("split_angle_deg")))
    bounds = [0, *sorted(cuts), len(chain.tris)]
    out: list[_Segment] = []
    for a, b in pairwise(bounds):
        if b <= a:
            continue
        out.append(
            _Segment(
                chain.tris[a:b],
                chain.points[a : b + 1],
                chain.widths[a:b],
                float(np.median(smooth[a:b])),
                labels[a],
            )
        )
    return out


@dataclass
class _Piece:
    tris: list[int] = field(default_factory=list)
    axis: list[list[Pt]] = field(default_factory=list)
    # параллельно axis: треугольники участка перед склейкой одной толщины (общий список на участок)
    axis_tris: list[list[int]] = field(default_factory=list)
    chords: list[float] = field(default_factory=list)  # собственные ширины участка
    area: float = 0.0
    width: float = 0.0
    label: int = -1
    adj: dict[int, float] = field(default_factory=dict)


def _rank(piece: _Piece, nominals: tuple[float, ...]) -> tuple[float, float]:
    """Ключ «самый толстый, при равенстве самый длинный»: по номиналу, если он найден."""
    thickness = nominals[piece.label] if piece.label >= 0 else round(piece.width)
    return (thickness, piece.area)


def _assign_junctions(
    mesh: _Mesh, pieces: dict[int, _Piece], owner: list[int], nominals: tuple[float, ...], p: Params
) -> None:
    n = len(mesh.tri)
    min_area = p.num("min_piece_area_mm2")
    junction = [len(e) >= 3 for e in mesh.tri_edges]
    done = [False] * n
    for root in range(n):
        if not junction[root] or done[root]:
            continue
        cluster: list[int] = []
        queue = deque([root])
        done[root] = True
        while queue:
            t = queue.popleft()
            cluster.append(t)
            for e in mesh.tri_edges[t]:
                o = _other(mesh, e, t)
                if junction[o] and not done[o]:
                    done[o] = True
                    queue.append(o)
        near = sorted(
            {
                owner[_other(mesh, e, t)]
                for t in cluster
                for e in mesh.tri_edges[t]
                if not junction[_other(mesh, e, t)]
            }
        )
        big = [q for q in near if pieces[q].area >= min_area]
        pool = big or near
        if pool:
            host = max(pool, key=lambda q: (_rank(pieces[q], nominals), -q))
        else:
            host = max(pieces, default=-1) + 1
            pieces[host] = _Piece()
        for t in cluster:
            owner[t] = host
            pieces[host].tris.append(t)
            pieces[host].area += float(mesh.area[t])


def _adjacency(mesh: _Mesh, pieces: dict[int, _Piece], owner: list[int]) -> None:
    for e, (a, b) in enumerate(mesh.edge_tris):
        pa, pb = owner[a], owner[b]
        if pa != pb:
            length = float(mesh.edge_len[e])
            pieces[pa].adj[pb] = pieces[pa].adj.get(pb, 0.0) + length
            pieces[pb].adj[pa] = pieces[pb].adj.get(pa, 0.0) + length


def _width(piece: _Piece) -> float:
    return float(np.median(piece.chords)) if piece.chords else math.sqrt(piece.area)


def _merge_small(pieces: dict[int, _Piece], p: Params) -> None:
    """Присоединяет мелкие остатки и паразитные ветки оси к соседу по самой длинной границе.

    Паразитная ветка — лист (один сосед), короче `spur_ratio` толщин соседа: хвосты хордовой оси
    у торцов и углов широких кусков. Собственные ширины и оси присоединённого куска не берутся.
    """
    min_area = p.num("min_piece_area_mm2")
    spur = p.num("spur_ratio")

    def removable(q: int, pc: _Piece) -> bool:
        if not pc.adj:
            return False
        if pc.area < min_area:
            return True
        if len(pc.adj) != 1:
            return False
        (r,) = pc.adj
        return pc.area / max(_width(pc), 1.0) < spur * _width(pieces[r])

    while True:
        small = [(pc.area, q) for q, pc in pieces.items() if removable(q, pc)]
        if not small:
            return
        _, p_id = min(small)
        piece = pieces[p_id]
        target = max(piece.adj, key=lambda r: (piece.adj[r], pieces[r].area, -r))
        host = pieces[target]
        host.tris += piece.tris
        host.area += piece.area
        for r, length in piece.adj.items():
            del pieces[r].adj[p_id]
            if r != target:
                host.adj[r] = host.adj.get(r, 0.0) + length
                pieces[r].adj[target] = pieces[r].adj.get(target, 0.0) + length
        del pieces[p_id]


def _compatible(a: _Piece, b: _Piece, tol: float) -> bool:
    """Одной ли толщины два участка: один номинал либо близкие ширины без номинала."""
    if a.label >= 0 or b.label >= 0:
        return a.label == b.label
    return abs(_width(a) - _width(b)) <= tol


def _merge_same_nominal(pieces: dict[int, _Piece], tol: float) -> None:
    """Склеивает соседние участки одной толщины: связная область одной толщины — один участок.

    Хост — участок с меньшим номером; оси (с составом исходных участков) и ширины обоих участков
    идут вместе. Повторяется до неподвижной точки.
    """
    while True:
        pair = next(
            (
                (q, r)
                for q in sorted(pieces)
                for r in sorted(pieces[q].adj)
                if q < r and _compatible(pieces[q], pieces[r], tol)
            ),
            None,
        )
        if pair is None:
            return
        host_id, p_id = pair
        host, piece = pieces[host_id], pieces[p_id]
        host.tris += piece.tris
        host.area += piece.area
        host.axis += piece.axis
        host.axis_tris += piece.axis_tris
        host.chords += piece.chords
        for r, length in piece.adj.items():
            del pieces[r].adj[p_id]
            if r != host_id:
                host.adj[r] = host.adj.get(r, 0.0) + length
                pieces[r].adj[host_id] = pieces[r].adj.get(host_id, 0.0) + length
        del pieces[p_id]
        host.width = _width(host)


def _simplify_axis(line: list[Pt]) -> list[Pt]:
    if len(line) < 3:
        return line
    simple = LineString(line).simplify(1.0)
    return [(float(x), float(y)) for x, y in simple.coords]


def decompose(poly: Polygon, nominals: tuple[float, ...], tol: float, p: Params) -> list[RawPiece]:
    """Разбивает связный кусок на участки; сумма площадей участков равна площади куска."""
    mesh = _build_mesh(poly, p.num("segmentize_step_mm"))
    n = len(mesh.tri)
    owner = [-1] * n
    pieces: dict[int, _Piece] = {}
    for chain in _chains(mesh):
        for seg in _segments(chain, nominals, tol, p):
            pid = len(pieces)
            piece = _Piece(
                tris=list(seg.tris),
                axis=[seg.points],
                chords=list(seg.widths),
                area=float(sum(mesh.area[t] for t in seg.tris)),
                width=seg.smooth,
                label=seg.label,
            )
            pieces[pid] = piece
            for t in seg.tris:
                owner[t] = pid
    _assign_junctions(mesh, pieces, owner, nominals, p)
    _adjacency(mesh, pieces, owner)
    _merge_small(pieces, p)
    for piece in pieces.values():
        snapshot = list(piece.tris)  # состав участка до склейки; общий для всех его линий оси
        piece.axis_tris = [snapshot for _ in piece.axis]
    _merge_same_nominal(pieces, tol)
    out: list[RawPiece] = []
    cache: dict[int, list[Polygon]] = {}  # по id списка треугольников: части участка до склейки
    for pid in sorted(pieces):
        piece = pieces[pid]
        geom = shapely.union_all(shapely.polygons(mesh.tri[piece.tris]))
        parts = [g for g in shapely.get_parts(geom) if isinstance(g, Polygon)]
        if not parts:
            continue
        for g in parts:
            axis_parts = [_line_part(mesh, tris, g, cache) for tris in piece.axis_tris]
            out.append(
                RawPiece(g, [_simplify_axis(a) for a in piece.axis], list(piece.chords), axis_parts)
            )
    return out


def _line_part(
    mesh: _Mesh, tris: list[int], g: Polygon, cache: dict[int, list[Polygon]]
) -> Polygon:
    """Полигон участка линии оси до склейки; из нескольких частей — та, что больше лежит в `g`."""
    parts = cache.get(id(tris))
    if parts is None:
        geom = shapely.union_all(shapely.polygons(mesh.tri[tris]))
        parts = [q for q in shapely.get_parts(geom) if isinstance(q, Polygon)]
        cache[id(tris)] = parts
    if not parts:
        return g
    return max(parts, key=lambda q: (q.intersection(g).area, q.area))


def min_rect_sides(poly: Polygon) -> tuple[float, float, float]:
    """Стороны минимального повёрнутого прямоугольника: (короткая, длинная, площадь)."""
    rect = poly.minimum_rotated_rectangle
    if not isinstance(rect, Polygon):
        return 0.0, 0.0, 0.0
    c = list(rect.exterior.coords)
    a = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
    b = math.hypot(c[2][0] - c[1][0], c[2][1] - c[1][1])
    return min(a, b), max(a, b), rect.area
