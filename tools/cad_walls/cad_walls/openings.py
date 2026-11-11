"""Проёмы: двери (блоки на слоях дверей) и безымянные разрывы между соосными участками.

Дверь стоит в разрыве стены: торцы участков по обе стороны разрыва лежат на одной оси.
Торец — конец оси, продлённый вдоль неё до выхода из полигона участка. Ширина проёма — расстояние
между торцами (`gap`); нет второй стороны — большая сторона bbox блока (`block_bbox`, оценка).
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from itertools import pairwise

import numpy as np
import numpy.typing as npt
import shapely
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from cad_walls.constructions import Construction
from cad_walls.dxfin import Door
from cad_walls.params import Params

FloatArr = npt.NDArray[np.float64]
MIN_BACK_MM = 100.0
MIN_GAP_MM = 1.0


@dataclass(frozen=True)
class End:
    """Свободный торец участка: точка на оси и единичное направление наружу."""

    owner: int
    point: FloatArr
    direction: FloatArr


@dataclass
class Opening:
    id: str
    kind: str  # door | gap
    status: str  # ok | estimate | no_data
    host_id: str | None
    adjacent_ids: list[str]
    width: float
    width_source: str  # gap | block_bbox
    thickness: float | None
    block_name: str | None
    handle: str | None
    center: tuple[float, float]
    # единичный вектор вдоль оси стены; знак нормализован (dx > 0, при dx == 0 — dy > 0)
    direction: tuple[float, float] | None = None
    # точка на оси стены посреди проёма — центр перемычки (center двери — центр блока со створкой)
    axis_point: tuple[float, float] | None = None


def _axis_point(con: Construction, center: tuple[float, float]) -> tuple[float, float] | None:
    """Ближайшая к точке точка оси конструкции."""
    lines = [LineString(line) for line in con.axis if len(line) >= 2]
    if not lines:
        return None
    pt = shapely.Point(center)
    best = min(lines, key=lambda ln: ln.distance(pt))
    near = best.interpolate(best.project(pt))
    return (round(near.x, 3), round(near.y, 3))


def unit_direction(dx: float, dy: float) -> tuple[float, float] | None:
    """Единичный вектор с детерминированным знаком; нулевой вектор — None."""
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        return None
    ux, uy = round(dx / norm, 6) + 0.0, round(dy / norm, 6) + 0.0
    if ux < 0 or (ux == 0 and uy < 0):
        ux, uy = -ux + 0.0, -uy + 0.0
    return ux, uy


def _axis_direction(con: Construction, center: tuple[float, float]) -> tuple[float, float] | None:
    """Направление ближайшего к точке звена оси конструкции."""
    best: tuple[float, float, float] | None = None
    c = np.asarray(center, dtype=np.float64)
    for line in con.axis:
        arr = np.asarray(line, dtype=np.float64)
        for a, b in pairwise(arr):
            dist = _seg_dist(c, a, b)
            if best is None or dist < best[0]:
                best = (dist, float(b[0] - a[0]), float(b[1] - a[1]))
    return None if best is None else unit_direction(best[1], best[2])


def _end_of(
    line: FloatArr, at_start: bool, t: float, poly: shapely.Polygon
) -> tuple[FloatArr, FloatArr] | None:
    """Торец у одного конца ломаной оси: точка выхода оси из полигона и направление наружу."""
    pts = line[::-1] if at_start else line
    axis = LineString(pts)
    back = max(t, MIN_BACK_MM)
    if axis.length < back / 2:
        return None
    base = axis.interpolate(max(axis.length - back, 0.0))
    origin = np.array([base.x, base.y], dtype=np.float64)
    vec = pts[-1] - origin
    norm = float(np.hypot(*vec))
    if norm < 1e-6:
        return None
    d = vec / norm
    hit = poly.intersection(LineString([origin, origin + d * (back + 3 * t)]))
    parts = [g for g in shapely.get_parts(hit) if g.geom_type == "LineString"]
    if not parts:
        return None
    here = min(parts, key=lambda g: g.distance(Point(origin)))
    coords = np.asarray(here.coords, dtype=np.float64)
    return coords[int(np.argmax(coords @ d))], d


def free_ends(cons: list[Construction], p: Params) -> list[End]:
    tol = p.num("end_contact_tol_mm")
    tree = STRtree([c.polygon for c in cons])
    out: list[End] = []
    for i, c in enumerate(cons):
        for line in c.axis:
            arr = np.asarray(line, dtype=np.float64)
            for at_start in (True, False):
                found = _end_of(arr, at_start, c.thickness, c.polygon)
                if found is None:
                    continue
                point, d = found
                near = tree.query(Point(point).buffer(tol))
                if any(
                    int(j) != i and cons[int(j)].polygon.distance(Point(point)) < tol for j in near
                ):
                    continue
                out.append(End(i, point, d))
    return out


def _seg_dist(p: FloatArr, a: FloatArr, b: FloatArr) -> float:
    ab = b - a
    denom = float(ab @ ab)
    f = 0.0 if denom == 0 else min(max(float((p - a) @ ab) / denom, 0.0), 1.0)
    return float(np.hypot(*(p - (a + ab * f))))


def _coaxial(a: End, b: End, cons: list[Construction], cos_split: float) -> float | None:
    """Ширина разрыва между двумя торцами, если они смотрят друг на друга по одной оси."""
    if a.owner == b.owner or float(a.direction @ b.direction) > -cos_split:
        return None
    v = b.point - a.point
    gap = float(np.hypot(*v))
    if gap < MIN_GAP_MM or float(v @ a.direction) <= 0 or float(v @ b.direction) >= 0:
        return None
    half = max(cons[a.owner].thickness, cons[b.owner].thickness) / 2
    off_a = abs(float(v[0] * a.direction[1] - v[1] * a.direction[0]))
    off_b = abs(float(v[0] * b.direction[1] - v[1] * b.direction[0]))
    if off_a > half or off_b > half:
        return None
    if cons[a.owner].polygon.distance(cons[b.owner].polygon) < MIN_GAP_MM:
        return None
    return gap


def _host(cons: list[Construction], idx: list[int]) -> Construction:
    """Несущая стена проёма: более толстая из соседних, при равенстве — первая по id."""
    return min((cons[i] for i in idx), key=lambda c: (-c.thickness, c.id))


def _opening_id(kind: str, key: str, center: tuple[float, float]) -> str:
    raw = f"{kind}|{key}|{round(center[0])}|{round(center[1])}"
    return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _unique(openings: list[Opening]) -> list[Opening]:
    used: dict[str, int] = {}
    for o in openings:
        n = used.get(o.id, 0)
        used[o.id] = n + 1
        if n:
            o.id = f"{o.id}-{n + 1}"
    return openings


def _door_opening(door: Door, ends: list[End], cons: list[Construction], p: Params) -> Opening:
    reach = door.max_side + p.num("door_gap_tol_mm")
    cos_split = math.cos(math.radians(p.num("split_angle_deg")))
    center = np.asarray(door.center, dtype=np.float64)
    near = [e for e in ends if float(np.hypot(*(e.point - center))) <= reach]
    best: tuple[float, End, End, float] | None = None
    for i, a in enumerate(near):
        for b in near[i + 1 :]:
            gap = _coaxial(a, b, cons, cos_split)
            if gap is None:
                continue
            dist = _seg_dist(center, a.point, b.point)
            if dist > door.max_side / 2 + p.num("door_gap_tol_mm"):
                continue
            score = gap + 2 * dist
            if best is None or score < best[0]:
                best = (score, a, b, gap)
    if best is not None:
        _, a, b, gap = best
        owners = sorted({a.owner, b.owner}, key=lambda i: cons[i].id)
        host = _host(cons, owners)
        return Opening(
            id=_opening_id("door", door.handle, door.center),
            kind="door",
            status="ok",
            host_id=host.id,
            adjacent_ids=[cons[i].id for i in owners],
            width=gap,
            width_source="gap",
            thickness=host.thickness,
            block_name=door.block_name,
            handle=door.handle,
            center=door.center,
            direction=unit_direction(float(a.direction[0]), float(a.direction[1])),
            axis_point=(
                round(float(a.point[0] + b.point[0]) / 2, 3),
                round(float(a.point[1] + b.point[1]) / 2, 3),
            ),
        )
    near_owners = sorted({e.owner for e in near}, key=lambda i: cons[i].id)
    near_host = _host(cons, near_owners) if near_owners else None
    return Opening(
        id=_opening_id("door", door.handle, door.center),
        kind="door",
        status="estimate",
        host_id=near_host.id if near_host else None,
        adjacent_ids=[cons[i].id for i in near_owners],
        width=door.max_side,
        width_source="block_bbox",
        thickness=near_host.thickness if near_host else None,
        block_name=door.block_name,
        handle=door.handle,
        center=door.center,
        direction=_axis_direction(near_host, door.center) if near_host else None,
        axis_point=_axis_point(near_host, door.center) if near_host else None,
    )


def _gap_openings(
    ends: list[End], cons: list[Construction], doors: list[Door], p: Params
) -> list[Opening]:
    """Соосные разрывы одного номинала без двери: вероятно окно или портал."""
    cos_split = math.cos(math.radians(p.num("split_angle_deg")))
    max_gap = p.num("max_gap_mm")
    min_gap = p.num("min_gap_mm")
    best: dict[int, tuple[float, int]] = {}
    for i, a in enumerate(ends):
        nominal = cons[a.owner].thickness_nominal
        if nominal is None:
            continue
        for j, b in enumerate(ends):
            if i == j or cons[b.owner].thickness_nominal != nominal:
                continue
            gap = _coaxial(a, b, cons, cos_split)
            if gap is None or gap > max_gap or gap < min_gap:
                continue
            if i not in best or (gap, j) < best[i]:
                best[i] = (gap, j)
    out: list[Opening] = []
    for i, (gap, j) in sorted(best.items()):
        if i > j or best.get(j, (0.0, -1))[1] != i:
            continue
        a, b = ends[i], ends[j]
        mid = (a.point + b.point) / 2
        center = (float(mid[0]), float(mid[1]))
        covered = any(
            _seg_dist(np.asarray(d.center, dtype=np.float64), a.point, b.point)
            <= d.max_side / 2 + p.num("door_gap_tol_mm")
            for d in doors
        )
        if covered:
            continue
        owners = sorted({a.owner, b.owner}, key=lambda k: cons[k].id)
        host = _host(cons, owners)
        out.append(
            Opening(
                id=_opening_id("gap", "", center),
                kind="gap",
                status="no_data",
                host_id=host.id,
                adjacent_ids=[cons[k].id for k in owners],
                width=gap,
                width_source="gap",
                thickness=host.thickness,
                block_name=None,
                handle=None,
                center=center,
                direction=unit_direction(float(a.direction[0]), float(a.direction[1])),
            )
        )
    return out


def build_openings(cons: list[Construction], doors: list[Door], p: Params) -> list[Opening]:
    ends = free_ends(cons, p)
    openings = [_door_opening(d, ends, cons, p) for d in doors]
    openings += _gap_openings(ends, cons, doors, p)
    openings.sort(key=lambda o: (o.kind, o.center[1], o.center[0], o.id))
    return _unique(openings)
