"""Контракты отделки помещений в пилоте CAD (ADR-0042): шаблоны, назначение, ведомость.

Шаблон - параметры проекта (человек), не результат скрипта. Ведомость - рабочая таблица пилота:
количества считаются при чтении по геометрии зон и уровням листа, не хранятся; это не ВОР Quantor,
не смета и не `Measurement`. Стоимости и цен нет.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.cad_room_types import ROOM_TYPE_VALUES, CadRoomType
from app.contracts.cad_zones import CadZoneKind

TEXT_MAX: Final = 200
UNIT_MAX: Final = 20
MAX_LAYERS: Final = 20
MAX_ASSIGN_ZONES: Final = 500
WALL_HEIGHT_MIN_MM: Final = 1000
WALL_HEIGHT_MAX_MM: Final = 6000
THICKNESS_MAX_MM: Final = 200.0
MAX_COATS: Final = 5

FinishSurface = Literal["floor", "walls", "ceiling"]
FinishTemplateSource = Literal["explicit", "by_type"]
FinishWallHeightSource = Literal["template", "levels"]
FinishWarningCode = Literal[
    "calibration_missing",
    "geometry_issue",
    "wall_height_missing",
    "no_template",
    "gap_unknown_height",
    "door_height_missing",
    "windows_not_detected",
    "edges_unlinked",
]
# Основание стены под отделку (ADR-0042, п. 6): монолит, кладка, каркасная перегородка ГКЛ.
FinishWallBase = Literal["monolith", "masonry", "gkl"]
FinishSkipReason = Literal["door", "parking_space", "not_found"]


def _empty_to_none(value: object) -> object:
    """Пустая строка поля формы - то же, что «не задано»."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class CadFinishLayer(BaseModel):
    """Слой отделки поверхности: работа, материал, число слоёв, толщина, расход."""

    model_config = ConfigDict(extra="forbid")

    work: str = Field(min_length=1, max_length=TEXT_MAX)
    material: str | None = Field(default=None, max_length=TEXT_MAX)
    coats: int = Field(default=1, ge=1, le=MAX_COATS, description="Число слоёв (раз)")
    thickness_mm: float | None = Field(default=None, gt=0, le=THICKNESS_MAX_MM)
    consumption: float | None = Field(
        default=None, gt=0, description="Расход на м² поверхности (на м² · мм, если по толщине)"
    )
    consumption_unit: str | None = Field(
        default=None,
        max_length=UNIT_MAX,
        description="Единица количества материала (кг, л, шт, м³); обязательна при расходе",
    )
    consumption_per_mm: bool = Field(
        default=False, description="Расход задан на м² · мм: количество умножается на толщину"
    )
    bases: list[FinishWallBase] | None = Field(
        default=None,
        min_length=1,
        max_length=len(get_args(FinishWallBase)),
        description=(
            "Основания, по которым идёт слой стен (monolith, masonry, gkl); null - все. "
            "Только для слоёв стен"
        ),
    )

    @field_validator("work", mode="before")
    @classmethod
    def _strip_work(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("material", "consumption_unit", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return _empty_to_none(value)

    @model_validator(mode="after")
    def _consistent(self) -> CadFinishLayer:
        if self.consumption is not None and self.consumption_unit is None:
            raise ValueError("Расход задан без единицы")
        if self.consumption_per_mm and self.thickness_mm is None:
            raise ValueError("Расход на мм требует толщину слоя")
        if self.bases is not None and len(set(self.bases)) != len(self.bases):
            raise ValueError("Основания слоя не повторяются")
        return self


def _bases_only_for_walls(
    floor: list[CadFinishLayer] | None, ceiling: list[CadFinishLayer] | None
) -> None:
    """Основание задаётся только слоям стен: пол и потолок от основания стен не зависят."""
    for layer in [*(floor or []), *(ceiling or [])]:
        if layer.bases is not None:
            raise ValueError("Основания задаются только слоям стен")


def _unique_room_types(value: list[CadRoomType]) -> list[CadRoomType]:
    if len(set(value)) != len(value):
        raise ValueError("Типы помещений в шаблоне не повторяются")
    return value


class CadFinishTemplateWrite(BaseModel):
    """Новый шаблон отделки проекта."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=TEXT_MAX)
    room_types: list[CadRoomType] = Field(default_factory=list, max_length=len(ROOM_TYPE_VALUES))
    wall_height_mm: int | None = Field(default=None, ge=WALL_HEIGHT_MIN_MM, le=WALL_HEIGHT_MAX_MM)
    walls_include_reveals: bool = Field(
        default=False,
        description="Откосы дверных проёмов входят в площадь слоёв стен (ADR-0042, п. 6)",
    )
    floor_layers: list[CadFinishLayer] = Field(default_factory=list, max_length=MAX_LAYERS)
    wall_layers: list[CadFinishLayer] = Field(default_factory=list, max_length=MAX_LAYERS)
    ceiling_layers: list[CadFinishLayer] = Field(default_factory=list, max_length=MAX_LAYERS)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("room_types")
    @classmethod
    def _room_types_unique(cls, value: list[CadRoomType]) -> list[CadRoomType]:
        return _unique_room_types(value)

    @model_validator(mode="after")
    def _bases_wall_layers_only(self) -> CadFinishTemplateWrite:
        _bases_only_for_walls(self.floor_layers, self.ceiling_layers)
        return self


class CadFinishTemplatePatch(BaseModel):
    """Частичная правка шаблона: переданное заменяет хранимое; явный null у высоты очищает её."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=TEXT_MAX)
    room_types: list[CadRoomType] | None = Field(default=None, max_length=len(ROOM_TYPE_VALUES))
    wall_height_mm: int | None = Field(default=None, ge=WALL_HEIGHT_MIN_MM, le=WALL_HEIGHT_MAX_MM)
    walls_include_reveals: bool | None = Field(default=None)
    floor_layers: list[CadFinishLayer] | None = Field(default=None, max_length=MAX_LAYERS)
    wall_layers: list[CadFinishLayer] | None = Field(default=None, max_length=MAX_LAYERS)
    ceiling_layers: list[CadFinishLayer] | None = Field(default=None, max_length=MAX_LAYERS)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("room_types")
    @classmethod
    def _room_types_unique(cls, value: list[CadRoomType] | None) -> list[CadRoomType] | None:
        return None if value is None else _unique_room_types(value)

    @model_validator(mode="after")
    def _no_null_for_required(self) -> CadFinishTemplatePatch:
        # Очищается только высота стен; остальные поля обязательны, null вместо значения - ошибка.
        for field in (
            "name",
            "room_types",
            "walls_include_reveals",
            "floor_layers",
            "wall_layers",
            "ceiling_layers",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"Поле {field} не очищается")
        _bases_only_for_walls(self.floor_layers, self.ceiling_layers)
        return self


class CadFinishTemplateRead(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    room_types: list[CadRoomType]
    wall_height_mm: int | None
    walls_include_reveals: bool
    floor_layers: list[CadFinishLayer]
    wall_layers: list[CadFinishLayer]
    ceiling_layers: list[CadFinishLayer]
    created_at: datetime
    updated_at: datetime


class CadFinishAssign(BaseModel):
    """Массовое назначение шаблона зонам проекта; `null` снимает явное назначение."""

    model_config = ConfigDict(extra="forbid")

    zone_ids: list[UUID] = Field(min_length=1, max_length=MAX_ASSIGN_ZONES)
    template_id: UUID | None


class CadFinishAssignSkip(BaseModel):
    zone_id: UUID
    reason: FinishSkipReason


class CadFinishAssignResult(BaseModel):
    assigned: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    skipped: list[CadFinishAssignSkip]


# --------------------------------------------------------------------------- ведомость


class CadFinishLayerRead(BaseModel):
    """Слой отделки зоны с количеством; `null` - не определено (не 0)."""

    surface: FinishSurface
    work: str
    material: str | None
    coats: int
    thickness_mm: float | None
    # Основания слоя стен; null - все (у пола и потолка всегда null).
    bases: list[FinishWallBase] | None
    area_m2: float | None
    material_qty: float | None
    material_unit: str | None


class CadFinishAreaByBaseRead(BaseModel):
    """Площадь стен зоны по основаниям (м2, без надпроёмных частей и откосов); null - нет."""

    monolith: float | None
    masonry: float | None
    gkl: float | None


class CadFinishWallsBreakdownRead(BaseModel):
    """Привязка рёбер зоны к конструкциям листа (ADR-0042, п. 6).

    `linked=false` - привязки нет (нет конструкций, кадра листа или контур зоны непригоден), все
    остальные поля null. Длины (м) известны при `linked`; площади - ещё и при известной высоте
    стен. Окон в результате конструкций нет: наружные стены без вычета окон.
    """

    linked: bool
    monolith_m: float | None
    masonry_m: float | None
    gkl_m: float | None
    # Дверные проёмы с известной высотой двери и проёмы без двери (gap) или без высоты двери.
    door_m: float | None
    gap_m: float | None
    # Граница без стены: соседняя зона, линия разреза.
    open_m: float | None
    area_by_base: CadFinishAreaByBaseRead
    # Надпроёмные части над дверями: длина участка x (высота стен - высота двери).
    door_over_area_m2: float | None
    # Откосы дверей, смежных зоне: справочно, на половину толщины стены. В слои стен входят только
    # при `walls_include_reveals` шаблона; null - у проёма нет толщины стены.
    reveal_m: float | None
    reveal_area_m2: float | None


class CadFinishZoneRead(BaseModel):
    zone_id: UUID
    name: str | None
    apartment_no: str | None
    room_mark: str | None
    kind: CadZoneKind
    room_type: CadRoomType | None
    template_id: UUID | None
    template_source: FinishTemplateSource | None
    floor_area_m2: float | None
    ceiling_area_m2: float | None
    perimeter_m: float | None
    wall_height_mm: float | None
    wall_height_source: FinishWallHeightSource | None
    wall_area_m2: float | None
    walls_breakdown: CadFinishWallsBreakdownRead
    layers: list[CadFinishLayerRead]


class CadFinishTotalRead(BaseModel):
    surface: FinishSurface
    work: str
    material: str | None
    material_unit: str | None
    area_m2: float | None
    material_qty: float | None
    zone_count: int


class CadFinishRoomTypeRead(BaseModel):
    room_type: CadRoomType
    zone_count: int
    floor_area_m2: float | None
    wall_area_m2: float | None
    ceiling_area_m2: float | None


class CadFinishWarningRead(BaseModel):
    code: FinishWarningCode
    zone_ids: list[UUID]


class CadFinishSheetRead(BaseModel):
    """Ведомость отделки листа: зоны, итоги по работам, итоги по типам помещений, предупреждения."""

    revision_id: UUID
    page_index: int
    zones: list[CadFinishZoneRead]
    totals: list[CadFinishTotalRead]
    by_room_type: list[CadFinishRoomTypeRead]
    warnings: list[CadFinishWarningRead]
