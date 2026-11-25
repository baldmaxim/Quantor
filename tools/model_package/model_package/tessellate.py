"""Триангуляция элементов IFC (ifcopenshell.geom) в систему здания, мм.

Итератор получает явный список элементов: без него ifcopenshell считает и проёмы, а
составные части с ним считаются (проверено на витражах Revit). Вывод ifcopenshell - в метрах
мировых координат; из них вычитается смещение начала (раздел 3). Один поток по умолчанию.

Элементы, у которых проёмы заданы тяжёлыми сетками (больше `HEAVY_OPENING_FACES` граней в
сумме), считаются без вычитания проёмов: булева операция OCC над ними идёт часами (в
Капельском - плита отделки паркинга с 27 проёмами-«швами» на ~98 тыс. граней, 74 мин).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import ifcopenshell.geom
import numpy as np

HEAVY_OPENING_FACES = 3000


@dataclass(frozen=True, slots=True)
class Mesh:
    step_id: int
    vertices: np.ndarray  # (n, 3) float64, мм, система здания
    faces: np.ndarray  # (m, 3) int64


def _settings(subtract_openings: bool) -> Any:
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    if not subtract_openings:
        settings.set("disable-opening-subtractions", True)
    return settings


def _item_faces(item: Any, depth: int = 0) -> int:
    """Грубая сложность элемента представления: число граней сеток, иначе 1."""
    if depth > 8:
        return 1
    if item.is_a("IfcFacetedBrep"):
        return len(item.Outer.CfsFaces)
    if item.is_a("IfcPolygonalFaceSet"):
        return len(item.Faces)
    if item.is_a("IfcTriangulatedFaceSet"):
        return len(item.CoordIndex)
    if item.is_a("IfcMappedItem"):
        return sum(_item_faces(i, depth + 1) for i in item.MappingSource.MappedRepresentation.Items)
    if item.is_a("IfcBooleanResult"):
        return sum(
            _item_faces(op, depth + 1)
            for op in (item.FirstOperand, item.SecondOperand)
            if op.is_a("IfcRepresentationItem")
        )
    return 1


def opening_faces(element: Any) -> int:
    """Сумма граней в представлениях проёмов элемента."""
    total = 0
    for rel in getattr(element, "HasOpenings", None) or ():
        rep = rel.RelatedOpeningElement.Representation
        for shape in rep.Representations if rep else ():
            total += sum(_item_faces(item) for item in shape.Items)
    return total


def split_heavy(
    elements: Sequence[Any], limit: int = HEAVY_OPENING_FACES
) -> tuple[list[Any], list[Any]]:
    """(обычные, с тяжёлыми проёмами)."""
    normal: list[Any] = []
    heavy: list[Any] = []
    for element in elements:
        (heavy if opening_faces(element) > limit else normal).append(element)
    return normal, heavy


def _iterate(
    model: Any, elements: Sequence[Any], settings: Any, shift: np.ndarray, threads: int
) -> Iterator[Mesh]:
    if not elements:
        return
    iterator = ifcopenshell.geom.iterator(settings, model, threads, include=list(elements))
    if not iterator.initialize():
        return
    while True:
        shape = iterator.get()
        geom = shape.geometry
        verts = np.asarray(geom.verts, dtype=np.float64).reshape(-1, 3)
        faces = np.asarray(geom.faces, dtype=np.int64).reshape(-1, 3)
        if len(verts) and len(faces):
            yield Mesh(int(shape.id), verts * 1000.0 - shift, faces)
        if not iterator.next():
            break


def tessellate(
    model: Any,
    elements: Sequence[Any],
    offset_mm: tuple[float, float, float],
    threads: int = 1,
    heavy_limit: int = HEAVY_OPENING_FACES,
) -> tuple[dict[int, Mesh], list[Any]]:
    """Меши по step id и список элементов, посчитанных без вычитания проёмов."""
    shift = np.asarray(offset_mm, dtype=np.float64)
    normal, heavy = split_heavy(elements, heavy_limit)
    meshes = {m.step_id: m for m in _iterate(model, normal, _settings(True), shift, threads)}
    for m in _iterate(model, heavy, _settings(False), shift, threads):
        meshes[m.step_id] = m
    return meshes, heavy


def bbox6(vertices: np.ndarray) -> list[float]:
    """[minX, minY, minZ, maxX, maxY, maxZ], мм, 0,1 мм."""
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    return [_r(v) for v in (*lo, *hi)]


def _r(value: float) -> float:
    out = round(float(value), 1)
    return 0.0 if out == 0 else out
