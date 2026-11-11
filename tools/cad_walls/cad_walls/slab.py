"""Данные для 3D-вида этажа (ADR-0039): контур плиты, отверстия-кандидаты, перемычки.

Контур плиты — наружный контур объединения стен после морфологического замыкания: разрывы фасада
(окна, балконные двери) закрываются, внутренние кольца отбрасываются. Отверстие-кандидат — замкнутый
стенами контур без дверного проёма: двери прерывают кладку, поэтому комнаты с дверями дыр в
объединении не дают, а шахты и другие глухие объёмы дают. Если задан контур зон помещений
(квартиры, МОП), он входит в объединение перед замыканием: зоны закрывают лоджии и участки
фасада, которых замыкание стен не берёт.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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


def build_slab(polygons: list[Polygon], p: Params, zones: Sequence[Polygon] = ()) -> SlabData:
    """Контур плиты и отверстия-кандидаты по полигонам стен (кладка и монолит вместе).

    Зоны помещений расширяются на `slab_zone_buffer_mm` и входят только в контур плиты;
    отверстия-кандидаты ищутся по стенам.
    """
    radius = p.num("slab_close_radius_mm")
    if not polygons:
        issue = Issue("slab_missing", "нет стен: контур плиты не построен")
        return SlabData(None, [], radius, [issue])
    union = _union(polygons)
    buffer = p.num("slab_zone_buffer_mm")
    grown = [z.buffer(buffer, join_style=MITRE) for z in zones if not z.is_empty]
    shell = _slab_shell(_union([union, *grown]) if grown else union, radius)
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


Pt = tuple[float, float]
Seg = tuple[Pt, Pt]


def lintel_hull(
    sections: tuple[Seg, Seg] | None, direction: tuple[float, float] | None = None
) -> list[Pt] | None:
    """Перемычка: выпуклая оболочка торцевых сечений стен по обе стороны разрыва (против часовой).

    Покрывает обе грани и при Т-примыкании, и при несоосных гранях. Оболочка вырождена — None.
    Вершины идут в порядке прямоугольника перемычки: от торца со стороны «минус» вдоль
    `direction` и поперёк слева направо; невыпуклый обход заменяется оболочкой.
    """
    if sections is None:
        return None
    hull = shapely.MultiPoint([*sections[0], *sections[1]]).convex_hull
    if not isinstance(hull, Polygon) or hull.is_empty or hull.area < 1.0:
        return None
    m0 = ((sections[0][0][0] + sections[0][1][0]) / 2, (sections[0][0][1] + sections[0][1][1]) / 2)
    m1 = ((sections[1][0][0] + sections[1][1][0]) / 2, (sections[1][0][1] + sections[1][1][1]) / 2)
    dx, dy = direction if direction is not None else (m1[0] - m0[0], m1[1] - m0[1])
    first, second = sections if (m1[0] - m0[0]) * dx + (m1[1] - m0[1]) * dy >= 0 else sections[::-1]

    def across(seg: Seg) -> Seg:
        lo, hi = seg
        return seg if (hi[0] - lo[0]) * -dy + (hi[1] - lo[1]) * dx >= 0 else (hi, lo)

    f, g = across(first), across(second)
    ring = Polygon([f[0], g[0], g[1], f[1]])
    if (
        ring.is_valid
        and ring.area > 1.0
        and abs(ring.area - hull.area) < 1.0
        and ring.exterior.is_ccw
    ):
        return [f[0], g[0], g[1], f[1]]
    return [(x, y) for x, y in list(orient(hull, 1.0).exterior.coords)[:-1]]


def leaf_shell(sections: tuple[Seg, Seg] | None, thickness: float) -> list[Pt] | None:
    """Полотно двери: прямоугольник толщиной `thickness` по оси между серединами сечений."""
    if sections is None:
        return None
    (a0, a1), (b0, b1) = sections
    m0 = ((a0[0] + a1[0]) / 2, (a0[1] + a1[1]) / 2)
    m1 = ((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2)
    return rect_along(m0, m1, thickness)


def rect_along(start: Pt, end: Pt, thickness: float) -> list[Pt] | None:
    """Прямоугольник вдоль отрезка start-end заданной толщины, против часовой."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1.0:
        return None
    nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
    return [
        (start[0] - nx, start[1] - ny),
        (end[0] - nx, end[1] - ny),
        (end[0] + nx, end[1] + ny),
        (start[0] + nx, start[1] + ny),
    ]
