"""Проёмы: двери (блоки на слоях дверей) и безымянные разрывы между соосными участками.

Дверь стоит в разрыве стены: торцы участков по обе стороны разрыва лежат на одной оси.
Торец — конец оси, продлённый вдоль неё до выхода из полигона участка. Ширина проёма — расстояние
между торцами (`gap`). Торец, касающийся другой конструкции (Т-примыкание, угол), тоже сторона
разрыва двери. Нет пары торцов — ближайший свободный разрыв вдоль оси несущей стены; нет и его —
проём `no_data` без перемычки и полотна (перемычка на сплошной стене не ставится никогда).
У проёма с разрывом есть торцевые сечения стен (отрезки от грани до грани): по ним строятся
перемычка и полотно двери.
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
# Сечение торца: глубина пробной линии внутрь стены, длина линии, окно вокруг оси (доля толщины)
SECTION_DEPTHS_MM = (10.0, 40.0, 100.0)
SECTION_REACH_MM = 3000.0
SECTION_WINDOW = 0.8
SECTION_MERGED_RATIO = 1.3
# Запас зазора между торцами при проверке «разрыв свободен»
CLEAR_SHRINK_MM = 2.0
CLAIM_TOL_MM = 50.0

Pt = tuple[float, float]
Seg = tuple[Pt, Pt]


@dataclass(frozen=True)
class End:
    """Свободный торец участка: точка на оси и единичное направление наружу."""

    owner: int
    point: FloatArr
    direction: FloatArr
    part: int = 0  # индекс линии оси в конструкции-владельце


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
    # торцевые сечения стен по обе стороны разрыва (грань-грань); None — разрыва нет
    sections: tuple[Seg, Seg] | None = None
    # отрезок разрыва между серединами торцов; нужен, чтобы другой проём не занял тот же разрыв
    span: Seg | None = None


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
    parts = [g for g in shapely.get_parts(hit) if g.geom_type == "LineString" and not g.is_empty]
    if not parts:
        return None
    here = min(parts, key=lambda g: g.distance(Point(origin)))
    coords = np.asarray(here.coords, dtype=np.float64)
    return coords[int(np.argmax(coords @ d))], d


def free_ends(cons: list[Construction], p: Params, touching: bool = False) -> list[End]:
    """Торцы участков: свободные (не касаются другой конструкции или участка) или все (touching)."""
    tol = p.num("end_contact_tol_mm")
    tree = STRtree([c.polygon for c in cons])
    out: list[End] = []
    for i, c in enumerate(cons):
        # участки линий оси до склейки; нет их или не сходятся с осями — как у целой конструкции
        parts = c.axis_parts if len(c.axis_parts) == len(c.axis) else []
        for k, line in enumerate(c.axis):
            arr = np.asarray(line, dtype=np.float64)
            for at_start in (True, False):
                found = _end_of(arr, at_start, c.thickness, parts[k] if parts else c.polygon)
                if found is None:
                    continue
                point, d = found
                pt = Point(point)
                near = tree.query(pt.buffer(tol))
                if not touching:
                    if any(int(j) != i and cons[int(j)].polygon.distance(pt) < tol for j in near):
                        continue
                    if any(k2 != k and part.distance(pt) < tol for k2, part in enumerate(parts)):
                        continue
                out.append(End(i, point, d, k))
    return out


def _seg_dist(p: FloatArr, a: FloatArr, b: FloatArr) -> float:
    ab = b - a
    denom = float(ab @ ab)
    f = 0.0 if denom == 0 else min(max(float((p - a) @ ab) / denom, 0.0), 1.0)
    return float(np.hypot(*(p - (a + ab * f))))


def _coaxial(a: End, b: End, cons: list[Construction], cos_split: float) -> float | None:
    """Ширина разрыва между двумя торцами, если они смотрят друг на друга по одной оси."""
    if float(a.direction @ b.direction) > -cos_split:
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
    if a.owner == b.owner:
        # одна конструкция: торцы разных участков, между которыми есть зазор (кольцо с разрывом)
        parts = cons[a.owner].axis_parts
        if a.part == b.part or len(parts) != len(cons[a.owner].axis):
            return None
        if parts[a.part].distance(parts[b.part]) < MIN_GAP_MM:
            return None
    elif cons[a.owner].polygon.distance(cons[b.owner].polygon) < MIN_GAP_MM:
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


def _round_pt(pt: FloatArr) -> Pt:
    return (round(float(pt[0]), 3), round(float(pt[1]), 3))


def _section(
    poly: shapely.Polygon, q: FloatArr, inward: FloatArr, d: FloatArr, t_end: float
) -> Seg | None:
    """Сечение стены у торца: отрезок поперёк d от грани до грани на линии торца (через точку q).

    Пробная линия идёт чуть внутри стены от торца; берётся кусок, ближайший к оси. Окно вокруг
    оси — 0,8 толщины стены торца; кусок длиннее 1,3 толщины (в полигон склеена перпендикулярная
    стена) сжимается до самой толщины.
    """
    n = np.array([-d[1], d[0]], dtype=np.float64)
    for depth in SECTION_DEPTHS_MM:
        c = q + inward * depth
        line = LineString([c - n * SECTION_REACH_MM, c + n * SECTION_REACH_MM])
        pieces: list[tuple[float, float]] = []
        for g in shapely.get_parts(poly.intersection(line)):
            if g.geom_type != "LineString" or g.length < MIN_GAP_MM:
                continue
            us = sorted(float((np.asarray(xy, dtype=np.float64) - q) @ n) for xy in g.coords)
            pieces.append((us[0], us[-1]))
        if not pieces:
            continue
        lo0, hi0 = min(
            pieces, key=lambda r: 0.0 if r[0] <= 0 <= r[1] else min(abs(r[0]), abs(r[1]))
        )
        half = SECTION_WINDOW * t_end
        if hi0 - lo0 > SECTION_MERGED_RATIO * t_end:
            half = min(half, t_end / 2)
        lo, hi = max(lo0, -half), min(hi0, half)
        if hi - lo < MIN_GAP_MM:
            continue
        return (_round_pt(q + n * lo), _round_pt(q + n * hi))
    return None


def _sections(cons: list[Construction], a: End, b: End) -> tuple[Seg, Seg] | None:
    sa = _section(
        cons[a.owner].polygon, a.point, -a.direction, a.direction, cons[a.owner].thickness
    )
    sb = _section(
        cons[b.owner].polygon, b.point, -b.direction, a.direction, cons[b.owner].thickness
    )
    return None if sa is None or sb is None else (sa, sb)


def _clear(a: End, b: End, tree: STRtree) -> bool:
    """Отрезок между торцами не пересекает ни одну конструкцию (края отступом не считаются)."""
    v = b.point - a.point
    norm = float(np.hypot(*v))
    if norm <= 2 * CLEAR_SHRINK_MM:
        return True
    u = v / norm
    seg = LineString([a.point + u * CLEAR_SHRINK_MM, b.point - u * CLEAR_SHRINK_MM])
    return len(tree.query(seg, predicate="intersects")) == 0


def _pair_opening(door: Door, a: End, b: End, gap: float, cons: list[Construction]) -> Opening:
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
        sections=_sections(cons, a, b),
        span=(_round_pt(a.point), _round_pt(b.point)),
    )


def _door_by_ends(
    door: Door,
    ends: list[End],
    cons: list[Construction],
    p: Params,
    tree: STRtree | None,
) -> Opening | None:
    """Дверь в разрыве между двумя торцами; `tree` — проверка, что разрыв между ними свободен."""
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
            if tree is not None and not _clear(a, b, tree):
                continue
            score = gap + 2 * dist
            if best is None or score < best[0]:
                best = (score, a, b, gap)
    if best is None:
        return None
    _, a, b, gap = best
    return _pair_opening(door, a, b, gap, cons)


def _solid_runs(
    origin: FloatArr, d: FloatArr, lo: float, hi: float, cons: list[Construction], tree: STRtree
) -> list[tuple[float, float, int, int]]:
    """Занятые конструкциями отрезки линии: (начало, конец, владелец начала, владелец конца)."""
    line = LineString([origin + d * lo, origin + d * hi])
    raw: list[tuple[float, float, int]] = []
    for j in tree.query(line, predicate="intersects"):
        for g in shapely.get_parts(cons[int(j)].polygon.intersection(line)):
            if g.geom_type != "LineString":
                continue
            ss = sorted(float((np.asarray(xy, dtype=np.float64) - origin) @ d) for xy in g.coords)
            raw.append((ss[0], ss[-1], int(j)))
    raw.sort()
    runs: list[tuple[float, float, int, int]] = []
    for start, end, j in raw:
        if runs and start <= runs[-1][1] + MIN_GAP_MM:
            s0, e0, o0, oe = runs[-1]
            runs[-1] = (s0, max(e0, end), o0, j if end > e0 else oe)
        else:
            runs.append((start, end, j, j))
    return runs


def _search_gap(
    door: Door,
    cons: list[Construction],
    tree: STRtree,
    p: Params,
    claimed: list[Seg],
) -> Opening | None:
    """Ближайший свободный разрыв вдоль оси несущей стены рядом с блоком двери."""
    reach = door.max_side + p.num("door_gap_tol_mm")
    min_gap = p.num("min_gap_mm")
    pt = Point(door.center)
    near = sorted(
        (cons[int(j)].polygon.distance(pt), cons[int(j)].id, int(j))
        for j in tree.query(pt.buffer(reach))
    )
    center = np.asarray(door.center, dtype=np.float64)
    tried: list[tuple[FloatArr, FloatArr]] = []
    best: tuple[tuple[float, float], FloatArr, FloatArr, float, float, int, int] | None = None
    for dist0, _, j in near:
        if dist0 > reach:
            continue
        unit = _axis_direction(cons[j], door.center)
        origin_pt = _axis_point(cons[j], door.center)
        if unit is None or origin_pt is None:
            continue
        d = np.asarray(unit, dtype=np.float64)
        origin = np.asarray(origin_pt, dtype=np.float64)
        nrm = np.array([-d[1], d[0]])
        if any(
            abs(float(d @ td)) > 0.996 and abs(float((origin - to) @ nrm)) < CLAIM_TOL_MM
            for td, to in tried
        ):
            continue
        tried.append((d, origin))
        s_c = float((center - origin) @ d)
        runs = _solid_runs(origin, d, s_c - 2 * reach, s_c + 2 * reach, cons, tree)
        for left, right in pairwise(runs):
            lo, hi = left[1], right[0]
            width = hi - lo
            if width < min_gap or width > reach:
                continue
            dist = 0.0 if lo <= s_c <= hi else min(abs(s_c - lo), abs(s_c - hi))
            if dist > reach:
                continue
            mid = origin + d * (lo + hi) / 2
            if any(
                _seg_dist(mid, np.asarray(a), np.asarray(b)) <= CLAIM_TOL_MM for a, b in claimed
            ):
                continue
            if best is None or (dist, width) < best[0]:
                best = ((dist, width), origin, d, lo, hi, left[3], right[2])
    if best is None:
        return None
    _, origin, d, lo, hi, left_owner, right_owner = best
    owners = sorted({left_owner, right_owner}, key=lambda i: cons[i].id)
    host = _host(cons, owners)
    q_lo, q_hi = origin + d * lo, origin + d * hi
    sa = _section(cons[left_owner].polygon, q_lo, -d, d, cons[left_owner].thickness)
    sb = _section(cons[right_owner].polygon, q_hi, d, d, cons[right_owner].thickness)
    mid = origin + d * (lo + hi) / 2
    return Opening(
        id=_opening_id("door", door.handle, door.center),
        kind="door",
        status="ok",
        host_id=host.id,
        adjacent_ids=[cons[i].id for i in owners],
        width=hi - lo,
        width_source="gap",
        thickness=host.thickness,
        block_name=door.block_name,
        handle=door.handle,
        center=door.center,
        direction=unit_direction(float(d[0]), float(d[1])),
        axis_point=_round_pt(mid),
        sections=None if sa is None or sb is None else (sa, sb),
        span=(_round_pt(q_lo), _round_pt(q_hi)),
    )


def _door_without_gap(door: Door, cons: list[Construction], tree: STRtree, p: Params) -> Opening:
    """Разрыва рядом нет: проём без данных — ни перемычки, ни полотна."""
    reach = door.max_side + p.num("door_gap_tol_mm")
    pt = Point(door.center)
    near = sorted(
        (cons[int(j)].polygon.distance(pt), cons[int(j)].id, int(j))
        for j in tree.query(pt.buffer(reach))
    )
    host = cons[near[0][2]] if near and near[0][0] <= reach else None
    return Opening(
        id=_opening_id("door", door.handle, door.center),
        kind="door",
        status="no_data",
        host_id=host.id if host else None,
        adjacent_ids=[host.id] if host else [],
        width=door.max_side,
        width_source="block_bbox",
        thickness=host.thickness if host else None,
        block_name=door.block_name,
        handle=door.handle,
        center=door.center,
        direction=_axis_direction(host, door.center) if host else None,
    )


def _gap_openings(
    ends: list[End],
    cons: list[Construction],
    doors: list[Door],
    p: Params,
    claimed: list[Seg],
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
        if covered or any(
            _seg_dist(mid, np.asarray(c0), np.asarray(c1)) <= CLAIM_TOL_MM for c0, c1 in claimed
        ):
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
                sections=_sections(cons, a, b),
            )
        )
    return out


def build_openings(cons: list[Construction], doors: list[Door], p: Params) -> list[Opening]:
    free = free_ends(cons, p)
    tree = STRtree([c.polygon for c in cons])
    every = free_ends(cons, p, touching=True)
    found: list[Opening | None] = []
    claimed: list[Seg] = []
    for door in doors:
        op = _door_by_ends(door, free, cons, p, None) or _door_by_ends(door, every, cons, p, tree)
        if op is not None and op.span is not None:
            claimed.append(op.span)
        found.append(op)
    openings: list[Opening] = []
    for door, op in zip(doors, found, strict=True):
        if op is None:
            op = _search_gap(door, cons, tree, p, claimed) or _door_without_gap(door, cons, tree, p)
            if op.span is not None:
                claimed.append(op.span)
        openings.append(op)
    openings += _gap_openings(free, cons, doors, p, claimed)
    openings.sort(key=lambda o: (o.kind, o.center[1], o.center[0], o.id))
    return _unique(openings)
