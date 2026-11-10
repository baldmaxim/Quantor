"""Контракты зон листа во вкладке CAD: помещения квартир, помещения МОП, двери."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain import MAX_MEASUREMENT_POINTS

CadZoneKind = Literal["room_apartment", "room_mop", "door"]

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
    # Площадь и периметр помещения, ширина двери: сервер, по геометрии страницы и действующей
    # калибровке листа. `null` — не определено (не 0): причина в `calibration_missing`
    # или `geometry_issue`.
    area_m2: float | None
    perimeter_m: float | None
    width_m: float | None
    calibration_missing: bool
    geometry_issue: str | None
    created_at: datetime
    updated_at: datetime
