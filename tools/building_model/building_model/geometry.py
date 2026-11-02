"""Плоская геометрия на кортежах: без Shapely и numpy. Единицы — мм."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

Pt = tuple[float, float]


def sub(p: Pt, q: Pt) -> Pt:
    return (p[0] - q[0], p[1] - q[1])


def add(p: Pt, q: Pt) -> Pt:
    return (p[0] + q[0], p[1] + q[1])


def scale(p: Pt, k: float) -> Pt:
    return (p[0] * k, p[1] * k)


def dot(p: Pt, q: Pt) -> float:
    return p[0] * q[0] + p[1] * q[1]


def cross(p: Pt, q: Pt) -> float:
    return p[0] * q[1] - p[1] * q[0]


def length(p: Pt) -> float:
    return math.hypot(p[0], p[1])


def dist(p: Pt, q: Pt) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def mid(p: Pt, q: Pt) -> Pt:
    return ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)


def unit(p: Pt) -> Pt | None:
    n = length(p)
    if n < 1e-9:
        return None
    return (p[0] / n, p[1] / n)


def rnd(x: float, digits: int = 1) -> float:
    """Округление для выхода; прибавление 0.0 убирает отрицательный ноль."""
    return round(x, digits) + 0.0


def rnd_pt(p: Pt, digits: int = 1) -> Pt:
    return (rnd(p[0], digits), rnd(p[1], digits))


def line_angle_deg(d: Pt) -> float:
    """Угол прямой (направление без знака) в [0, 180)."""
    a = math.degrees(math.atan2(d[1], d[0])) % 180.0
    # 180.0 - 1e-15 после % может дать ровно 180.0 из-за округления
    return 0.0 if a >= 180.0 else a


def line_angle_diff_deg(a: Pt, b: Pt) -> float:
    """Острый угол между направлениями двух прямых, градусы [0, 90]."""
    ua, ub = unit(a), unit(b)
    if ua is None or ub is None:
        return 90.0
    c = min(1.0, abs(dot(ua, ub)))
    return math.degrees(math.acos(c))


def project(p: Pt, a: Pt, b: Pt) -> tuple[float, float, float]:
    """Проекция точки на прямую a->b: (расстояние от a вдоль оси, расстояние до оси, длина a->b).

    Для вырожденного отрезка вдоль = 0, расстояние = до точки a.
    """
    d = sub(b, a)
    n = length(d)
    if n < 1e-9:
        return (0.0, dist(p, a), 0.0)
    u = (d[0] / n, d[1] / n)
    v = sub(p, a)
    return (dot(v, u), abs(cross(u, v)), n)


def point_segment_distance(p: Pt, a: Pt, b: Pt) -> float:
    along, perp, n = project(p, a, b)
    if along < 0.0:
        return dist(p, a)
    if along > n:
        return dist(p, b)
    return perp


def signed_area(poly: Sequence[Pt]) -> float:
    s = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        s += p[0] * q[1] - q[0] * p[1]
    return s / 2.0


def centroid(poly: Sequence[Pt]) -> Pt:
    """Центр масс многоугольника; для вырожденного — среднее вершин."""
    a = signed_area(poly)
    if abs(a) < 1e-9:
        n = max(len(poly), 1)
        return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    cx = cy = 0.0
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        w = p[0] * q[1] - q[0] * p[1]
        cx += (p[0] + q[0]) * w
        cy += (p[1] + q[1]) * w
    return (cx / (6.0 * a), cy / (6.0 * a))


def point_in_polygon(p: Pt, poly: Sequence[Pt]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if p[0] < x:
                inside = not inside
    return inside


def canonical_polygon(poly: Sequence[Pt]) -> list[Pt]:
    """Контур против часовой стрелки, начало — наименьшая вершина: не зависит от порядка входа."""
    pts = list(poly)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return []
    if signed_area(pts) < 0:
        pts.reverse()
    start = min(range(len(pts)), key=lambda i: pts[i])
    return pts[start:] + pts[:start]


def bbox(points: Iterable[Pt]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for p in points:
        xs.append(p[0])
        ys.append(p[1])
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


class SegmentGrid:
    """Равномерная сетка отрезков для выбора кандидатов по рамке; индексы — номера в списке."""

    def __init__(self, segments: Sequence[tuple[Pt, Pt]], cell_mm: float = 2000.0) -> None:
        self._cell = cell_mm
        self._cells: dict[tuple[int, int], list[int]] = {}
        for i, (a, b) in enumerate(segments):
            x0, y0, x1, y1 = bbox((a, b))
            for cx in range(self._ix(x0), self._ix(x1) + 1):
                for cy in range(self._ix(y0), self._ix(y1) + 1):
                    self._cells.setdefault((cx, cy), []).append(i)

    def _ix(self, v: float) -> int:
        return math.floor(v / self._cell)

    def query(self, x0: float, y0: float, x1: float, y1: float) -> list[int]:
        """Индексы отрезков, чьи ячейки пересекают рамку; по возрастанию, без повторов."""
        found: set[int] = set()
        for cx in range(self._ix(x0), self._ix(x1) + 1):
            for cy in range(self._ix(y0), self._ix(y1) + 1):
                found.update(self._cells.get((cx, cy), ()))
        return sorted(found)
