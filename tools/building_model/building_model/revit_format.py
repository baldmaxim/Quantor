"""Формат `quantor.revit_package.v0`: черновой пакет для сборщика Revit (мм, Y вверх).

Образца формата от автора плагина Revit нет, поэтому схема черновая (`draft_format = true`) и
заменяема: адаптер `revit.py` — единственное место, которое знает про этот формат.
Подробно: docs/building-model/03-revit-package-v0.md. Пакет здания
(`quantor.revit_building_package.v0`, несколько листов в одной системе координат) описан тут же:
docs/building-model/05-revit-building-package-v0.md.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from building_model.approval import ApprovalOut
from building_model.elements import HingeEnd, OpeningKind, OpensTo
from building_model.geometry import Pt

PACKAGE_SCHEMA = "quantor.revit_package.v0"
ADAPTER_NAME = "quantor.revit_adapter"
ADAPTER_VERSION = "0.1.0"
BUILDING_PACKAGE_SCHEMA = "quantor.revit_building_package.v0"

ElementKind = Literal["wall", "opening", "floor", "floor_hole", "column", "stack", "room"]
NotExportedReason = Literal[
    "no_host",
    "ambiguous_host",
    "offset_outside_host",
    "wider_than_host",
    "zero_length_wall",
    "degenerate_polygon",
]
ScaleStatus = Literal["human", "candidate"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


ElementParams = dict[str, str]


class TenderRef(_Out):
    number: str | None
    version: int | None
    manifest_sha256: str | None


class ReaderRef(_Out):
    name: str
    version: str
    normalizer: str


class AdapterRef(_Out):
    name: str
    version: str


class OriginRef(_Out):
    axes: list[str] | None
    source: Literal["axes", "sheet_corner"]
    y: Literal["up"] = "up"


class Coverage(_Out):
    total: int
    exported: int
    not_exported: int


class AssumedParams(_Out):
    door_height_mm: float
    window_sill_mm: float
    window_head_mm: float
    slab_thickness_mm: float
    level_height_mm: float


class Assumptions(_Out):
    params: AssumedParams
    # Сколько выгруженных элементов каждого вида имеет QTO_Status = assumed.
    assumed_elements: dict[str, int]


class ReviewSummary(_Out):
    """Код review -> число записей, по важности. Берётся из модели как есть."""

    blocker: dict[str, int]
    warning: dict[str, int]
    info: dict[str, int]


class Manifest(_Out):
    tender: TenderRef
    reader: ReaderRef
    adapter: AdapterRef
    model_sha256: str
    page: int
    # null — пакет собран без подтверждения человека (--unapproved-test), только для проверки.
    approval: ApprovalOut | None
    scale_status: ScaleStatus
    units: Literal["mm"] = "mm"
    origin: OriginRef
    coverage: dict[str, Coverage]
    review_summary: ReviewSummary
    assumptions: Assumptions


class LevelStatusOut(_Out):
    elevation_mm: str
    height_mm: str


class LevelPkg(_Out):
    id: str
    floor: int | None
    elevation_mm: float
    height_mm: float
    status: LevelStatusOut
    # Не null: геометрия лежит на уровне `instance_of`, сборщик повторяет её на этом уровне.
    instance_of: str | None


class WallType(_Out):
    id: str
    thickness_mm: float
    count: int


class WallPkg(_Out):
    id: str
    level: str
    start: Pt
    end: Pt
    height_mm: float
    type: str
    thickness_mm: float
    structural: bool
    params: ElementParams


class SwingPkg(_Out):
    hinge_at: HingeEnd
    opens_to: OpensTo


class OpeningPkg(_Out):
    id: str
    kind: OpeningKind
    host: str
    offset_mm: float
    width_mm: float
    height_mm: float | None
    sill_mm: float | None
    swing: list[SwingPkg] | None
    at: Pt
    params: ElementParams


class HolePkg(_Out):
    kind: Literal["stair", "shaft"]
    boundary: list[Pt]


class FloorPkg(_Out):
    id: str
    level: str
    boundary: list[Pt]
    holes: list[HolePkg]
    thickness_mm: float
    params: ElementParams


class ColumnPkg(_Out):
    id: str
    level: str
    outline: list[Pt]
    height_mm: float
    params: ElementParams


class StackPkg(_Out):
    id: str
    level: str
    kind: Literal["stair", "lift", "possible_lift"]
    outline: list[Pt]
    slab_opening: list[Pt] | None
    params: ElementParams


class RoomPkg(_Out):
    id: str
    level: str
    tag: str | None
    type: str
    area_m2: float
    boundary: list[Pt]
    point: Pt
    params: ElementParams


class NotExported(_Out):
    key: str
    kind: ElementKind
    reason: NotExportedReason
    at: Pt | None


class RevitPackage(_Out):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: Literal["quantor.revit_package.v0"] = Field(
        default="quantor.revit_package.v0", alias="schema"
    )
    draft_format: Literal[True] = True
    manifest: Manifest
    levels: list[LevelPkg]
    wall_types: list[WallType]
    walls: list[WallPkg]
    openings: list[OpeningPkg]
    floors: list[FloorPkg]
    columns: list[ColumnPkg]
    stacks: list[StackPkg]
    rooms: list[RoomPkg]
    not_exported: list[NotExported]


def dumps_package(package: RevitPackage) -> str:
    """Детерминированная сериализация: порядок полей фиксирован, времени запуска нет."""
    data = package.model_dump(mode="json", by_alias=True)
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def package_json_schema() -> str:
    schema = RevitPackage.model_json_schema(by_alias=True)
    return json.dumps(schema, ensure_ascii=False, indent=1) + "\n"


class SkippedPage(_Out):
    page: int
    reason: str


class BuildingInfo(_Out):
    group: int
    reference_page: int
    # Решения человека: --add-page / --exclude-page.
    added_pages: list[int]
    excluded_pages: list[int]
    skipped_pages: list[SkippedPage]
    # Номера этажей между наименьшим и наибольшим этажом включённых уровней, которых нет в пакете.
    missing_floors: list[int]
    input_sha256: str


class AxisMatch(_Out):
    shared: int
    residual_median_mm: float
    residual_max_mm: float
    outliers: int


class SheetEntry(_Out):
    page: int
    model_sha256: str
    scale_status: ScaleStatus
    approval: ApprovalOut | None
    levels: list[str]
    # Смещение, добавленное ко всем координатам плана листа: [dx, dy], мм, Y вверх.
    offset_mm: Pt
    axis_match: AxisMatch
    coverage: dict[str, Coverage]
    review_summary: ReviewSummary


class BuildingManifest(_Out):
    building: BuildingInfo
    sheets: list[SheetEntry]
    tender: TenderRef
    reader: ReaderRef
    adapter: AdapterRef
    units: Literal["mm"] = "mm"
    # Оси опорного листа: в их системе лежит весь пакет.
    origin: OriginRef
    scale_status: ScaleStatus
    coverage: dict[str, Coverage]
    assumptions: Assumptions


class RevitBuildingPackage(_Out):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: Literal["quantor.revit_building_package.v0"] = Field(
        default="quantor.revit_building_package.v0", alias="schema"
    )
    draft_format: Literal[True] = True
    manifest: BuildingManifest
    levels: list[LevelPkg]
    wall_types: list[WallType]
    walls: list[WallPkg]
    openings: list[OpeningPkg]
    floors: list[FloorPkg]
    columns: list[ColumnPkg]
    stacks: list[StackPkg]
    rooms: list[RoomPkg]
    not_exported: list[NotExported]


def dumps_building_package(package: RevitBuildingPackage) -> str:
    """Детерминированная сериализация, как у пакета листа."""
    data = package.model_dump(mode="json", by_alias=True)
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def building_package_json_schema() -> str:
    schema = RevitBuildingPackage.model_json_schema(by_alias=True)
    return json.dumps(schema, ensure_ascii=False, indent=1) + "\n"
