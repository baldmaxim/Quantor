"""Контракт общего вида здания для 3D: список этажей проекта с отметками и контуром плиты.

Вид только показывает: этаж — лист CAD с готовыми конструкциями; в итоги обмера, calc и MEP
он не входит. Высоты — те же действующие значения, что в модели этажа (ADR-0039).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

CadBuilding3dOutlineSource = Literal["slab", "bbox"]
# `reference` - эталонный этаж группы; `axes` - совмещён с эталоном по общим осям;
# `none` - не совмещён (смещение - запасное: центр контура на центр эталона или 0).
CadBuilding3dAlignment = Literal["reference", "axes", "none"]


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
    # Корпус и секция из заголовка плана; нет заголовка - `None`.
    corps: str | None
    section: str | None
    # Здание (корпус + секция), к которому относится этаж: ключ и подпись для переключателя.
    group_key: str
    group_label: str
    # Смещение в мм, уже применённое к контуру и bbox этажа: геометрия в системе эталона группы.
    offset_mm: tuple[float, float]
    alignment: CadBuilding3dAlignment
    # Подписи общих осей, по которым совмещён этаж (`alignment = axes`).
    alignment_axes: list[str]
    # Почему этаж не совмещён (`alignment = none`); иначе `None`.
    alignment_message: str | None


class CadBuilding3dGroupRead(BaseModel):
    """Здание для переключателя вида: этажи одного корпуса и секции."""

    key: str
    label: str
    floor_count: int
    # Этажи, совмещённые по осям (эталон входит).
    aligned_count: int


class CadBuilding3dRead(BaseModel):
    units: Literal["mm"]
    floors: list[CadBuilding3dFloorRead]
    groups: list[CadBuilding3dGroupRead]
    warnings: list[CadBuilding3dWarningRead]
