"""Система координат модели: мм, Y вверх, начало — пересечение двух осей сетки (без поворота)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from building_model.geometry import Pt
from building_model.params import Params
from building_model.reader import AxisIn


@dataclass(frozen=True)
class Frame:
    """Перевод из системы листа (мм, Y вниз) в систему модели и обратно."""

    origin_sheet: Pt
    axes: tuple[str, str] | None
    # Метки осей могут отсутствовать; блокер no_axes_origin ставится, когда подходящей пары нет.
    has_axes_origin: bool

    def to_model(self, p: Pt) -> Pt:
        return (p[0] - self.origin_sheet[0], self.origin_sheet[1] - p[1])

    def to_sheet(self, p: Pt) -> Pt:
        return (p[0] + self.origin_sheet[0], self.origin_sheet[1] - p[1])


def _axis_order(axis: AxisIn) -> tuple[str, float, float, int, float, float]:
    # Порядок не зависит от порядка записей входа: у осей нет id, сортируем по значениям.
    return (
        axis.label or "",
        axis.offset_mm,
        axis.angle,
        axis.bubbles,
        axis.normal[0],
        axis.normal[1],
    )


def intersection(a: AxisIn, b: AxisIn) -> Pt | None:
    det = a.normal[0] * b.normal[1] - a.normal[1] * b.normal[0]
    if abs(det) < 1e-9:
        return None
    x = (a.offset_mm * b.normal[1] - b.offset_mm * a.normal[1]) / det
    y = (a.normal[0] * b.offset_mm - b.normal[0] * a.offset_mm) / det
    return (x, y)


def angle_between_deg(a: AxisIn, b: AxisIn) -> float:
    na = math.hypot(*a.normal)
    nb = math.hypot(*b.normal)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    c = (a.normal[0] * b.normal[0] + a.normal[1] * b.normal[1]) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def choose_origin(axes: Sequence[AxisIn], params: Params, corner: Pt) -> Frame:
    """Пара осей с наибольшим числом кружков при угле 60-120°; при равенстве — по метке и смещению.

    Если пары нет, начало — угол листа `corner` и has_axes_origin = False.
    """
    ordered = sorted(axes, key=_axis_order)
    best: tuple[int, AxisIn, AxisIn, Pt] | None = None
    for i, first in enumerate(ordered):
        for second in ordered[i + 1 :]:
            angle = angle_between_deg(first, second)
            if not params.origin_angle_min_deg <= angle <= params.origin_angle_max_deg:
                continue
            point = intersection(first, second)
            if point is None:
                continue
            score = first.bubbles + second.bubbles
            # Строгое «больше»: при равенстве остаётся первая пара в каноническом порядке.
            if best is None or score > best[0]:
                best = (score, first, second, point)
    if best is None:
        return Frame(origin_sheet=corner, axes=None, has_axes_origin=False)
    _, first, second, point = best
    return Frame(
        origin_sheet=point,
        axes=(first.label or "", second.label or ""),
        has_axes_origin=True,
    )
