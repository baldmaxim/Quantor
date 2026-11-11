"""Контракт общего состояния конвейера CAD ревизии: по листу и виду, одним ответом."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain import JobStatus


class CadPipelineStageRead(BaseModel):
    """Последнее задание этапа: статус задания, ход и итог текущей попытки."""

    job_id: UUID
    job_type: str
    status: JobStatus
    progress: float | None
    stage: str | None
    # Итог текущей попытки (`result_status` результата); `null` - итога нет (идёт, отказ).
    result_status: str | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None


class CadPipelineViewRead(BaseModel):
    page: int
    view: int
    has_dxf: bool
    walls: CadPipelineStageRead | None
    zones: CadPipelineStageRead | None
    # Зоны хранятся по листу, а не по виду: одно и то же число у всех видов страницы.
    zones_count: int
    # Действующее одобрение вида (после проверки человеком).
    approved: bool
    routes: CadPipelineStageRead | None
    # Действующее принятие трасс по последнему заданию трасс вида.
    routes_accepted: bool
    floor3d: CadPipelineStageRead | None


class CadPipelineSheetRead(BaseModel):
    page_index: int
    page_label: str | None
    # Есть действующая калибровка листа.
    calibrated: bool
    # Последнее задание `cad_pdf_convert`, в котором есть этот лист.
    convert: CadPipelineStageRead | None
    views: list[CadPipelineViewRead]


class CadPipelineRead(BaseModel):
    revision_id: UUID
    server_time: datetime
    sheets: list[CadPipelineSheetRead]
