"""Контракты API модели здания (ADR-0053): версии, этажи, элементы, части пакета."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain import JobStatus, ModelVersionStatus
from app.models import Job

MAX_ELEMENTS_PAGE = 500
MAX_COMMENT = 500


class ModelIssueRead(BaseModel):
    code: str
    where: str
    message: str


class ModelStoreyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    storey_key: str
    name: str
    elevation_mm: float
    height_mm: float | None = None
    bbox_mm: list[float] | None = None
    element_count: int = 0
    # Здание этажа: только в моделях с несколькими зданиями (QMP v1, раздел 4).
    building_key: str | None = None
    building_name: str | None = None


class ModelVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    tender_version_id: uuid.UUID | None = None
    number: int
    status: ModelVersionStatus
    source_kind: str
    manifest_sha256: str
    generator: str | None = None
    counts: dict[str, Any] = Field(default_factory=dict)
    warnings: list[ModelIssueRead] = Field(default_factory=list)
    comment: str | None = None
    created_at: datetime
    committed_at: datetime | None = None
    approved_at: datetime | None = None


class ModelVersionStarted(ModelVersionRead):
    """Ответ на начало выгрузки: что ещё надо загрузить (повторная выгрузка возобновляется)."""

    created: bool
    missing_parts: list[str] = Field(default_factory=list)


class ModelPartRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    path: str
    kind: str
    storey_key: str | None = None
    discipline: str | None = None
    size_bytes: int
    sha256: str


class ModelVersionDetail(ModelVersionRead):
    storeys: list[ModelStoreyRead] = Field(default_factory=list)
    parts: list[ModelPartRead] = Field(default_factory=list)


class ModelVersionList(BaseModel):
    items: list[ModelVersionRead]


class ModelApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: Annotated[str, Field(max_length=MAX_COMMENT)] | None = None


class ModelElementRead(BaseModel):
    id: str
    category: str
    ifc_class: str | None = None
    name: str | None = None
    type: str | None = None
    discipline: str
    bbox_mm: list[float] | None = None
    part: str | None = None
    props: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ModelElementsPage(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[ModelElementRead]


class ModelImportCreate(BaseModel):
    """Постановка импорта: выбранные ревизии IFC; пусто - последние ревизии всех IFC проекта."""

    model_config = ConfigDict(extra="forbid")

    revision_ids: Annotated[list[uuid.UUID], Field(max_length=40)] | None = None


class ModelImportRead(BaseModel):
    """Состояние задания «Модель из IFC»; `version_id` - версия модели, когда задание готово."""

    job_id: uuid.UUID
    status: JobStatus
    stage: str | None
    progress: float | None
    error_code: str | None
    error_message: str | None
    generator_version: str | None
    inputs: int
    version_id: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, job: Job) -> ModelImportRead:
        result = job.payload.get("model_result")
        version = result.get("version_id") if isinstance(result, dict) else None
        generator = job.payload.get("generator_version")
        inputs = job.payload.get("inputs")
        return cls(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            error_code=job.error_code,
            error_message=job.error_message,
            generator_version=generator if isinstance(generator, str) else None,
            inputs=len(inputs) if isinstance(inputs, list) else 0,
            version_id=uuid.UUID(version) if isinstance(version, str) else None,
            created_at=job.created_at,
            finished_at=job.finished_at,
        )
