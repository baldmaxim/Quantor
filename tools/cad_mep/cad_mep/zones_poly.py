"""Многоугольники зон из меток тонкого растра: контур, упрощение, дуги остекления, перекрытия."""

from __future__ import annotations

import math
from collections import defaultdict
from itertools import pairwise

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from cad_mep import zones_const as zc
from cad_mep.frame import Frame
from cad_mep.raster import BoolArr, dilate, erode
from cad_mep.zones_raster import Field

FloatArr = NDArray[np.float64]


def largest(geom: BaseGeometry) -> Polygon | None:
    """Наибольший по площади многоугольник геометрии."""
    parts = [p for p in shapely.get_parts(geom) if isinstance(p, Polygon) and not p.is_empty]
    return max(parts, key=lambda p: p.area) if parts else None


def region_polygon(mask: BoolArr, ox: int, oy: int, f: float) -> BaseGeometry:
    """Многоугольник из клеток: одинаковые по горизонтали ряды подряд сливаются в прямоугольники."""
    rects = []
    open_runs: dict[tuple[int, int], int] = {}
    h = mask.shape[0]
    for iy in range(h + 1):
        row = mask[iy] if iy < h else np.zeros(mask.shape[1], dtype=np.bool_)
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        runs = set(
            zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist(), strict=True)
        )
        for r in list(open_runs):
            if r not in runs:
                top = open_runs.pop(r)
                rects.append(box((r[0] + ox) * f, (top + oy) * f, (r[1] + ox) * f, (iy + oy) * f))
        for r in runs:
            if r not in open_runs:
                open_runs[r] = iy
    return shapely.union_all(rects)


def drop_collinear(poly: Polygon, tol_mm: float = zc.COLLINEAR_TOL_MM) -> Polygon:
    """Вершины, лежащие на прямой между соседними (в пределах tol), выбрасываются."""
    pts = list(poly.exterior.coords)[:-1]
    changed = True
    while changed and len(pts) > 3:
        changed = False
        out = []
        n = len(pts)
        for i in range(n):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
            straight = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) > 0
            if straight and LineString([a, c]).distance(Point(b)) < tol_mm:
                changed = True
                continue
            out.append(b)
        if changed:
            pts = out
    return Polygon(pts)


def simplify_poly(p: Polygon, tol: float) -> Polygon:
    q = p.simplify(tol, preserve_topology=True)
    ring = largest(q)
    return drop_collinear(Polygon((ring or p).exterior))


def seed_polygons(
    fld: Field, seed_ids: list[int]
) -> tuple[dict[int, Polygon], dict[int, list[str]]]:
    """Контур каждой области по меткам поля (наибольшая связная часть, без дыр) и замечания."""
    gi = fld.gi
    out: dict[int, Polygon] = {}
    notes: dict[int, list[str]] = defaultdict(list)
    for sid in seed_ids:
        ys, xs = np.nonzero(gi == sid)
        if len(ys) == 0:
            continue
        y0, y1 = max(ys.min() - 3, 0), min(ys.max() + 4, fld.ny)
        x0, x1 = max(xs.min() - 3, 0), min(xs.max() + 4, fld.nx)
        gsub = gi[y0:y1, x0:x1]
        m = gsub == sid
        # тонкие линии проёма (1-2 клетки) внутри области замыкаем: карман откоса входит в помещение
        inner = erode(dilate(m)) & (gsub <= 0) & ~fld.fill[y0:y1, x0:x1]
        parts = sorted(
            (
                p
                for p in shapely.get_parts(region_polygon(m | inner, x0, y0, fld.f))
                if isinstance(p, Polygon)
            ),
            key=lambda p: -p.area,
        )
        rest = sum(p.area for p in parts[1:]) / 1e6
        if len(parts) > 1 and rest >= zc.PART_NOTE_MIN_M2:
            notes[sid].append(
                f"{len(parts)} несвязных частей, взята наибольшая ({parts[0].area / 1e6:.2f} м²; "
                f"остальные {rest:.3f} м²)"
            )
        p = parts[0]
        if p.interiors:
            holes = sum(Polygon(r).area for r in p.interiors) / 1e6
            notes[sid].append(f"{len(p.interiors)} дыр(ы) отброшены ({holes:.3f} м²)")
            p = Polygon(p.exterior)
        out[sid] = p
    return out, notes


def remove_overlaps(polys: dict[int, Polygon]) -> None:
    """Перекрытия снимаются: большая зона остаётся целой, из меньших вычитается пересечение."""
    placed: list[Polygon] = []
    for sid in sorted(polys, key=lambda s: -polys[s].area):
        q = polys[sid]
        over = [p for p in placed if p.intersects(q) and p.intersection(q).area > 1e-6]
        if over:
            rest = largest(q.difference(unary_union(over)))
            if rest is not None:
                q = drop_collinear(Polygon(rest.exterior))
                polys[sid] = q
        placed.append(q)


def fix_invalid(poly: Polygon) -> tuple[Polygon, bool]:
    """(многоугольник, исправляли ли): невалидный чинится buffer(0), берётся наибольшая часть."""
    if poly.is_valid:
        return poly, False
    fixed = largest(poly.buffer(0))
    return (fixed if fixed is not None else poly), True


