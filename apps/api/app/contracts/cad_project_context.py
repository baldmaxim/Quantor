"""Контракт проектного контекста CAD (`quantor.cad_project_context.v1`).

Единый срез проекта для ИИ-петли (`ai_review`), MCP-агентов (Claude, Gemini, Codex) и расчётов
ВИС/3D: координационная сетка осей и этажей в системе здания (`building_mm`, тот же контракт
`quantor.object_base.coordination.v1`, что и в выпуске базы), привязки видов (`offset_mm`,
`rotation_deg`, `frame`), высоты из разрезов АР и схем КР, виды фасадов с окнами и зоны помещений
(включая балконы/террасы и МОП) фокусного вида.

Только чтение: геометрию и величины считает детерминированный движок; цен и расценок нет.
"""

from __future__ import annotations

from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_building3d import (
    CadBuilding3dAlignment,
    CadBuilding3dGroupRead,
    CadBuilding3dHeightSource,
    CadBuilding3dOutlineSource,
    CadBuilding3dWarningRead,
)
from app.contracts.tender_exchange import ObjectBaseCoordination

PROJECT_CONTEXT_SCHEMA: Final = "quantor.cad_project_context.v1"

CoordinationSource = Literal["base_release", "live_building3d", "empty"]


class CadProjectCoordinationContext(BaseModel):
    """Координационная сетка осей и этажей объекта (`building_mm`).

    При наличии действующего выпуска базы берётся замороженный `coordination.json` выпуска;
    до выпуска собирается «на лету» из совмещённых этажей `cad_building3d` тем же алгоритмом
    `tender_base_coordination.build_coordination`, чтобы ВИС, 3D и ИИ работали в одной системе.
    """

    source: CoordinationSource
    release_id: UUID | None = None
    release_number: int | None = None
    coordination: ObjectBaseCoordination | None = None
    note: str | None = None


class CadProjectViewPlacement(BaseModel):
    """Положение одного вида (этажа) в общей системе здания и его высоты."""

    view_key: str
    job_id: UUID
    revision_id: UUID
    page_index: int
    view: int
    label: str
    group_key: str
    group_label: str
    corps: str | None = None
    section: str | None = None
    kind: str | None = None
    typical_of: str | None = None
    base_z_mm: int
    elevation_known: bool
    floor_height_mm: int
    floor_height_known: bool
    floor_height_source: CadBuilding3dHeightSource | None = None
    slab_thickness_mm: int
    slab_thickness_known: bool
    offset_mm: list[float]
    rotation_deg: float = 0.0
    alignment: CadBuilding3dAlignment
    alignment_axes: list[str] = Field(default_factory=list)
    outline_source: CadBuilding3dOutlineSource
    slab_area_m2: float | None = None
    windows_count: int = 0
    level_zones_count: int = 0
    # Кадр вида PDF -> DXF мм `[ox_pt, oy_pt, mm_per_pt]`, если подтверждён.
    frame: list[float] | None = None


class CadProjectSectionLevel(BaseModel):
    """Уровень этажа из распознанного разреза АР (`cad_sections`)."""

    id: UUID
    revision_id: UUID
    page_index: int
    cut: str | None = None
    corps: str | None = None
    section: str | None = None
    floor: int | None = None
    elevation_mm: int
    upper_elevation_mm: int
    clear_height_mm: int | None = None
    structure_mm: int | None = None
    status: str
    auto_accepted: bool = False
    evidence: str


class CadProjectKrLevel(BaseModel):
    """Отметка верха плиты этажа по заголовку схемы КР (`cad_project_levels`)."""

    corps: str
    floor: int
    z_mm: int
    ref: str
    source: str = "схеме КР"


class CadProjectFacadeWindowSample(BaseModel):
    """Окно вида фасада: отметки подоконника/верха и ширина в мм."""

    z_bottom_mm: int | None = None
    z_top_mm: int | None = None
    width_mm: int | None = None


class CadProjectFacadeView(BaseModel):
    """Вид фасада АР (`cad_facades`): оси, привязка и сводка окон."""

    id: UUID
    revision_id: UUID
    page_index: int
    view_key: str
    title: str
    corps: str | None = None
    section: str | None = None
    axis_from: str | None = None
    axis_to: str | None = None
    status: str
    scale_status: str
    axes: list[str] = Field(default_factory=list)
    window_count: int = 0
    windows_sample: list[CadProjectFacadeWindowSample] = Field(default_factory=list)


class CadProjectZoneSummary(BaseModel):
    """Зона помещения на листе (`cad_zones`), включая балконы/террасы и МОП."""

    id: UUID
    kind: str
    apartment_no: str | None = None
    room_mark: str | None = None
    name: str | None = None
    room_type: str | None = None
    expl_area_m2: float | None = None
    generator_area_m2: float | None = None
    source: str
    quality_status: str


class CadProjectFocusView(BaseModel):
    """Детальный контекст выбранного вида: соседи по вертикали, зоны и мостик координат."""

    view_key: str
    revision_id: UUID
    page_index: int
    view: int
    placement: CadProjectViewPlacement | None = None
    below_label: str | None = None
    below_z_mm: int | None = None
    above_label: str | None = None
    above_z_mm: int | None = None
    zones: list[CadProjectZoneSummary] = Field(default_factory=list)
    apartment_zones_count: int = 0
    mop_zones_count: int = 0
    balcony_terrace_zones_count: int = 0
    coordinate_bridge: str


class CadProjectContextRead(BaseModel):
    """Полный проектный контекст CAD: сетка, этажи, высоты, фасады и фокусный вид."""

    model_config = ConfigDict(populate_by_name=True)

    schema_name: Literal["quantor.cad_project_context.v1"] = Field(
        default=PROJECT_CONTEXT_SCHEMA, alias="schema"
    )
    project_id: UUID
    project_name: str
    coordination: CadProjectCoordinationContext
    groups: list[CadBuilding3dGroupRead] = Field(default_factory=list)
    views: list[CadProjectViewPlacement] = Field(default_factory=list)
    sections: list[CadProjectSectionLevel] = Field(default_factory=list)
    kr_levels: list[CadProjectKrLevel] = Field(default_factory=list)
    project_slab_mm: int | None = None
    project_slab_ref: str | None = None
    facades: list[CadProjectFacadeView] = Field(default_factory=list)
    building_warnings: list[CadBuilding3dWarningRead] = Field(default_factory=list)
    focus_view: CadProjectFocusView | None = None
