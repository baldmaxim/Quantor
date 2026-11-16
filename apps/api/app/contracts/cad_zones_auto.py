"""Контракты автоматической разметки зон (`cad_zones`): файл генератора и ответ ручного запуска."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.cad_zones import CadParkingType, ZonePoint
from app.domain import MAX_MEASUREMENT_POINTS, JobStatus

# Подписи типов по легенде листа: имя места, если генератор не передал подпись.
PARKING_TYPE_LABELS: dict[str, str] = {
    "permanent": "Постоянное хранение",
    "temporary": "Временное хранение",
    "guest": "Гостевое",
    "medium": "Medium",
    "medium_guest": "Medium гостевое",
    "large": "Large",
    "large_guest": "Large гостевое",
    "mgn_m1_3": "МГН М1–3",
    "mgn_m4": "МГН М4",
    "unknown": "Тип не определён",
}

# Предел числа заметок зоны и марок без зоны, которые сервер сохраняет из zones.json.
MAX_ZONE_NOTES = 20
MAX_UNMATCHED_MARKS = 300
_MAX_NOTE = 300


def _area_or_none(value: object) -> float | None:
    """Площадь из файла: конечное положительное число, иначе - «нет данных» (не отказ)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number > 0 and number < float("inf") else None


def _text_or_none(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


class ZonesFileZone(BaseModel):
    """Зона из `zones.json` генератора: кандидат, поля сверх контракта сервер не читает.

    У `room_apartment` № квартиры обязателен, у `room_mop` его нет (проверяется валидатором).
    Площади и заметки - необязательные данные сверки: неверный тип читается как «нет данных».
    """

    model_config = ConfigDict(extra="ignore")

    kind: Literal["room_apartment", "room_mop"]
    apartment_no: str | None = Field(default=None, min_length=1)
    room_mark: str | None = None
    name: str | None = None
    points: list[ZonePoint] = Field(min_length=3, max_length=MAX_MEASUREMENT_POINTS)
    # Площадь по экспликации листа и площадь контура по масштабу преобразования, м2.
    expl_area_m2: float | None = None
    poly_area_m2: float | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("expl_area_m2", "poly_area_m2", mode="before")
    @classmethod
    def _area(cls, value: object) -> float | None:
        return _area_or_none(value)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        notes = [text for text in (_text_or_none(item, _MAX_NOTE) for item in value) if text]
        return notes[:MAX_ZONE_NOTES]

    @model_validator(mode="after")
    def _apartment_by_kind(self) -> ZonesFileZone:
        if self.kind == "room_apartment" and self.apartment_no is None:
            raise ValueError("room_apartment: apartment_no обязателен")
        return self


class ZonesFileParkingSpace(BaseModel):
    """Машино-место из `zones.json`: кандидат; размеры и площадь генератора сервер не читает."""

    model_config = ConfigDict(extra="ignore")

    parking_type: CadParkingType
    label: str | None = None
    points: list[ZonePoint] = Field(min_length=3, max_length=MAX_MEASUREMENT_POINTS)


class ZonesFileUnmatchedMark(BaseModel):
    """Марка экспликации, для которой генератор не построил зону."""

    model_config = ConfigDict(extra="ignore")

    room_mark: str
    name: str | None = None
    expl_area_m2: float | None = None
    reason: str | None = None

    @field_validator("expl_area_m2", mode="before")
    @classmethod
    def _area(cls, value: object) -> float | None:
        return _area_or_none(value)

    @field_validator("name", "reason", mode="before")
    @classmethod
    def _text(cls, value: object) -> str | None:
        return _text_or_none(value, _MAX_NOTE)


class ZonesFile(BaseModel):
    """`zones.json` схемы `quantor.cad_mep.zones.v1`."""

    model_config = ConfigDict(extra="ignore")

    schema_name: str = Field(alias="schema")
    page_index: int
    zones: list[ZonesFileZone]
    parking_spaces: list[ZonesFileParkingSpace] = Field(default_factory=list)
    unmatched_marks: list[ZonesFileUnmatchedMark] = Field(default_factory=list)

    @field_validator("unmatched_marks", mode="before")
    @classmethod
    def _unmatched(cls, value: object) -> list[object]:
        """Марки без зоны - данные сверки: запись вне контракта пропускается без отказа."""
        if not isinstance(value, list):
            return []
        rows: list[object] = [
            row
            for row in value
            if isinstance(row, dict) and isinstance(row.get("room_mark"), str) and row["room_mark"]
        ]
        return rows[:MAX_UNMATCHED_MARKS]


class CadZonesJobRead(BaseModel):
    """Задание `cad_zones`, поставленное на автоматическую разметку вида."""

    job_id: UUID
    parent_job_id: UUID
    page_index: int
    view: int
    status: JobStatus
    attempt: int
    created_at: datetime
