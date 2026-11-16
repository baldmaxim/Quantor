"""Горизонтальный разрез этажа на +1200 мм (раздел 8) для привязки чертежа.

Сечение меша плоскостью - отрезки (trimesh), из них кольца (shapely.polygonize) и материал
по правилу чёт-нечет (полость шахты не заливается). Объединение по группе; многоугольник с
дырами (замкнутое кольцо стен подвала вокруг помещений) режется вертикалями через дыры на
куски без дыр - в формате раздела 8 есть только внешние кольца, а залитый контур здания
испортил бы привязку. Кольца замкнутые, первая точка не повторяется, обход против часовой,
0,1 мм. Пустые группы в выход не попадают.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import numpy as np
import trimesh
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, split, unary_union

CUT_ABOVE_MM = 1200.0
GROUP_OF_CATEGORY = {
    "wall": "walls",
    "column": "columns",
    "curtain_wall": "curtain",
    "plate": "curtain",
    "member": "curtain",
}
MIN_AREA_MM2 = 500.0
SIMPLIFY_MM = 0.5
SNAP_MM = 0.01
MAX_SPLIT_DEPTH = 64


def section_polygons(vertices: np.ndarray, faces: np.ndarray, z_cut: float) -> list[Polygon]:
    """Многоугольники сечения одного меша плоскостью z = z_cut (мм)."""
    if not vertices[:, 2].min() < z_cut < vertices[:, 2].max():
        return []
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    try:
        segments = trimesh.intersections.mesh_plane(mesh, [0.0, 0.0, 1.0], [0.0, 0.0, z_cut])
    except (ValueError, IndexError):
        return []
    if len(segments) == 0:
        return []
    lines = np.round(np.asarray(segments)[:, :, :2] / SNAP_MM) * SNAP_MM
    lines = lines[np.any(lines[:, 0] != lines[:, 1], axis=1)]
    if not len(lines):
        return []
    noded = unary_union(MultiLineString([tuple(map(tuple, s)) for s in lines]))
    material: BaseGeometry = Polygon()
    for face in polygonize(noded):
        if face.is_valid and face.area > 0:
            material = material.symmetric_difference(Polygon(face.exterior))
    return _polygons(material)


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    parts = getattr(geom, "geoms", [geom])
    return [p for p in parts if isinstance(p, Polygon) and not p.is_empty]


def hole_free(poly: Polygon, depth: int = 0) -> list[Polygon]:
    """Куски многоугольника без дыр: разрез вертикалью через середину первой дыры."""
    if not poly.interiors:
        return [poly]
    if depth >= MAX_SPLIT_DEPTH:
        return [Polygon(poly.exterior)]
    hx0, _, hx1, _ = poly.interiors[0].bounds
    x = (hx0 + hx1) / 2
    _, y0, _, y1 = poly.bounds
    pieces = _polygons(split(poly, LineString([(x, y0 - 1.0), (x, y1 + 1.0)])))
    if len(pieces) < 2:
        return [Polygon(poly.exterior)]
    return [q for piece in pieces for q in hole_free(piece, depth + 1)]


def _rings(polygons: list[Polygon]) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    for poly in _polygons(unary_union(polygons)):
        if poly.area < MIN_AREA_MM2:
            continue
        for piece in hole_free(poly):
            shell = orient(piece, 1.0).simplify(SIMPLIFY_MM, preserve_topology=True)
            coords = [[_r(x), _r(y)] for x, y in shell.exterior.coords[:-1]]
            if len(coords) >= 3 and shell.area > 1.0:
                rings.append(coords)
    rings.sort(key=lambda ring: (min(p[0] for p in ring), min(p[1] for p in ring)))
    return rings


def _r(value: float) -> float:
    out = round(float(value), 1)
    return 0.0 if out == 0 else out


def build_footprint(
    storey_key: str,
    elevation_mm: float,
    meshes: Iterable[tuple[str, np.ndarray, np.ndarray]],
) -> dict[str, Any]:
    """Разрез этажа по мешам (категория, вершины мм, треугольники)."""
    z_cut = elevation_mm + CUT_ABOVE_MM
    groups: dict[str, list[Polygon]] = defaultdict(list)
    for category, vertices, faces in meshes:
        group = GROUP_OF_CATEGORY.get(category)
        if group is not None:
            groups[group].extend(section_polygons(vertices, faces, z_cut))
    polygons = {g: rings for g in sorted(groups) if (rings := _rings(groups[g]))}
    return {"storey_key": storey_key, "z_cut_mm": _r(z_cut), "polygons": polygons}
