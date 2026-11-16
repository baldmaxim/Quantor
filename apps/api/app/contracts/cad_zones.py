"""Контракты зон листа во вкладке CAD: помещения квартир, помещения МОП, двери, машино-места."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_room_types import CadRoomType, CadRoomTypeSource
from app.domain import MAX_MEASUREMENT_POINTS

CadZoneKind = Literal["room_apartment", "room_mop", "door", "parking_space"]
CadParkingType = Literal[
    "permanent",
    "temporary",
    "guest",
    "medium",
    "medium_guest",
    "large",
    "large_guest",
    "mgn_m1_3",
    "mgn_m4",
    "unknown",
]

# Происхождение зоны: `unknown` - строка до миграции 0041, ведёт себя как `human`.
CadZoneSource = Literal["auto", "human", "unknown"]
# Итог сверки с экспликацией; `failed` не участвует в плите, перегородках и отделке до принятия.
CadZoneQualityStatus = Literal["ok", "review", "failed"]
# Что удалять массово: только авто-зоны листа или все зоны листа.
CadZonesDeleteScope = Literal["auto", "all"]

MAX_TEXT = 200
ZonePoint = tuple[float, float]


class CadZoneCreate(BaseModel):
    """Новая зона. Вид-зависимые поля и топологию проверяет сервис."""

    model_config = ConfigDict(extra="forbid")

    revision_id: UUID
    page_index: int = Field(ge=0)
    kind: CadZoneKind
    apartment_no: str | None = Field(default=None, max_length=MAX_TEXT)
    room_mark: str | None = Field(default=None, max_length=MAX_TEXT)
    name: str | None = Field(default=None, max_length=MAX_TEXT)
    points: list[ZonePoint] = Field(min_length=2, max_length=MAX_MEASUREMENT_POINTS)
    door_height_mm: int | None = None
    parking_type: CadParkingType | None = None
    # Тип помещения (ADR-0042): не передан - сервер выводит из названия; у двери и места - нет.
    room_type: CadRoomType | None = None
    finish_template_id: UUID | None = None


class CadZoneUpdate(BaseModel):
    """Частичная правка: переданные поля заменяют хранимые, итог проверяется целиком."""

    model_config = ConfigDict(extra="forbid")

    kind: CadZoneKind | None = None
    apartment_no: str | None = Field(default=None, max_length=MAX_TEXT)
    room_mark: str | None = Field(default=None, max_length=MAX_TEXT)
    name: str | None = Field(default=None, max_length=MAX_TEXT)
    points: list[ZonePoint] | None = Field(
        default=None, min_length=2, max_length=MAX_MEASUREMENT_POINTS
    )
    door_height_mm: int | None = None
    parking_type: CadParkingType | None = None
    # Явный null очищает: тип снова выводится из названия, назначение шаблона снимается.
    room_type: CadRoomType | None = None
    finish_template_id: UUID | None = None


class CadZoneRead(BaseModel):
    id: UUID
    revision_id: UUID
    page_index: int
    kind: CadZoneKind
    apartment_no: str | None
    room_mark: str | None
    name: str | None
    points: list[ZonePoint]
    door_height_mm: int | None
    parking_type: CadParkingType | None
    # Действующий тип помещения: заданный человеком или выведенный из названия (ADR-0042).
    # У двери и машино-места - null, как и источник.
    room_type: CadRoomType | None
    room_type_source: CadRoomTypeSource | None
    finish_template_id: UUID | None
    # Площадь и периметр помещения, ширина двери: сервер, по геометрии страницы и действующей
    # калибровке листа. `null` — не определено (не 0): причина в `calibration_missing`
    # или `geometry_issue`.
    area_m2: float | None
    perimeter_m: float | None
    width_m: float | None
    calibration_missing: bool
    geometry_issue: str | None
    # Происхождение и сверка с экспликацией (ревью движка 2026-11-16).
    source: CadZoneSource
    generator_version: str | None
    # Площадь по экспликации листа из zones.json; `null` - экспликации нет.
    expl_area_m2: float | None
    # Заметки генератора о зоне.
    notes: list[str]
    quality_status: CadZoneQualityStatus
    quality_reason: str | None
    quality_accepted_by: UUID | None
    quality_accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CadZoneUnmatchedMarkRead(BaseModel):
    """Марка экспликации без зоны: из итога последнего задания разметки листа."""

    room_mark: str
    name: str | None
    expl_area_m2: float | None
    reason: str | None


class CadZonesSheetSummaryRead(BaseModel):
    """Сводка сверки зон листа с экспликацией."""

    revision_id: UUID
    page_index: int
    # Зоны-помещения (квартиры и МОП) по итогу сверки.
    ok: int
    review: int
    failed: int
    # Все зоны листа по происхождению.
    auto: int
    human: int
    unknown: int
    # Версии генератора авто-зон листа (обычно одна).
    generator_versions: list[str]
    # Комнаты квартир, у которых есть и площадь контура, и экспликация: сумма против экспликации.
    apartments_compared: int
    apartments_area_m2: float | None
    apartments_expl_area_m2: float | None
    apartments_delta_percent: float | None
    unmatched_marks: list[CadZoneUnmatchedMarkRead]
    # Все зоны листа - авто: ручной запуск разметки удалит их и создаст заново.
    recreate_allowed: bool


class CadZonesDeleteRead(BaseModel):
    deleted: int
