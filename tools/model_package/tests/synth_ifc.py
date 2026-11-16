"""Синтетический IFC для тестов: два этажа, сетка 3×2, стены, колонна, витраж из частей.

Здание поднято на 100 м (смещение начала), единицы - миллиметры. Витраж - IfcCurtainWall
без своей геометрии, с частями IfcPlate и IfcMember (как экспортирует Revit). В первой
стене - проём (IfcOpeningElement), он в пакет попадать не должен.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.geometry
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit
import numpy as np

BUILDING_Z_MM = 100_000.0
GRID_U = {"1": 0.0, "2": 6000.0, "3": 12000.0}
GRID_V = {"А": 0.0, "Б": 8000.0}


@dataclass(frozen=True)
class SynthModel:
    path: Path
    storeys: dict[str, str]  # имя → GlobalId
    column_id: str
    curtain_id: str
    part_ids: list[str]
    opening_id: str


def _matrix(x: float, y: float, z: float, angle_deg: float = 0.0) -> np.ndarray:
    """Матрица размещения в метрах (ifcopenshell.api ждёт СИ)."""
    m = np.eye(4)
    a = np.radians(angle_deg)
    m[:2, :2] = [[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]
    m[:3, 3] = [x / 1000.0, y / 1000.0, z / 1000.0]
    return m


class _Builder:
    def __init__(self, schema: str) -> None:
        self.f = ifcopenshell.api.project.create_file(version=schema)
        if schema == "IFC2X3":  # в IFC2X3 OwnerHistory обязателен: нужен автор и программа
            org = self.f.createIfcOrganization(Name="Синтетика")
            self.f.createIfcPersonAndOrganization(self.f.createIfcPerson(FamilyName="Тест"), org)
            self.f.createIfcApplication(org, "0.1", "synth", "synth")
        self.project = self._entity("IfcProject", "Синтетика")
        length = ifcopenshell.api.unit.add_si_unit(self.f, unit_type="LENGTHUNIT", prefix="MILLI")
        ifcopenshell.api.unit.assign_unit(self.f, units=[length])
        model = ifcopenshell.api.context.add_context(self.f, context_type="Model")
        self.body = ifcopenshell.api.context.add_context(
            self.f,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model,
        )

    def _entity(self, cls: str, name: str | None = None) -> Any:
        return ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=name)

    def place(self, product: Any, matrix: np.ndarray) -> None:
        ifcopenshell.api.geometry.edit_object_placement(self.f, product=product, matrix=matrix)

    def spatial(self, cls: str, name: str, parent: Any, matrix: np.ndarray) -> Any:
        obj = self._entity(cls, name)
        ifcopenshell.api.aggregate.assign_object(self.f, products=[obj], relating_object=parent)
        self.place(obj, matrix)
        return obj

    def box(
        self,
        cls: str,
        name: str,
        length: float,
        height: float,
        thickness: float,
        matrix: np.ndarray,
    ) -> Any:
        """Элемент-параллелепипед: длина вдоль X, толщина вдоль Y, высота вверх (мм)."""
        obj = self._entity(cls, name)
        rep = ifcopenshell.api.geometry.add_wall_representation(
            self.f,
            context=self.body,
            length=length / 1000.0,
            height=height / 1000.0,
            thickness=thickness / 1000.0,
        )
        ifcopenshell.api.geometry.assign_representation(self.f, product=obj, representation=rep)
        self.place(obj, matrix)
        return obj

    def contain(self, storey: Any, *products: Any) -> None:
        ifcopenshell.api.spatial.assign_container(
            self.f, products=list(products), relating_structure=storey
        )

    def grid(self, storey: Any, extent: float = 1500.0) -> Any:
        f = self.f
        grid = self._entity("IfcGrid", "Сетка")
        grid.ObjectPlacement = f.createIfcLocalPlacement(
            storey.ObjectPlacement,
            f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None),
        )

        def axis(tag: str, p0: tuple[float, float], p1: tuple[float, float]) -> Any:
            line = f.createIfcPolyline(
                [f.createIfcCartesianPoint(p0), f.createIfcCartesianPoint(p1)]
            )
            return f.createIfcGridAxis(tag, line, True)

        ys = (min(GRID_V.values()) - extent, max(GRID_V.values()) + extent)
        xs = (min(GRID_U.values()) - extent, max(GRID_U.values()) + extent)
        grid.UAxes = [axis(t, (x, ys[0]), (x, ys[1])) for t, x in GRID_U.items()]
        grid.VAxes = [axis(t, (xs[0], y), (xs[1], y)) for t, y in GRID_V.items()]
        self.contain(storey, grid)
        return grid


def make_arch_ifc(path: Path, schema: str = "IFC4") -> SynthModel:
    """ARCH: этажи 0 и +3000, сетка на каждом этаже, стены, колонна, витраж, проём."""
    b = _Builder(schema)
    site = b.spatial("IfcSite", "Участок", b.project, _matrix(0, 0, 0))
    building = b.spatial("IfcBuilding", "Здание", site, _matrix(0, 0, BUILDING_Z_MM))
    s1 = b.spatial("IfcBuildingStorey", "Этаж 1", building, _matrix(0, 0, BUILDING_Z_MM))
    s2 = b.spatial("IfcBuildingStorey", "Этаж 2", building, _matrix(0, 0, BUILDING_Z_MM + 3000))
    s1.Elevation, s2.Elevation = 0.0, 3000.0
    walls1 = [
        b.box("IfcWall", "Стена 1", 12000, 3000, 200, _matrix(0, 0, BUILDING_Z_MM)),
        b.box("IfcWall", "Стена 2", 8000, 3000, 200, _matrix(0, 0, BUILDING_Z_MM, 90)),
    ]
    walls2 = [b.box("IfcWall", "Стена 3", 12000, 3000, 250, _matrix(0, 8000, BUILDING_Z_MM + 3000))]
    column = b.box(
        "IfcColumn", "Колонна", 400, 3000, 400, _matrix(5800, 3800, BUILDING_Z_MM + 3000)
    )
    b.contain(s1, *walls1)
    b.contain(s2, *walls2, column)
    curtain = b._entity("IfcCurtainWall", "Витраж")
    b.place(curtain, _matrix(12000, 0, BUILDING_Z_MM))
    b.contain(s1, curtain)
    parts = [
        b.box("IfcPlate", "Стекло", 7600, 2800, 24, _matrix(12000, 200, BUILDING_Z_MM + 100, 90)),
        b.box("IfcMember", "Стойка 1", 100, 3000, 60, _matrix(11950, 100, BUILDING_Z_MM, 90)),
        b.box("IfcMember", "Стойка 2", 100, 3000, 60, _matrix(11950, 7800, BUILDING_Z_MM, 90)),
    ]
    ifcopenshell.api.aggregate.assign_object(b.f, products=parts, relating_object=curtain)
    opening = b.box(
        "IfcOpeningElement", "Проём", 1000, 2100, 400, _matrix(2000, -100, BUILDING_Z_MM)
    )
    ifcopenshell.api.feature.add_feature(b.f, feature=opening, element=walls1[0])
    b.grid(s1)
    b.grid(s2)
    b.f.write(str(path))
    return SynthModel(
        path,
        {"Этаж 1": s1.GlobalId, "Этаж 2": s2.GlobalId},
        column.GlobalId,
        curtain.GlobalId,
        [p.GlobalId for p in parts],
        opening.GlobalId,
    )


def make_pl_ifc(path: Path, schema: str = "IFC4") -> Path:
    """PL: этажи с отметками 0 и +3010 (в пределах 20 мм от ARCH), один трубопровод."""
    b = _Builder(schema)
    site = b.spatial("IfcSite", "Участок", b.project, _matrix(0, 0, 0))
    building = b.spatial("IfcBuilding", "Здание", site, _matrix(0, 0, BUILDING_Z_MM))
    s1 = b.spatial("IfcBuildingStorey", "Level 1", building, _matrix(0, 0, BUILDING_Z_MM))
    s2 = b.spatial("IfcBuildingStorey", "Level 2", building, _matrix(0, 0, BUILDING_Z_MM + 3010))
    s1.Elevation, s2.Elevation = 0.0, 3010.0
    pipe = b.box(
        "IfcPipeSegment", "Труба", 5000, 100, 100, _matrix(1000, 2000, BUILDING_Z_MM + 3500)
    )
    b.contain(s2, pipe)
    b.f.write(str(path))
    return path
