"""Чтение источника IFC: единицы, смещение начала, этажи и оси (разделы 3-5).

Единица длины берётся только из `IfcUnitAssignment` проекта; если её нет - ошибка,
предположений нет. Смещение `origin_offset_mm`: X и Y - перенос `IfcBuilding` (вместе с
участком), Z - разность мировой Z этажа и его `Elevation` (медиана по этажам), то есть
нулевая отметка проекта. Расхождение Z с переносом здания - предупреждение.
Здание этажа - ближайшее `IfcBuilding` вверх по `IfcRelAggregates` (раздел 4).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy as np


class QmpError(Exception):
    """Ошибка выгрузки с понятным сообщением для человека."""


@dataclass(frozen=True, slots=True)
class RawBuilding:
    global_id: str
    name: str


@dataclass(frozen=True, slots=True)
class RawStorey:
    step_id: int
    global_id: str
    name: str
    elevation_mm: float
    elevation_source: str
    building_id: str | None = None  # GlobalId здания этажа; None - этаж вне IfcBuilding


@dataclass(frozen=True, slots=True)
class RawAxis:
    tag: str
    dir: str
    p0: tuple[float, float]
    p1: tuple[float, float]


@dataclass(frozen=True, slots=True)
class Frame:
    unit_mm: float
    offset_mm: tuple[float, float, float]


def open_ifc(path: Path) -> Any:
    try:
        return ifcopenshell.open(str(path))
    except Exception as exc:  # ifcopenshell бросает разные типы
        raise QmpError(f"{path.name}: IFC не открывается: {exc}") from exc


def length_unit_mm(model: Any, name: str) -> float:
    """Миллиметров в единице длины файла; единица обязана быть в IfcUnitAssignment."""
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    if units is None:
        raise QmpError(f"{name}: у IfcProject нет IfcUnitAssignment - единицы неизвестны")
    if not any(getattr(u, "UnitType", None) == "LENGTHUNIT" for u in units.Units):
        raise QmpError(f"{name}: в IfcUnitAssignment нет единицы длины (LENGTHUNIT)")
    return float(ifcopenshell.util.unit.calculate_unit_scale(model)) * 1000.0


def authoring(model: Any) -> str:
    system = getattr(model.header.file_name, "originating_system", "") or ""
    if system:
        return str(system)
    apps = model.by_type("IfcApplication")
    return f"{apps[0].ApplicationFullName} {apps[0].Version}" if apps else ""


def _placement_mm(product: Any, unit_mm: float) -> np.ndarray:
    m = np.array(ifcopenshell.util.placement.get_local_placement(product.ObjectPlacement))
    m[:3, 3] *= unit_mm
    return m


def read_frame(model: Any, unit_mm: float, warnings: list[str], name: str) -> Frame:
    """Смещение начала системы здания относительно мировых координат IFC, мм."""
    buildings = model.by_type("IfcBuilding") or model.by_type("IfcSite")
    base = _placement_mm(buildings[0], unit_mm) if buildings else np.eye(4)
    if buildings and not np.allclose(base[:3, :3], np.eye(3), atol=1e-6):
        warnings.append(f"{name}: размещение здания с поворотом - поворот не учитывается")
    diffs = [
        _placement_mm(s, unit_mm)[2, 3] - float(s.Elevation) * unit_mm
        for s in model.by_type("IfcBuildingStorey")
        if s.Elevation is not None and s.ObjectPlacement is not None
    ]
    z = statistics.median(diffs) if diffs else float(base[2, 3])
    if diffs and (max(diffs) - min(diffs) > 1.0 or abs(z - base[2, 3]) > 1.0):
        warnings.append(
            f"{name}: мировая Z этажей минус Elevation = {min(diffs):.1f}…{max(diffs):.1f} мм, "
            f"Z здания {base[2, 3]:.1f} мм; ноль проекта взят по Elevation ({z:.1f} мм)"
        )
    return Frame(unit_mm, (_r(base[0, 3]), _r(base[1, 3]), _r(z)))


def _r(value: float, nd: int = 1) -> float:
    out = round(float(value), nd)
    return 0.0 if out == 0 else out


def read_buildings(model: Any) -> list[RawBuilding]:
    """Здания файла в порядке файла."""
    return [
        RawBuilding(str(b.GlobalId), str(b.Name or b.LongName or b.GlobalId))
        for b in model.by_type("IfcBuilding")
    ]


def _building_of(product: Any) -> Any | None:
    """Ближайшее IfcBuilding вверх по IfcRelAggregates (этаж может входить в этаж)."""
    seen: set[int] = set()
    parent = ifcopenshell.util.element.get_aggregate(product)
    while parent is not None and parent.id() not in seen:
        if parent.is_a("IfcBuilding"):
            return parent
        seen.add(parent.id())
        parent = ifcopenshell.util.element.get_aggregate(parent)
    return None


def read_storeys(model: Any, frame: Frame, warnings: list[str], name: str) -> list[RawStorey]:
    """Этажи файла с отметкой относительно нуля проекта, мм, и зданием каждого."""
    out: list[RawStorey] = []
    for s in model.by_type("IfcBuildingStorey"):
        if s.Elevation is not None:
            elev, source = float(s.Elevation) * frame.unit_mm, "ifc_storey_elevation"
        elif s.ObjectPlacement is not None:
            elev = _placement_mm(s, frame.unit_mm)[2, 3] - frame.offset_mm[2]
            source = "level"
            warnings.append(f"{name}: у этажа {s.Name!r} нет Elevation - взята Z размещения")
        else:
            warnings.append(
                f"{name}: у этажа {s.Name!r} нет ни Elevation, ни размещения - пропущен"
            )
            continue
        building = _building_of(s)
        out.append(
            RawStorey(
                s.id(),
                s.GlobalId,
                s.Name or s.LongName or s.GlobalId,
                _r(elev),
                source,
                str(building.GlobalId) if building is not None else None,
            )
        )
    return out


def _curve_points(curve: Any) -> list[tuple[float, ...]] | None:
    if curve.is_a("IfcPolyline"):
        return [tuple(float(c) for c in p.Coordinates) for p in curve.Points]
    if curve.is_a("IfcIndexedPolyCurve"):
        return [tuple(float(c) for c in p) for p in curve.Points.CoordList]
    if curve.is_a("IfcTrimmedCurve") and curve.BasisCurve.is_a("IfcLine"):
        t1 = [t for t in curve.Trim1 if t.is_a("IfcCartesianPoint")]
        t2 = [t for t in curve.Trim2 if t.is_a("IfcCartesianPoint")]
        if t1 and t2:
            return [
                tuple(float(c) for c in t1[0].Coordinates),
                tuple(float(c) for c in t2[0].Coordinates),
            ]
    return None


def axis_dir(p0: tuple[float, float], p1: tuple[float, float]) -> str:
    """`U` - ось идёт вдоль Y (постоянная X), `V` - вдоль X (раздел 5)."""
    return "U" if abs(p1[1] - p0[1]) >= abs(p1[0] - p0[0]) else "V"


def read_grids(model: Any, frame: Frame, warnings: list[str], name: str) -> list[RawAxis]:
    """Оси всех IfcGrid файла в системе здания, мм (до сведения повторов)."""
    out: list[RawAxis] = []
    skipped = 0
    for grid in model.by_type("IfcGrid"):
        m = _placement_mm(grid, frame.unit_mm) if grid.ObjectPlacement else np.eye(4)
        for attr in ("UAxes", "VAxes", "WAxes"):
            for axis in getattr(grid, attr, None) or ():
                pts = _curve_points(axis.AxisCurve) if axis.AxisCurve else None
                if not pts or len(pts) < 2:
                    skipped += 1
                    continue
                p0, p1 = (_axis_point(m, pts[0], frame), _axis_point(m, pts[-1], frame))
                out.append(RawAxis(str(axis.AxisTag or ""), axis_dir(p0, p1), p0, p1))
    if skipped:
        warnings.append(f"{name}: {skipped} осей с кривой не-ломаной пропущено")
    return out


def _axis_point(m: np.ndarray, pt: tuple[float, ...], frame: Frame) -> tuple[float, float]:
    local = np.array(
        [
            pt[0] * frame.unit_mm,
            pt[1] * frame.unit_mm,
            (pt[2] if len(pt) > 2 else 0.0) * frame.unit_mm,
            1.0,
        ]
    )
    w = m @ local
    return (_r(w[0] - frame.offset_mm[0]), _r(w[1] - frame.offset_mm[1]))
