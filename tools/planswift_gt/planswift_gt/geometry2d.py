"""Плоская геометрия сборщика датасета: заливка с отверстиями, цель осевой, упрощение, pHash.

Всё в пикселях рабочего растра, стандартной библиотекой. Маска площади — чёт-нечет по центрам
пикселей: отверстие остаётся отверстием, морфология к маске не применяется.
"""

from __future__ import annotations

import math
from itertools import pairwise

Point = tuple[float, float]
Ring = list[Point]


def ring_bounds(rings: list[Ring]) -> tuple[float, float, float, float]:
    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def fill_rings(
    mask: bytearray, width: int, height: int, rings: list[Ring], value: int = 255
) -> None:
    """Заливает внешний контур с отверстиями по правилу чёт-нечет, пиксель — по его центру."""
    if not rings:
        return
    _, min_y, _, max_y = ring_bounds(rings)
    edges = [(a, b) for ring in rings for a, b in pairwise([*ring, ring[0]]) if a[1] != b[1]]
    fill = bytes((value,))
    for y in range(max(0, math.floor(min_y)), min(height, math.ceil(max_y) + 1)):
        center = y + 0.5
        crossings = sorted(
            x0 + (center - y0) * (x1 - x0) / (y1 - y0)
            for (x0, y0), (x1, y1) in edges
            if (y0 <= center) != (y1 <= center)
        )
        row = y * width
        for left, right in zip(crossings[0::2], crossings[1::2], strict=False):
            start = max(0, math.ceil(left - 0.5))
            stop = min(width, math.floor(right - 0.5) + 1)
            if stop > start:
                mask[row + start : row + stop] = fill * (stop - start)


def centerline_target(
    target: bytearray, width: int, height: int, polyline: list[Point], radius: float
) -> None:
    """Цель осевой: 255 на линии, линейный спад до 0 на расстоянии `radius`, максимум по линиям."""
    for (x0, y0), (x1, y1) in pairwise(polyline):
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        left = max(0, math.floor(min(x0, x1) - radius))
        right = min(width - 1, math.ceil(max(x0, x1) + radius))
        top = max(0, math.floor(min(y0, y1) - radius))
        bottom = min(height - 1, math.ceil(max(y0, y1) + radius))
        for y in range(top, bottom + 1):
            cy = y + 0.5
            row = y * width
            for x in range(left, right + 1):
                cx = x + 0.5
                t = 0.0 if length_sq == 0 else ((cx - x0) * dx + (cy - y0) * dy) / length_sq
                t = min(1.0, max(0.0, t))
                distance = math.hypot(cx - (x0 + t * dx), cy - (y0 + t * dy))
                if distance < radius:
                    value = round(255 * (1 - distance / radius))
                    if value > target[row + x]:
                        target[row + x] = value


def point_in_rings(point: Point, rings: list[Ring]) -> bool:
    """Чёт-нечет по всем кольцам: внутри контура и не в отверстии."""
    x, y = point
    inside = False
    for ring in rings:
        for (x0, y0), (x1, y1) in pairwise([*ring, ring[0]]):
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def interior_point(rings: list[Ring], *, steps: int = 16) -> Point | None:
    """Точка внутри фигуры с отверстиями: центр охвата, иначе ближайший к нему узел сетки."""
    left, top, right, bottom = ring_bounds(rings)
    center = ((left + right) / 2, (top + bottom) / 2)
    if point_in_rings(center, rings):
        return center
    candidates = [
        (left + (right - left) * (i + 0.5) / steps, top + (bottom - top) * (j + 0.5) / steps)
        for i in range(steps)
        for j in range(steps)
    ]
    inside = [p for p in candidates if point_in_rings(p, rings)]
    if not inside:
        return None
    return min(inside, key=lambda p: (math.hypot(p[0] - center[0], p[1] - center[1]), p))


def simplify(points: list[Point], tolerance: float, *, closed: bool) -> list[Point]:
    """Дуглас — Пекер. Замкнутое кольцо режется по двум самым удалённым вершинам."""
    if len(points) <= 3:
        return list(points)
    if closed:
        far = max(range(len(points)), key=lambda i: math.dist(points[0], points[i]))
        first = _douglas_peucker(points[: far + 1], tolerance)
        second = _douglas_peucker([*points[far:], points[0]], tolerance)
        return [*first[:-1], *second[:-1]]
    return _douglas_peucker(points, tolerance)


def _douglas_peucker(points: list[Point], tolerance: float) -> list[Point]:
    if len(points) <= 2:
        return list(points)
    (x0, y0), (x1, y1) = points[0], points[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    worst, index = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        distance = (
            math.hypot(px - x0, py - y0)
            if length == 0
            else abs((x1 - x0) * (y0 - py) - (x0 - px) * (y1 - y0)) / length
        )
        if distance > worst:
            worst, index = distance, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    return [
        *_douglas_peucker(points[: index + 1], tolerance)[:-1],
        *_douglas_peucker(points[index:], tolerance),
    ]


def phash(gray: bytes, width: int, height: int) -> int:
    """Перцептивный хеш 64 бита: среднее 32×32, DCT, 8×8 низких частот, порог — медиана."""
    size = 32
    pooled = [0.0] * (size * size)
    for j in range(size):
        y0, y1 = j * height // size, max(j * height // size + 1, (j + 1) * height // size)
        for i in range(size):
            x0, x1 = i * width // size, max(i * width // size + 1, (i + 1) * width // size)
            total = sum(sum(gray[y * width + x0 : y * width + x1]) for y in range(y0, y1))
            pooled[j * size + i] = total / ((y1 - y0) * (x1 - x0))
    cosines = [
        [math.cos((2 * x + 1) * u * math.pi / (2 * size)) for x in range(size)] for u in range(8)
    ]
    coefficients: list[float] = []
    for v in range(8):
        for u in range(8):
            coefficients.append(
                sum(
                    pooled[y * size + x] * cosines[u][x] * cosines[v][y]
                    for y in range(size)
                    for x in range(size)
                )
            )
    body = coefficients[1:]
    median = sorted(body)[len(body) // 2]
    bits = 0
    for index, value in enumerate(coefficients):
        if index and value > median:
            bits |= 1 << index
    return bits


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
