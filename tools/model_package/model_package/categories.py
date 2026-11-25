"""Нейтральные категории элементов (раздел 6) и таблица соответствия классов IFC.

Таблица проверяется сверху вниз, первое совпадение по наследованию (`is_a`) побеждает,
поэтому частные классы стоят выше общих. Версия таблицы пишется в `generator.category_table`.
Для IFC2X3 трубы, воздуховоды и лотки - это `IfcFlowSegment`/`IfcFlowFitting`, их категория
берётся по классу типа (`IfcPipeSegmentType` и т. п.), поэтому в таблице есть и классы типов.
"""

from __future__ import annotations

from typing import Any

CATEGORY_TABLE_VERSION = "ifc-1"

CATEGORIES: tuple[str, ...] = (
    "wall",
    "slab",
    "column",
    "beam",
    "door",
    "window",
    "curtain_wall",
    "plate",
    "member",
    "railing",
    "stair",
    "covering",
    "roof",
    "furniture",
    "equipment",
    "pipe",
    "duct",
    "cable_carrier",
    "other",
)

IFC_CATEGORY: tuple[tuple[str, str], ...] = (
    ("IfcWall", "wall"),
    ("IfcCurtainWall", "curtain_wall"),
    ("IfcSlab", "slab"),
    ("IfcColumn", "column"),
    ("IfcBeam", "beam"),
    ("IfcDoor", "door"),
    ("IfcWindow", "window"),
    ("IfcPlate", "plate"),
    ("IfcMember", "member"),
    ("IfcRailing", "railing"),
    ("IfcStair", "stair"),
    ("IfcStairFlight", "stair"),
    ("IfcRamp", "stair"),
    ("IfcRampFlight", "stair"),
    ("IfcCovering", "covering"),
    ("IfcRoof", "roof"),
    ("IfcFurnishingElement", "furniture"),
    ("IfcPipeSegment", "pipe"),
    ("IfcPipeFitting", "pipe"),
    ("IfcDuctSegment", "duct"),
    ("IfcDuctFitting", "duct"),
    ("IfcCableCarrierSegment", "cable_carrier"),
    ("IfcCableCarrierFitting", "cable_carrier"),
    ("IfcPipeSegmentType", "pipe"),
    ("IfcPipeFittingType", "pipe"),
    ("IfcDuctSegmentType", "duct"),
    ("IfcDuctFittingType", "duct"),
    ("IfcCableCarrierSegmentType", "cable_carrier"),
    ("IfcCableCarrierFittingType", "cable_carrier"),
    ("IfcDistributionElement", "equipment"),
    ("IfcTransportElement", "equipment"),
)

# RGB 0..1 для плоского материала `cat:<category>` в GLB.
CATEGORY_COLOR: dict[str, tuple[float, float, float]] = {
    "wall": (0.75, 0.75, 0.75),
    "slab": (0.59, 0.59, 0.63),
    "column": (0.84, 0.35, 0.24),
    "beam": (0.78, 0.47, 0.24),
    "door": (0.59, 0.39, 0.24),
    "window": (0.47, 0.75, 0.90),
    "curtain_wall": (0.47, 0.75, 0.90),
    "plate": (0.55, 0.80, 0.92),
    "member": (0.35, 0.47, 0.59),
    "railing": (0.43, 0.43, 0.43),
    "stair": (0.67, 0.59, 0.47),
    "covering": (0.88, 0.86, 0.80),
    "roof": (0.63, 0.35, 0.31),
    "furniture": (0.78, 0.71, 0.35),
    "equipment": (0.55, 0.71, 0.39),
    "pipe": (0.24, 0.51, 0.78),
    "duct": (0.39, 0.67, 0.67),
    "cable_carrier": (0.86, 0.63, 0.20),
    "other": (0.71, 0.55, 0.78),
}


def category_of(element: Any, type_class: str | None = None) -> str:
    """Категория элемента IFC; `type_class` - класс его типа (нужен для IFC2X3)."""
    for ifc_class, category in IFC_CATEGORY:
        if ifc_class.endswith("Type"):
            if type_class == ifc_class:
                return category
            continue
        try:
            if element.is_a(ifc_class):
                return category
        except RuntimeError:
            continue
    return "other"
