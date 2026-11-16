"""Ручная привязка корпуса к площадке по двум парам точек (ADR-0052): чистая математика.

Привязка - поворот и сдвиг, без масштаба и без зеркала: масштаб листов задаёт калибровка, а не
привязка. Точки - в мм кадра своего вида (системы DXF листа). Без базы данных и без геометрии
сборки: проверки, решение и перевод в постановку здания.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

Point = tuple[float, float]
# Адрес листа в сборке 3D: ревизия документа, страница, вид (как `CadBuilding3dFloorRead`).
SheetKey = tuple[uuid.UUID, int, int]

# База (расстояние между точками источника) короче этого даёт плохой угол: ошибка указания точки
# в 1 м на базе 5 м - это 11 градусов, на 20 м - меньше трёх. Короткая база не принимается.
SITE_PIN_MIN_BASELINE_MM: Final = 5000.0
# Длины отрезков «источник» и «цель» - одно и то же расстояние на объекте. Расхождение больше 1 %
# значит, что указаны не те точки или у листов разный масштаб: привязка без масштаба такое
# не исправит, молча «растянуть» её нельзя.
SITE_PIN_MAX_LENGTH_MISMATCH: Final = 0.01


class SitePinError(ValueError):
    """Привязку нельзя вычислить из этих точек; текст - для человека, по-русски."""


@dataclass(frozen=True, slots=True)
class PinTransform:
    """Кадр вида источника -> кадр вида цели: `q = R(rotation_deg) · p + (offset_x, offset_y)`."""

    rotation_deg: float
    offset_mm: Point
    baseline_mm: float
    residual_mm: float


@dataclass(frozen=True, slots=True)
class SitePin:
    """Действующая привязка для сборки: листы и перевод вида источника в вид цели."""

    id: uuid.UUID
    source: SheetKey
    target: SheetKey
    rotation_deg: float
    offset_mm: Point
    baseline_mm: float
    residual_mm: float
    created_at: datetime


def rotate(point: Point, degrees: float) -> Point:
    """Поворот вокруг начала против часовой стрелки; кратные 90 градусам - без остатка sin/cos."""
    turns = degrees / 90.0
    if turns == round(turns):
        x, y = point
        return ((x, y), (-y, x), (-x, -y), (y, -x))[round(turns) % 4]
    radians = math.radians(degrees)
    cos, sin = math.cos(radians), math.sin(radians)
    return point[0] * cos - point[1] * sin, point[0] * sin + point[1] * cos


def _angle(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))


def _normalized(degrees: float) -> float:
    """Угол в пределах (-180, 180]."""
    value = math.fmod(degrees, 360.0)
    if value <= -180.0:
        value += 360.0
    elif value > 180.0:
        value -= 360.0
    return value


def solve_pin(source: tuple[Point, Point], target: tuple[Point, Point]) -> PinTransform:
    """Поворот и сдвиг по серединам отрезков: `p1, p2` источника переходят в `q1, q2` цели.

    Отказ (`SitePinError`): база короче `SITE_PIN_MIN_BASELINE_MM`, длины отрезков расходятся
    больше чем на `SITE_PIN_MAX_LENGTH_MISMATCH`.
    """
    p1, p2 = source
    q1, q2 = target
    length_p = math.dist(p1, p2)
    length_q = math.dist(q1, q2)
    if length_p < SITE_PIN_MIN_BASELINE_MM or length_q < SITE_PIN_MIN_BASELINE_MM:
        raise SitePinError(
            f"Точки слишком близко: расстояние между ними {min(length_p, length_q) / 1000:.1f} м, "
            f"нужно не меньше {SITE_PIN_MIN_BASELINE_MM / 1000:.0f} м - на короткой базе "
            "угол привязки получается неточным. Выберите точки дальше друг от друга."
        )
    residual = abs(length_p - length_q)
    if residual > SITE_PIN_MAX_LENGTH_MISMATCH * length_p:
        raise SitePinError(
            f"Расстояния между точками не совпадают: на листе корпуса {length_p / 1000:.2f} м, "
            f"на листе площадки {length_q / 1000:.2f} м (расхождение "
            f"{residual / length_p:.1%}, допустимо не больше "
            f"{SITE_PIN_MAX_LENGTH_MISMATCH:.0%}). Проверьте, что точки указаны одни и те же, "
            "и масштаб обоих листов."
        )
    theta = _normalized(_angle(q1, q2) - _angle(p1, p2))
    mid_p = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    mid_q = ((q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2)
    rx, ry = rotate(mid_p, theta)
    return PinTransform(
        rotation_deg=theta,
        offset_mm=(mid_q[0] - rx, mid_q[1] - ry),
        baseline_mm=length_p,
        residual_mm=residual,
    )


def apply_transform(rotation_deg: float, offset_mm: Point, point: Point) -> Point:
    rx, ry = rotate(point, rotation_deg)
    return rx + offset_mm[0], ry + offset_mm[1]


def group_placement(
    *,
    source_rotation_deg: float,
    source_offset_mm: Point,
    target_rotation_deg: float,
    target_offset_mm: Point,
    pin_rotation_deg: float,
    pin_offset_mm: Point,
) -> tuple[float, Point]:
    """Положение группы источника на площадке: `G = S_цели ∘ T_пина ∘ A_источника⁻¹`.

    `A_источника` - совмещение листа в своей группе (`p_группы = R(a)·p_вида + o`), `S_цели` -
    полный перевод вида листа цели в систему площадки, `T_пина` - перевод вида источника в вид
    цели. Результат - `(rotation, offset)` в формуле `p_площадки = R(rotation)·p_группы + offset`.
    """
    rotation = target_rotation_deg + pin_rotation_deg - source_rotation_deg
    rt = rotate(pin_offset_mm, target_rotation_deg)
    ro = rotate(source_offset_mm, rotation)
    return rotation, (
        rt[0] + target_offset_mm[0] - ro[0],
        rt[1] + target_offset_mm[1] - ro[1],
    )
