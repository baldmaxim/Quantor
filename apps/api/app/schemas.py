"""Схемы API v1.

Единственный источник контракта: из них генерируется OpenAPI, а из него — TypeScript-клиент.
Руками DTO на фронтенде не дублируются (ADR-0001).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import (
    ArtifactKind,
    DocumentKind,
    JobStatus,
    JobType,
    ProcessingStatus,
    ProjectSource,
    ProjectStatus,
    RegionShape,
)

if TYPE_CHECKING:
    from app.services.uploads import UploadOutcome

# Пагинация обязательна: на одном листе бывают сотни областей, во всём документе — тысячи.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


class Page[ItemT](BaseModel):
    """Страница списка. total нужен интерфейсу, чтобы показать общее количество."""

    items: list[ItemT]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class ApiModel(BaseModel):
    """База для схем, читаемых прямо из моделей SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- проекты


class ProjectNameMixin(BaseModel):
    """Имя проекта обрезается до проверки длины.

    Иначе строка из одних пробелов проходит min_length и превращается в пустое имя
    уже после сохранения.
    """

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def _strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProjectCreate(ProjectNameMixin):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class ProjectUpdate(ProjectNameMixin):
    name: Annotated[str | None, Field(default=None, min_length=1, max_length=200)] = None
    status: ProjectStatus | None = None


class ProjectRead(ApiModel):
    id: uuid.UUID
    name: str
    status: ProjectStatus
    source: ProjectSource
    """Откуда взялся проект: заведён руками или подтянут из внешней системы."""
    external_ref: str | None
    """Человекочитаемая ссылка на источник — номер тендера. Идентификатор наружу не нужен."""
    created_at: datetime
    updated_at: datetime


class ProjectJobSummary(ApiModel):
    """Состояние последнего задания проекта.

    Компактнее полного JobRead: список проектов не должен тащить служебные поля,
    которые в нём всё равно не показать.
    """

    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    progress: float | None
    stage: str | None
    error_code: str | None
    finished_at: datetime | None


class ProjectSummary(ProjectRead):
    """Проект вместе с производными счётчиками — то, что нужно списку и карточке.

    Последнее задание отдаётся здесь же: иначе, чтобы увидеть ход импорта, пришлось бы
    открывать каждый проект по очереди.
    """

    document_count: int = Field(ge=0)
    sheet_count: int = Field(ge=0)
    last_job: ProjectJobSummary | None = None


# --------------------------------------------------------------------------- документы


class DocumentRead(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID
    display_name: str
    discipline: str | None
    document_kind: DocumentKind
    created_at: datetime
    updated_at: datetime


class DocumentRevisionRead(ApiModel):
    id: uuid.UUID
    document_id: uuid.UUID
    revision_label: str | None
    source_filename: str
    source_mime: str
    source_size: int
    source_sha256: str
    processing_status: ProcessingStatus
    processing_error_code: str | None
    source_metadata: dict[str, Any]
    created_at: datetime


class RecognitionArtifactRead(ApiModel):
    id: uuid.UUID
    revision_id: uuid.UUID
    artifact_kind: ArtifactKind
    schema_version: int | None
    sha256: str
    source_filename: str
    metadata: dict[str, Any] = Field(validation_alias="artifact_metadata")
    created_at: datetime


class ContentUrl(BaseModel):
    """Ссылка на файл ревизии прямо из хранилища.

    API не проксирует бинарные данные: документ на 50–500 МБ не должен проходить через
    процесс приложения (ADR-0002).
    """

    url: str
    expires_in: int = Field(gt=0)
    filename: str
    content_type: str


# --------------------------------------------------------------------------- листы и области


class SheetRead(ApiModel):
    id: uuid.UUID
    revision_id: uuid.UUID
    page_index: int
    page_label: str | None
    width_px: int | None
    height_px: int | None
    rotation: int
    region_count: int = Field(ge=0)


class RegionRead(ApiModel):
    """Область распознавания.

    coords_norm — [x0, y0, x1, y1] от левого верхнего угла листа, значения в [0, 1].
    Перевод в экранные координаты выполняет клиент при отрисовке (ADR-0008).
    """

    id: uuid.UUID
    sheet_id: uuid.UUID
    external_block_id: str
    ordinal: int | None
    block_type: str
    shape_type: RegionShape
    coords_norm: list[float]
    polygon_points: list[list[float]] | None
    recognition_status: str | None
    raw_content_md: str | None
    legacy_metadata: dict[str, Any]


# --------------------------------------------------------------------------- загрузка


class UploadedFileType(ApiModel):
    """Что портал умеет делать с файлом такого расширения."""

    extension: str
    document_kind: DocumentKind
    capability: str
    schedules_import: bool
    max_size_bytes: int = Field(gt=0)


class UploadRead(BaseModel):
    """Результат загрузки.

    is_duplicate означает, что такой файл в проекте уже был: возвращается прежняя ревизия,
    вторая копия не создаётся.
    """

    document: DocumentRead
    revision: DocumentRevisionRead
    job: JobRead | None
    is_duplicate: bool

    @classmethod
    def from_outcome(cls, outcome: UploadOutcome) -> UploadRead:
        return cls(
            document=DocumentRead.model_validate(outcome.document),
            revision=DocumentRevisionRead.model_validate(outcome.revision),
            job=JobRead.model_validate(outcome.job) if outcome.job else None,
            is_duplicate=outcome.is_duplicate,
        )


# --------------------------------------------------------------------------- задания


class JobRead(ApiModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    job_type: JobType
    status: JobStatus
    progress: float | None
    stage: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TenderBriefRead(BaseModel):
    """Тендер TenderHUB в том виде, в каком его показывает портал.

    Сметные строки и суммы сюда не входят: портал на Stage 1 не ведёт расчёт, и
    показывать чужие деньги как свой результат нельзя (границы этапа в CLAUDE.md).
    """

    id: str
    tender_number: str | None
    title: str
    client_name: str | None
    version: int | None
    construction_scope: str | None
    submission_deadline: str | None
    updated_at: str | None
    imported_project_id: uuid.UUID | None
    """Проект портала, уже созданный по этому тендеру. None — тендер ещё не подключён."""


class TenderImport(BaseModel):
    """Запрос на создание проекта по тендеру."""

    tender_id: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str | None, Field(default=None, max_length=200)] = None
    """Имя проекта. Пусто — берётся из тендера."""
