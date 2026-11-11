"""Конструкции: участки одной толщины с номиналом, видом (колонна, пилон, стена), id."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from cad_walls.cat import Pt, RawPiece, decompose, min_rect_sides
from cad_walls.fill import Fill
from cad_walls.params import Params

MIN_AXIS_POINTS = 2


@dataclass
class Construction:
    id: str
    kind: str  # masonry | monolith_wall | monolith_pylon | monolith_column
    family: str  # masonry | monolith
    polygon: Polygon
    axis: list[list[Pt]]
    thickness_measured: float
    thickness_nominal: float | None
    length_axis: float
    source_layers: list[str] = field(default_factory=list)

    @property
    def thickness(self) -> float:
        """Толщина для сопоставления: номинал, если он найден, иначе измеренная."""
        return (
            self.thickness_nominal
            if self.thickness_nominal is not None
            else self.thickness_measured
        )


def rect_thickness(area: float, perimeter: float) -> float:
    """Толщина прямоугольника по площади и периметру: t = (P/2 - sqrt((P/2)^2 - 4A)) / 2."""
    half = perimeter / 2
    return (half - math.sqrt(max(half * half - 4 * area, 0.0))) / 2


def match_nominal(t: float, nominals: tuple[float, ...], tol: float) -> float | None:
    best: float | None = None
    best_d = tol + 1e-9
    for nom in nominals:
        d = abs(t - nom)
        if d < best_d:
            best, best_d = nom, d
    return best


def _rect_piece(poly: Polygon) -> RawPiece:
    """Одна конструкция без разбиения: ось — средняя линия повёрнутого прямоугольника."""
    rect = poly.minimum_rotated_rectangle
    c = list(rect.exterior.coords) if isinstance(rect, Polygon) else []
    if len(c) < 4:
        return RawPiece(poly, [], [])
    a = math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1])
    b = math.hypot(c[2][0] - c[1][0], c[2][1] - c[1][1])
    if a >= b:  # длинная сторона c0-c1: ось между серединами коротких сторон
        p0 = ((c[0][0] + c[3][0]) / 2, (c[0][1] + c[3][1]) / 2)
        p1 = ((c[1][0] + c[2][0]) / 2, (c[1][1] + c[2][1]) / 2)
    else:
        p0 = ((c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2)
        p1 = ((c[3][0] + c[2][0]) / 2, (c[3][1] + c[2][1]) / 2)
    return RawPiece(poly, [[p0, p1]], [])


def _axis(raw: RawPiece) -> list[list[Pt]]:
    lines = [line for line in raw.axis if len(line) >= MIN_AXIS_POINTS]
    return lines or _rect_piece(raw.polygon).axis


def _measure(raw: RawPiece, p: Params) -> float:
    poly = raw.polygon
    short, _, rect_area = min_rect_sides(poly)
    t_rect = rect_thickness(poly.area, poly.length)
    if rect_area > 0 and poly.area / rect_area >= p.num("rect_fill_ratio"):
        return t_rect
    if raw.widths:
        return float(np.median(raw.widths))
    return t_rect if t_rect > 0 else short


def _monolith_kind(poly: Polygon, p: Params) -> str:
    short, long, _ = min_rect_sides(poly)
    aspect = long / short if short > 0 else math.inf
    if aspect <= p.num("column_max_aspect"):
        return "monolith_column"
    if aspect <= p.num("pylon_max_aspect"):
        return "monolith_pylon"
    return "monolith_wall"


def _stable_id(c: Construction) -> str:
    nominal = "check" if c.thickness_nominal is None else f"{c.thickness_nominal:g}"
    cx, cy = c.polygon.centroid.x, c.polygon.centroid.y
    area = round(c.polygon.area / 1000) * 1000
    key = f"{c.kind}|{nominal}|{round(cx / 10) * 10}|{round(cy / 10) * 10}|{area}"
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _layers_of(poly: Polygon, layers: dict[str, BaseGeometry]) -> list[str]:
    return sorted(name for name, geom in layers.items() if geom.intersection(poly).area > 1.0)


def build_constructions(
    fill: Fill,
    layers: dict[str, dict[str, BaseGeometry]],
    p: Params,
) -> list[Construction]:
    """Конструкции по обоим видам; `layers[family]` — геометрия слоёв для source_layers."""
    out: list[Construction] = []
    for family in ("masonry", "monolith"):
        nominals = p.nums(f"nominals_{family}_mm")
        tol = p.num(f"tolerance_{family}_mm")
        for comp in fill.polygons[family]:
            _, _, rect_area = min_rect_sides(comp)
            if (
                not comp.interiors
                and rect_area > 0
                and comp.area / rect_area >= p.num("rect_fill_ratio")
            ):
                pieces = [_rect_piece(comp)]
            else:
                pieces = decompose(comp, nominals, tol, p)
            for raw in pieces:
                t = _measure(raw, p)
                if t <= 0:
                    continue
                kind = family if family == "masonry" else _monolith_kind(raw.polygon, p)
                out.append(
                    Construction(
                        id="",
                        kind=kind,
                        family=family,
                        polygon=raw.polygon,
                        axis=_axis(raw),
                        thickness_measured=t,
                        thickness_nominal=match_nominal(t, nominals, tol),
                        length_axis=raw.polygon.area / t,
                        source_layers=_layers_of(raw.polygon, layers[family]),
                    )
                )
    order = {"masonry": 0, "monolith_wall": 1, "monolith_pylon": 2, "monolith_column": 3}
    out.sort(
        key=lambda c: (
            order[c.kind],
            round(c.polygon.centroid.y, 1),
            round(c.polygon.centroid.x, 1),
            round(c.polygon.area, 1),
        )
    )
    used: dict[str, int] = {}
    for c in out:
        base = _stable_id(c)
        n = used.get(base, 0)
        used[base] = n + 1
        c.id = base if n == 0 else f"{base}-{n + 1}"
    return out