def simplify_all(polys: dict[int, Polygon], notes: dict[int, list[str]]) -> dict[int, Polygon]:
    """Упрощение контуров и снятие перекрытий (большие зоны первыми)."""
    final: dict[int, Polygon] = {}
    for sid in sorted(polys, key=lambda s: -polys[s].area):
        q, fixed = fix_invalid(simplify_poly(polys[sid], zc.SIMPLIFY_MM))
        if fixed:
            notes[sid].append("исправлена невалидность buffer(0)")
        final[sid] = q
    remove_overlaps(final)
    return final


# --- дуги остекления
def fit_circle(pts: FloatArr) -> tuple[float, float, float, float]:
    """МНК-окружность: (cx, cy, R, наибольшая невязка)."""
    x, y = pts[:, 0], pts[:, 1]
    a = np.column_stack([2 * x, 2 * y, np.ones(len(x))])
    sol = np.linalg.lstsq(a, x * x + y * y, rcond=None)[0]
    cx, cy = float(sol[0]), float(sol[1])
    radius = math.sqrt(max(float(sol[2]) + cx * cx + cy * cy, 0.0))
    return cx, cy, radius, float(np.abs(np.hypot(x - cx, y - cy) - radius).max())


def _arc_runs(pts: list[FloatArr]) -> list[list[int]]:
    """Серии вершин с коротким ребром и одним знаком небольшого поворота — кандидаты в дугу."""
    n = len(pts)
    turn = []
    for i in range(n):
        v1, v2 = pts[i] - pts[i - 1], pts[(i + 1) % n] - pts[i]
        turn.append(math.degrees(math.atan2(v1[0] * v2[1] - v1[1] * v2[0], float(v1 @ v2))))
    elen = [float(np.hypot(*(pts[(i + 1) % n] - pts[i]))) for i in range(n)]
    lo, hi = zc.ARC_EDGE_MIN_MM, zc.ARC_EDGE_MAX_MM
    ok = [
        zc.ARC_TURN_MIN_DEG <= abs(turn[i]) <= zc.ARC_TURN_MAX_DEG
        and lo <= elen[i - 1] <= hi
        and lo <= elen[i] <= hi
        for i in range(n)
    ]
    if all(ok):
        return []
    start = ok.index(False)
    runs: list[list[int]] = []
    cur: list[int] = []
    for v in ((start + t) % n for t in range(1, n + 1)):
        if ok[v] and (not cur or (turn[v] > 0) == (turn[cur[0]] > 0)):
            cur.append(v)
        else:
            if len(cur) >= zc.ARC_MIN_RUN:
                runs.append(cur)
            cur = [v] if ok[v] else []
    if len(cur) >= zc.ARC_MIN_RUN:
        runs.append(cur)
    return runs


def densify_arcs(poly: Polygon) -> tuple[Polygon, int]:
    """Остекление по дуге: между вершинами серии — вершины на окружности, шаг <= ARC_STEP_MM."""
    pts = [np.array(p) for p in poly.exterior.coords[:-1]]
    inserts: dict[int, list[FloatArr]] = {}
    added = 0
    for run in _arc_runs(pts):
        cx, cy, radius, res = fit_circle(np.array([pts[t] for t in run]))
        if not (
            zc.ARC_RADIUS_MIN_MM <= radius <= zc.ARC_RADIUS_MAX_MM and res <= zc.ARC_FIT_MAX_MM
        ):
            continue
        for a_i, b_i in pairwise(run):
            a, b = pts[a_i], pts[b_i]
            m = math.ceil(float(np.hypot(*(b - a))) / zc.ARC_STEP_MM)
            if m <= 1:
                continue
            ta = math.atan2(a[1] - cy, a[0] - cx)
            d = (math.atan2(b[1] - cy, b[0] - cx) - ta + math.pi) % (2 * math.pi) - math.pi
            inserts[a_i] = [
                np.array(
                    [cx + radius * math.cos(ta + d * q / m), cy + radius * math.sin(ta + d * q / m)]
                )
                for q in range(1, m)
            ]
            added += m - 1
    if not added:
        return poly, 0
    out: list[tuple[float, float]] = []
    for t, p in enumerate(pts):
        out.append((float(p[0]), float(p[1])))
        out += [(float(q[0]), float(q[1])) for q in inserts.get(t, [])]
    newp = Polygon(out)
    if not newp.is_valid or abs(newp.area - poly.area) > zc.ARC_AREA_TOL * poly.area:
        return poly, 0
    return newp, added


# --- нормализованные координаты
def to_norm(poly: Polygon, frame: Frame, width_pt: float, height_pt: float) -> list[list[float]]:
    """Вершины в долях размера страницы от левого верхнего угла (6 знаков)."""
    out: list[list[float]] = []
    for x, y in list(poly.exterior.coords)[:-1]:
        px, py = frame.dxf_to_pt(*frame.local_to_dxf(x, y))
        out.append([round(px / width_pt, 6), round(py / height_pt, 6)])
    return out


def norm_area_m2(norm: list[list[float]], width_pt: float, height_pt: float, scale: float) -> float:
    pts = [(x * width_pt, y * height_pt) for x, y in norm]
    return float(Polygon(pts).area * scale * scale / 1e6)
