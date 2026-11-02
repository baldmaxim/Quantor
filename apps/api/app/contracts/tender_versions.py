"""Контракты версии тендера (ADR-0035, этап M2).

Версия тендера — замороженный комплект ревизий документов проекта. Контракты не знают ни о
разборе планов, ни о модели здания, ни о Revit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import TenderVersionStatus

SECTION_MAX_LENGTH = 16


def _blank_to_none(value: object) -> object:
    """Пустая строка и пробелы значат «не задано»: в базе хранится NULL, а не ''."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class TenderVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str | None, Field(default=None, max_length=200)] = None
    external_tender_id: Annotated[str | None, Field(default=None, max_length=128)] = None
    """Идентификатор строки HUBTender. Сервер сверяет её номер с номером проекта."""

    _normalize = field_validator("label", "external_tender_id", mode="before")(_blank_to_none)


class TenderVersionUpdate(BaseModel):
    """Частичное изменение черновика.

    Различается «поле не прислано» (не трогать) и «прислан null» (очистить): для
    `external_tender_id` это разница между «оставить связь» и «снять связь».
    """

    model_config = ConfigDict(extra="forbid")

    label: Annotated[str | None, Field(default=None, max_length=200)] = None
    external_tender_id: Annotated[str | None, Field(default=None, max_length=128)] = None

    _normalize = field_validator("label", "external_tender_id", mode="before")(_blank_to_none)


class TenderVersionDocumentPut(BaseModel):
    """Состав: какая ревизия документа входит в версию, в каком разделе и участвует ли в модели."""

    model_config = ConfigDict(extra="forbid")

    document_revision_id: UUID
    section: Annotated[str | None, Field(default=None, max_length=SECTION_MAX_LENGTH)] = None
    use_in_model: bool = True

    _normalize = field_validator("section", mode="before")(_blank_to_none)


class TenderVersionDocumentRead(BaseModel):
    document_id: UUID
    document_name: str
    document_revision_id: UUID
    revision_number: int = Field(ge=1)
    """Порядковый номер ревизии в документе: от старой к новой, с единицы."""
    source_sha256: str
    section: str | None
    use_in_model: bool


class TenderVersionSummaryRead(BaseModel):
    id: UUID
    project_id: UUID
    number: int
    label: str | None
    external_tender_id: str | None
    external_version: int | None
    status: TenderVersionStatus
    manifest_sha256: str | None
    """Отпечаток комплекта. Пусто, пока версия не заморожена."""
    frozen_at: datetime | None
    frozen_by: UUID | None
    created_at: datetime
    created_by: UUID | None
    document_count: int = Field(ge=0)


class TenderVersionRead(TenderVersionSummaryRead):
    tender_number: str | None
    """Номер тендера проекта (`external_ref`): часть отпечатка, у ручного проекта пуст."""
    documents: list[TenderVersionDocumentRead]


class TenderHubCandidateRead(BaseModel):
    """Строка HUBTender того же номера, с которой можно связать версию."""

    id: str
    version: int | None
    submission_deadline: str | None
