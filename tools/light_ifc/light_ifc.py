"""Облегчённый IFC: только геометрия, без свойств, количеств, материалов и стилей.

    python light_ifc.py <исходный.ifc> <результат.ifc> [--drop IfcCovering,IfcFurnishingElement]

Что остаётся: проект, участок, здание, этажи (имя, отметка, GlobalId как в источнике), сетка осей и
элементы этажей с их GlobalId, именем и классом IFC. Геометрия каждого элемента - одна компактная
сетка треугольников (IfcTriangulatedFaceSet) в координатах здания: метры, нулевая отметка проекта (смещение
участка и здания вычтено), поэтому свойства, привязки к типам и разные виды представления не нужны.
Результат - обычный IFC4: портал принимает его как любой IFC, но разбор и хранение в разы дешевле.
Сетка - IfcTriangulatedFaceSet (список точек одной сущностью и тройки индексов): около 15 байт на
треугольник против ~70 у набора граней; кривые разбиваются грубее исходного (`--deflection-mm`).
Revit отдаёт трубы и приборы мелкими гранями, поэтому сетка элемента прореживается до потолка
`--max-tris` треугольников (квадратичное схлопывание рёбер), а детали мельче `--min-size-mm` не берутся.
Не входят: свойства и количества, материалы, цвета, проёмы, помещения, по умолчанию отделка и мебель.

Зависимости: ifcopenshell, numpy, fast-simplification. Запускать с пониженным приоритетом.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.grid
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import fast_simplification
import numpy as np

DEFAULT_DROP = ("IfcCovering", "IfcFurnishingElement")
ALWAYS_SKIP = ("IfcOpeningElement", "IfcSpace", "IfcAnnotation")
ROUND = 3  # метры -> мм
NAME_LIMIT = 120


def storey_elements(storey: ifcopenshell.entity_instance, skip: set[str]) -> list:
    """Элементы этажа: содержащиеся в нём и все их составные части (панели витража)."""
    found: dict[int, ifcopenshell.entity_instance] = {}
    for rel in storey.ContainsElements:
        for element in rel.RelatedElements:
            found[element.id()] = element
            for part in ifcopenshell.util.element.get_decomposition(element, is_recursive=True):
                found[part.id()] = part
    return [e for e in found.values() if not any(e.is_a(cls) for cls in skip)]


def build_skeleton(src: ifcopenshell.file, dst: ifcopenshell.file, z_offset_m: float):
    """Проект, участок, здание, этажи и сетка осей в метрах."""
    api = ifcopenshell.api
    project = api.root.create_entity(dst, ifc_class="IfcProject", name="Light model")
    api.unit.assign_unit(dst)
    for unit in dst.by_type("IfcSIUnit"):
        if unit.UnitType == "LENGTHUNIT":
            unit.Prefix = None  # метры: координаты записываются в метрах, а не в миллиметрах
    model_ctx = api.context.add_context(dst, context_type="Model")
    body = api.context.add_context(
        dst,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )
    site = api.root.create_entity(dst, ifc_class="IfcSite", name="Site")
    building = api.root.create_entity(dst, ifc_class="IfcBuilding", name="Building")
    api.aggregate.assign_object(dst, products=[site], relating_object=project)
    api.aggregate.assign_object(dst, products=[building], relating_object=site)
    scale = ifcopenshell.util.unit.calculate_unit_scale(src)
    storeys: dict[int, ifcopenshell.entity_instance] = {}
    for source in src.by_type("IfcBuildingStorey"):
        storey = api.root.create_entity(dst, ifc_class="IfcBuildingStorey", name=source.Name)
        storey.GlobalId = source.GlobalId
        storey.LongName = source.LongName
        storey.Elevation = round(float(source.Elevation or 0.0) * scale, ROUND)
        api.aggregate.assign_object(dst, products=[storey], relating_object=building)
        storeys[source.id()] = storey
    return body, building, storeys, scale


def copy_grid(src: ifcopenshell.file, dst: ifcopenshell.file, building, z_offset_m: float) -> int:
    """Первая сетка осей источника (в Revit она повторяется по этажам) одной сеткой."""
    grids = src.by_type("IfcGrid")
    if not grids:
        return 0
    api = ifcopenshell.api
    scale = ifcopenshell.util.unit.calculate_unit_scale(src)
    source = grids[0]
    placement = (
        ifcopenshell.util.placement.get_local_placement(source.ObjectPlacement)
        if source.ObjectPlacement
        else np.eye(4)
    )
    grid = api.root.create_entity(dst, ifc_class="IfcGrid", name="Grid")
    api.spatial.assign_container(dst, products=[grid], relating_structure=building)
    count = 0
    for axes, uvw in ((source.UAxes, "UAxes"), (source.VAxes, "VAxes")):
        for axis in axes or []:
            curve = axis.AxisCurve
            if not curve.is_a("IfcPolyline") or len(curve.Points) < 2:
                continue
            points = [
                (placement @ np.array([*p.Coordinates[:2], 0.0, 1.0]))[:2] * scale
                for p in (curve.Points[0], curve.Points[-1])
            ]
            target = api.grid.create_grid_axis(dst, grid=grid, axis_tag=axis.AxisTag, uvw_axes=uvw)
            api.grid.create_axis_curve(
                dst,
                p1=(round(float(points[0][0]), ROUND), round(float(points[0][1]), ROUND), 0.0),
                p2=(round(float(points[1][0]), ROUND), round(float(points[1][1]), ROUND), 0.0),
                grid_axis=target,
            )
            count += 1
    return count


def decimate(
    vertices: np.ndarray, faces: np.ndarray, max_tris: int
) -> tuple[np.ndarray, np.ndarray]:
    """Не больше `max_tris` треугольников: квадратичное схлопывание рёбер, форма сохраняется."""
    if len(faces) <= max_tris:
        return vertices, faces
    reduction = min(0.95, 1.0 - max_tris / len(faces))
    try:
        points, triangles = fast_simplification.simplify(
            vertices.astype(np.float32), faces.astype(np.int32), target_reduction=reduction
        )
    except (RuntimeError, ValueError):
        return vertices, faces
    if not len(triangles):
        return vertices, faces
    return points.astype(float), triangles.astype(int)


def mesh_of(
    shape, z_offset_m: float, max_tris: int, min_size_m: float
) -> tuple[np.ndarray, np.ndarray] | None:
    """Вершины (метры, нулевая отметка проекта) и треугольники без вырожденных после округления."""
    geometry = shape.geometry
    vertices = np.array(geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.array(geometry.faces, dtype=int).reshape(-1, 3)
    if not len(vertices) or not len(faces):
        return None
    if float((vertices.max(axis=0) - vertices.min(axis=0)).max()) < min_size_m:
        return None
    vertices, faces = decimate(vertices, faces, max_tris)
    vertices[:, 2] -= z_offset_m
    vertices = np.round(vertices, ROUND)
    keep = (
        (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    )
    faces = faces[keep]
    if not len(faces):
        return None
    used, inverse = np.unique(faces.ravel(), return_inverse=True)
    return vertices[used], inverse.reshape(-1, 3)


def triangulated(dst: ifcopenshell.file, body, vertices: np.ndarray, faces: np.ndarray):
    """Тело элемента: IfcTriangulatedFaceSet (индексы с единицы)."""
    points = dst.createIfcCartesianPointList3D(CoordList=vertices.tolist())
    mesh = dst.createIfcTriangulatedFaceSet(
        Coordinates=points, Closed=None, CoordIndex=(faces + 1).tolist()
    )
    shape = dst.createIfcShapeRepresentation(
        ContextOfItems=body,
        RepresentationIdentifier="Body",
        RepresentationType="Tessellation",
        Items=[mesh],
    )
    return dst.createIfcProductDefinitionShape(Representations=[shape])


def convert(
    source: Path,
    target: Path,
    drop: tuple[str, ...],
    deflection_mm: float,
    angle: float,
    max_tris: int,
    min_size_mm: float,
) -> dict[str, int]:
    started = time.time()
    src = ifcopenshell.open(str(source))
    dst = ifcopenshell.file(schema="IFC4")
    building = src.by_type("IfcBuilding")[0]
    z_offset = (
        ifcopenshell.util.placement.get_local_placement(building.ObjectPlacement)[2, 3]
        * ifcopenshell.util.unit.calculate_unit_scale(src)
    )
    body, dst_building, storeys, _scale = build_skeleton(src, dst, z_offset)
    axes = copy_grid(src, dst, dst_building, z_offset)
    skip = set(ALWAYS_SKIP) | set(drop)
    chosen: dict[int, tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]] = {}
    for storey in src.by_type("IfcBuildingStorey"):
        for element in storey_elements(storey, skip):
            chosen.setdefault(element.id(), (element, storeys[storey.id()]))
    print(f"этажей {len(storeys)}, осей {axes}, элементов к выгрузке {len(chosen)}", flush=True)

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    settings.set("mesher-linear-deflection", deflection_mm / 1000.0)
    settings.set("mesher-angular-deflection", angle)
    iterator = ifcopenshell.geom.iterator(
        settings, src, 2, include=[element for element, _ in chosen.values()]
    )
    per_storey: dict[int, list] = {}
    written = triangles = missed = 0
    if iterator.initialize():
        while True:
            shape = iterator.get()
            element, dst_storey = chosen.get(shape.id, (None, None))
            mesh = (
                mesh_of(shape, z_offset, max_tris, min_size_mm / 1000.0)
                if element is not None
                else None
            )
            if mesh is None:
                missed += 1
            else:
                vertices, faces = mesh
                try:
                    product = ifcopenshell.api.root.create_entity(
                        dst, ifc_class=element.is_a(), name=(element.Name or "")[:NAME_LIMIT]
                    )
                except RuntimeError:
                    product = ifcopenshell.api.root.create_entity(
                        dst, ifc_class="IfcBuildingElementProxy", name=(element.Name or "")[:NAME_LIMIT]
                    )
                product.GlobalId = element.GlobalId
                ifcopenshell.api.geometry.edit_object_placement(dst, product=product)
                product.Representation = triangulated(dst, body, vertices, faces)
                per_storey.setdefault(dst_storey.id(), []).append(product)
                written += 1
                triangles += len(faces)
            if not iterator.next():
                break
    for storey_id, products in per_storey.items():
        ifcopenshell.api.spatial.assign_container(
            dst, products=products, relating_structure=dst.by_id(storey_id)
        )
    dst.write(str(target))
    stats = {
        "elements": written,
        "triangles": triangles,
        "without_geometry": missed,
        "bytes_in": source.stat().st_size,
        "bytes_out": target.stat().st_size,
        "seconds": int(time.time() - started),
    }
    print(stats, flush=True)
    return stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--drop", default=",".join(DEFAULT_DROP), help="классы IFC через запятую")
    parser.add_argument("--deflection-mm", type=float, default=5.0, help="допуск кривых, мм")
    parser.add_argument("--angle", type=float, default=0.8, help="угловой допуск, рад")
    parser.add_argument("--max-tris", type=int, default=150, help="потолок треугольников на элемент")
    parser.add_argument("--min-size-mm", type=float, default=30.0, help="мельче - не берём, мм")
    args = parser.parse_args(argv)
    drop = tuple(name for name in args.drop.split(",") if name)
    convert(
        args.source, args.target, drop, args.deflection_mm, args.angle, args.max_tris, args.min_size_mm
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
