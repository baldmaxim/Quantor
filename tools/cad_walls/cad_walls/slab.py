"""Данные для 3D-вида этажа (ADR-0039): контур плиты, отверстия-кандидаты, перемычки.

Контур плиты — наружный контур объединения стен после морфологического замыкания: разрывы фасада
(окна, балконные двери) закрываются, внутренние кольца отбрасываются. Отверстие-кандидат — замкнутый
стенами контур без дверного проёма: двери прерывают кладку, поэтому комнаты с дверями дыр в
объединении не дают, а шахты и другие глухие объёмы дают.
"""

from __future__ import annotations

from dataclasses import dataclass

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient

from cad_walls.errors import Issue
from cad_walls.params import Params

MITRE = "mitre"
SIMPLIFY_TOL_MM = 0.05


@dataclass(frozen=True)
class SlabData:
    """Контур плиты (None, если стен нет) и отверстия-кандидаты по порядку (minx, miny)."""

    shell: Polygon | None
    holes: list[Polygon]
    close_radius: float
    issues: list[Issue]


def _union(polygons: list[Polygon]) -> BaseGeometry:
    return shapely.union_all(polygons)


def _closed(geom: BaseGeometry, radius: float) -> BaseGeometry:
    """Морфологическое замыкание: расширение и обратное сжатие с острыми углами."""
    grown = geom.buffer(radius, join_style=MITRE)
    return grown.buffer(-radius, join_style=MITRE)


def _parts(geom: BaseGeometry) -> list[Polygon]:
    return [g for g in shapely.get_parts(geom) if isinstance(g, Polygon) and not g.is_empty]


def _outline(poly: Polygon) -> Polygon:
    """Только наружное кольцо, против часовой стрелки, без шума вершин."""
    shell = orient(Polygon(poly.exterior), 1.0)
    clean = shell.simplify(SIMPLIFY_TOL_MM, preserve_topology=True)
    if isinstance(clean, Polygon) and clean.is_valid and not clean.is_empty:
        return orient(clean, 1.0)
    return shell


def _sort_key(poly: Polygon) -> tuple[float, float, float]:
    x0, y0, _, _ = poly.bounds
    return (round(x0, 1), round(y0, 1), round(poly.area, 1))


def _slab_shell(union: BaseGeometry, radius: float) -> Polygon | None:
    parts = _parts(_closed(union, radius))
    if not parts:
        return None
    biggest = max(parts, key=lambda g: (Polygon(g.exterior).area, -g.bounds[0], -g.bounds[1]))
    return _outline(biggest)


def _holes(union: BaseGeometry, shell: Polygon, p: Params) -> list[Polygon]:
    lo, hi = p.num("slab_hole_min_area_mm2"), p.num("slab_hole_max_area_mm2")
    joined = _closed(union, p.num("hole_join_radius_mm"))
    out: list[Polygon] = []
    for part in _parts(joined):
        for ring in part.interiors:
            hole = Polygon(ring)
            if lo <= hole.area <= hi and shell.contains(hole):
                out.append(_outline(hole))
    out.sort(key=_sort_key)
    return out


def build_slab(polygons: list[Polygon], p: Params) -> SlabData:
    """Контур плиты и отверстия-кандидаты по полигонам стен (кладка и монолит вместе)."""
    radius = p.num("slab_close_radius_mm")
    if not polygons:
        issue = Issue("slab_missing", "нет стен: контур плиты не построен")
        return SlabData(None, [], radius, [issue])
    union = _union(polygons)
    shell = _slab_shell(union, radius)
    if shell is None:
        return SlabData(None, [], radius, [Issue("slab_missing", "контур плиты не построен")])
    return SlabData(shell, _holes(union, shell, p), radius, [])


def lintel_shell(
    center: tuple[float, float],
    direction: tuple[float, float] | None,
    width: float,
    thickness: float | None,
) -> list[tuple[float, float]] | None:
    """Прямоугольник перемычки в плане (против часовой): длина вдоль оси, глубина поперёк."""
    if direction is None or thickness is None:
        return None
    dx, dy = direction
    hw, ht = width / 2, thickness / 2
    cx, cy = center
    nx, ny = -dy, dx
    return [
        (cx - dx * hw - nx * ht, cy - dy * hw - ny * ht),
        (cx + dx * hw - nx * ht, cy + dy * hw - ny * ht),
        (cx + dx * hw + nx * ht, cy + dy * hw + ny * ht),
        (cx - dx * hw + nx * ht, cy - dy * hw + ny * ht),
    ]
