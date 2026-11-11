"""Контракт общего вида здания для 3D: список этажей проекта с отметками и контуром плиты.

Вид только показывает: этаж — лист CAD с готовыми конструкциями; в итоги обмера, calc и MEP
он не входит. Высоты — те же действующие значения, что в модели этажа (ADR-0039).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

CadBuilding3dOutlineSource = Literal["slab", "bbox"]


class CadBuilding3dWarningRead(BaseModel):
    code: str
    message: str


class CadBuilding3dFloorRead(BaseModel):
    """Этаж здания: адрес листа, отметки и контур плиты в мм системы DXF."""

    job_id: UUID
    revision_id: UUID
    page_index: int
    view: int
    document_id: UUID | None
    label: str
    # Отметка этажа (верх плиты); не определена — 0 и `elevation_known = false`.
    elevation_known: bool
    base_z_mm: int
    # Высота этажа и толщина плиты; не определены — типовые значения для отрисовки и
    # `*_known = false` (значение не из документации и не от человека).
    floor_height_mm: int
    floor_height_known: bool
    slab_thickness_mm: int
    slab_thickness_known: bool
    # Контур плиты (не более 200 точек) или прямоугольник по стенам.
    outline: list[list[float]]
    outline_source: CadBuilding3dOutlineSource
    # [minx, miny, maxx, maxy] по плите и стенам листа.
    bbox: list[float] | None


class CadBuilding3dRead(BaseModel):
    units: Literal["mm"]
    floors: list[CadBuilding3dFloorRead]
    warnings: list[CadBuilding3dWarningRead]
