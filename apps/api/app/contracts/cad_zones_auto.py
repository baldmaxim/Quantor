"""Контракты автоматической разметки зон (`cad_zones`): файл генератора и ответ ручного запуска."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.cad_zones import ZonePoint
from app.domain import MAX_MEASUREMENT_POINTS, JobStatus


class ZonesFileZone(BaseModel):
    """Зона из `zones.json` генератора: кандидат, поля сверх контракта сервер не читает."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["room_apartment"]
    apartment_no: str = Field(min_length=1)
    room_mark: str | None = None
    name: str | None = None
    points: list[ZonePoint] = Field(min_length=3, max_length=MAX_MEASUREMENT_POINTS)


class ZonesFile(BaseModel):
    """`zones.json` схемы `quantor.cad_mep.zones.v1`."""

    model_config = ConfigDict(extra="ignore")

    schema_name: str = Field(alias="schema")
    page_index: int
    zones: list[ZonesFileZone]


class CadZonesJobRead(BaseModel):
    """Задание `cad_zones`, поставленное на автоматическую разметку вида."""

    job_id: UUID
    parent_job_id: UUID
    page_index: int
    view: int
    status: JobStatus
    attempt: int
    created_at: datetime
