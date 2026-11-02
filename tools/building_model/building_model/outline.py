"""Ось по контуру для стен plangeom без осевых линий (правило прототипа, не наблюдение).

Прямоугольный контур (4 вершины, углы в пределах допуска от 90°) даёт среднюю линию вдоль длинной
стороны и толщину, равную короткой. Компактные контуры (L/T мала) и не прямоугольники осей не
получают.
Ось, лежащая вдоль уже имеющейся оси из настоящих segments, считается дублем.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from building_model.elements import Piece
from building_model.geometry import (
    Pt,
    SegmentGrid,
    cross,
    dist,
    dot,
    line_angle_diff_deg,
    mid,
    sub,
    unit,
)
from building_model.params import Params


@dataclass(frozen=True)
class RectAxis:
    a: Pt
    b: Pt
    thickness: float


def _clean(polygon: Sequence[Pt]) -> list[Pt]:
    pts = list(polygon)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _is_rectangle(pts: Sequence[Pt], tol_deg: float) -> bool:
    if len(pts) != 4:
        return False
    for i in range(4):
        prev, here, nxt = pts[i - 1], pts[i], pts[(i + 1) % 4]
        u, v = unit(sub(prev, here)), unit(sub(nxt, here))
        if u is None or v is None:
            return False
        angle = math.degrees(math.acos(max(-1.0, min(1.0, dot(u, v)))))
        if abs(angle - 90.0) > tol_deg:
            return False
    return True


def rectangle_axis(polygon: Sequence[Pt], params: Params) -> RectAxis | str:
    """Ось и толщина по контуру либо причина отказа: not_rectangle / compact."""
    pts = _clean(polygon)
    if not _is_rectangle(pts, params.outline_axis_corner_tol_deg):
        return "not_rectangle"
    # Рёбра 0 и 2 параллельны, 1 и 3 параллельны (с допуском угла).
    len_02 = (dist(pts[0], pts[1]) + dist(pts[2], pts[3])) / 2.0
    len_13 = (dist(pts[1], pts[2]) + dist(pts[3], pts[0])) / 2.0
    long_side, short_side = max(len_02, len_13), min(len_02, len_13)
    if short_side <= 0.0 or long_side / short_side < params.outline_axis_min_aspect:
        return "compact"
    if len_02 >= len_13:
        # длинные рёбра 0 и 2: ось соединяет середины коротких рёбер 1 и 3
        return RectAxis(mid(pts[1], pts[2]), mid(pts[3], pts[0]), short_side)
    return RectAxis(mid(pts[0], pts[1]), mid(pts[2], pts[3]), short_side)


def _interval(base: float, slope: float, lo: float, hi: float) -> tuple[float, float] | None:
    """Решение lo <= base + slope * s <= hi относительно s."""
    if abs(slope) < 1e-12:
        return (-math.inf, math.inf) if lo <= base <= hi else None
    s1, s2 = (lo - base) / slope, (hi - base) / slope
    return (min(s1, s2), max(s1, s2))


class RealAxes:
    """Оси настоящих участков с сеткой для быстрой выборки (строится один раз на лист)."""

    def __init__(self, pieces: Sequence[Piece]) -> None:
        self.pieces = list(pieces)
        self.grid = SegmentGrid([(p.a, p.b) for p in self.pieces])
        self.reach = max((p.thickness for p in self.pieces), default=0.0) / 2.0 + 1.0


def covered_share(axis: tuple[Pt, Pt], axes: RealAxes, params: Params) -> float:
    """Доля длины оси, лежащая в пределах t/2 от осей настоящих участков того же направления."""
    a, b = axis
    length = dist(a, b)
    u = unit(sub(b, a))
    if u is None or length <= 0.0:
        return 0.0
    reach = axes.reach
    found = axes.grid.query(
        min(a[0], b[0]) - reach, min(a[1], b[1]) - reach,
        max(a[0], b[0]) + reach, max(a[1], b[1]) + reach,
    )  # fmt: skip
    spans: list[tuple[float, float]] = []
    for i in found:
        piece = axes.pieces[i]
        ur = unit(sub(piece.b, piece.a))
        if ur is None or line_angle_diff_deg(u, ur) > params.angle_tol_deg:
            continue
        half = piece.thickness / 2.0
        # Расстояние до оси и проекция на участок линейны по s вдоль нашей оси.
        across = _interval(cross(ur, sub(a, piece.a)), cross(ur, u), -half, half)
        along = _interval(dot(ur, sub(a, piece.a)), dot(ur, u), 0.0, piece.length)
        if across is None or along is None:
            continue
        lo = max(0.0, across[0], along[0])
        hi = min(length, across[1], along[1])
        if hi > lo:
            spans.append((lo, hi))
    spans.sort()
    covered = 0.0
    current_lo = current_hi = 0.0
    started = False
    for lo, hi in spans:
        if not started:
            current_lo, current_hi, started = lo, hi, True
        elif lo <= current_hi:
            current_hi = max(current_hi, hi)
        else:
            covered += current_hi - current_lo
            current_lo, current_hi = lo, hi
    if started:
        covered += current_hi - current_lo
    return covered / length
