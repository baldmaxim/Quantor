"""Канонический формат `quantor.building_model.v1` (план, раздел 6).

Формат принадлежит Quantor и не зависит ни от plangeom, ни от целевого JSON Revit. Статусы величин:
observed — прочитано с чертежа, derived — выведено из прочитанного, assumed — параметр прототипа,
human — решение человека (в M1 не встречается). Предположение не выдаётся за наблюдение.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from building_model.elements import AxisSource, HingeEnd, OpeningKind, OpensTo
from building_model.geometry import Pt

Status = Literal["observed", "derived", "assumed", "human"]
Severity = Literal["blocker", "warning", "info"]
HoleKind = Literal["stair", "shaft"]
StackKind = Literal["stair", "lift", "possible_lift"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenderOut(_Out):
    """В M1 версий тендера нет: поля приходят из аргументов командной строки и могут быть null."""

    number: str | None = None
    version: int | None = None
    manifest_sha256: str | None = None


class ReaderOut(_Out):
    name: str
    version: str
    normalizer: str


class OriginOut(_Out):
    axes: list[str] | None
    y: Literal["up"] = "up"
    # Положение начала в системе листа plangeom (мм, Y вниз): нужно для обратного перевода.
    sheet_mm: Pt
    source: Literal["axes", "sheet_corner"]


class LevelStatus(_Out):
    elevation_mm: Status | None
    height_mm: Status


class LevelOut(_Out):
    key: str
    floor: int | None
    elevation_mm: float | None
    height_mm: float
    status: LevelStatus
    # Для этажей типового листа: ключ уровня, на котором лежит геометрия (она не копируется).
    instance_of: str | None = None


class SourceRef(_Out):
    page: int
    plangeom_ids: list[str]


class WallOut(_Out):
    key: str
    level: str
    a: Pt
    b: Pt
    thickness_mm: float
    # derived, если ось (а с ней и толщина) выведена из контура стены без segments.
    thickness_status: Status
    axis_source: AxisSource
    role: str
    role_status: Status
    # Каталога типов шаблона в M1 нет: сопоставление типов — этап M6.
    type_ref: str | None
    status: Status
    pieces: int
    bridged_openings: list[str]
    source: list[SourceRef]


class ColumnOut(_Out):
    key: str
    level: str
    polygon: list[Pt]
    status: Status
    source: list[SourceRef]


class SwingOut(_Out):
    hinge_at: HingeEnd
    opens_to: OpensTo


class OpeningStatus(_Out):
    width_mm: Status
    height_mm: Status
    sill_mm: Status | None
    offset_mm: Status | None
    swing: Status | None


class OpeningOut(_Out):
    key: str
    kind: OpeningKind
    level: str
    host: str | None
    offset_mm: float | None
    width_mm: float
    height_mm: float | None
    sill_mm: float | None
    swing: list[SwingOut] | None
    at: Pt
    span: tuple[Pt, Pt]
    status: OpeningStatus
    source: list[SourceRef]


class SlabHole(_Out):
    kind: HoleKind
    polygon: list[Pt]
    status: Status
    source: list[SourceRef]


class SlabStatus(_Out):
    outline: Status
    thickness_mm: Status


class SlabOut(_Out):
    key: str
    level: str
    polygon: list[Pt]
    thickness_mm: float
    holes: list[SlabHole]
    status: SlabStatus
    source: list[SourceRef]


class RoomStatus(_Out):
    area_m2: Status
    type: Status


class RoomOut(_Out):
    key: str
    level: str
    tag: str | None
    type: str
    area_m2: float
    schedule_area_m2: float | None
    polygon: list[Pt]
    status: RoomStatus
    source: list[SourceRef]


class StackOut(_Out):
    key: str
    level: str
    kind: StackKind
    polygon: list[Pt]
    slab_opening: list[Pt] | None
    status: Status
    source: list[SourceRef]


class ReviewItem(_Out):
    code: str
    severity: Severity
    element: str | None
    source_ids: list[str]
    at: Pt | None
    detail: dict[str, float | int | str | None]
    # Концы отрезка (для отсечённых стен): по ним overlay рисует то, что не вошло в модель.
    a: Pt | None = None
    b: Pt | None = None


class ReviewOut(_Out):
    blockers: int
    warnings: int
    # Служебные записи: отсечённые стены и висячие концы у проёмов. Дефектами не считаются.
    info: int
    items: list[ReviewItem]


class BuildingModel(_Out):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # В JSON поле называется `schema`; у BaseModel уже есть метод schema(), поэтому — через alias.
    schema_id: Literal["quantor.building_model.v1"] = Field(
        default="quantor.building_model.v1", alias="schema"
    )
    tender: TenderOut
    reader: ReaderOut
    units: Literal["mm"] = "mm"
    origin: OriginOut
    levels: list[LevelOut]
    walls: list[WallOut]
    openings: list[OpeningOut]
    slabs: list[SlabOut]
    rooms: list[RoomOut]
    stacks: list[StackOut]
    review: ReviewOut
    columns: list[ColumnOut]
    params: dict[str, JsonValue]
    stats: dict[str, JsonValue]
