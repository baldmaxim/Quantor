"""Контракты паспорта листа (ADR-0043, этап С1)."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.consistency.dictionaries import SECTION_MARKS, SheetKind

BULK_MAX: Final = 1000
LIST_MAX: Final = 1000
TEXT_MAX: Final = 500
STAGES: Final = ("П", "РД")
ORDINAL_MIN: Final = -50
ORDINAL_MAX: Final = 300
ELEVATION_ABS_MAX_M: Final = 1000.0
# Поля паспорта, которые правит человек (и которые разбор пишет кандидатом).
TEXT_FIELDS: Final = (
    "section_mark",
    "sheet_kind",
    "stage",
    "building",
    "section",
    "level_from",
    "level_to",
    "code",
    "sheet_number",
    "title",
)
INT_FIELDS: Final = ("level_from_ordinal", "level_to_ordinal")
PASSPORT_FIELDS: Final = (*TEXT_FIELDS, *INT_FIELDS, "elevation_m")
_SECTION_MARKS: Final = frozenset(item.mark for item in SECTION_MARKS)
_SHEET_KINDS: Final = frozenset(kind.value for kind in SheetKind)


class SheetPassportStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class FieldEvidenceOut(BaseModel):
    source: str
    snippet: str


class SheetPassportOut(BaseModel):
    id: UUID
    project_id: UUID
    revision_id: UUID
    document_id: UUID
    document_name: str
    page_index: int
    file_name: str
    section_mark: str | None
    sheet_kind: str | None
    stage: str | None
    building: str | None
    section: str | None
    level_from: str | None
    level_to: str | None
    level_from_ordinal: int | None
    level_to_ordinal: int | None
    elevation_m: float | None
    code: str | None
    sheet_number: str | None
    title: str | None
    status: SheetPassportStatus
    evidence: dict[str, FieldEvidenceOut]
    versions: dict[str, str]
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SheetPassportListOut(BaseModel):
    items: list[SheetPassportOut]
    total: int


class SheetPassportPatch(BaseModel):
    """Частичная правка: переданное поле меняется (в том числе на null), остальные - нет."""

    model_config = ConfigDict(extra="forbid")

    section_mark: str | None = None
    sheet_kind: str | None = None
    stage: str | None = None
    building: str | None = Field(default=None, max_length=TEXT_MAX)
    section: str | None = Field(default=None, max_length=TEXT_MAX)
    level_from: str | None = Field(default=None, max_length=TEXT_MAX)
    level_to: str | None = Field(default=None, max_length=TEXT_MAX)
    level_from_ordinal: int | None = Field(default=None, ge=ORDINAL_MIN, le=ORDINAL_MAX)
    level_to_ordinal: int | None = Field(default=None, ge=ORDINAL_MIN, le=ORDINAL_MAX)
    elevation_m: float | None = Field(default=None, ge=-ELEVATION_ABS_MAX_M, le=ELEVATION_ABS_MAX_M)
    code: str | None = Field(default=None, max_length=TEXT_MAX)
    sheet_number: str | None = Field(default=None, max_length=TEXT_MAX)
    title: str | None = Field(default=None, max_length=TEXT_MAX)
    status: SheetPassportStatus | None = None

    @field_validator(*TEXT_FIELDS, mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Пустая строка поля формы - то же, что «не задано»."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("section_mark")
    @classmethod
    def _known_section_mark(cls, value: str | None) -> str | None:
        if value is not None and value not in _SECTION_MARKS:
            raise ValueError("марки раздела нет в словаре")
        return value

    @field_validator("sheet_kind")
    @classmethod
    def _known_sheet_kind(cls, value: str | None) -> str | None:
        if value is not None and value not in _SHEET_KINDS:
            raise ValueError("типа листа нет в словаре")
        return value

    @field_validator("stage")
    @classmethod
    def _known_stage(cls, value: str | None) -> str | None:
        if value is not None and value not in STAGES:
            raise ValueError("стадия - «П» или «РД»")
        return value

    @field_validator("elevation_m")
    @classmethod
    def _finite_elevation(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("отметка должна быть конечным числом")
        return value

    @model_validator(mode="after")
    def _not_empty(self) -> SheetPassportPatch:
        if not self.model_fields_set:
            raise ValueError("в запросе нет ни одного поля")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("статус нельзя сбросить в null")
        return self


class SheetPassportBulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1, max_length=BULK_MAX)
    status: SheetPassportStatus


class SheetPassportBulkOut(BaseModel):
    updated: int


class SheetPassportExtractError(BaseModel):
    file_name: str
    error: str


class SheetPassportExtractSummary(BaseModel):
    """Итог последнего задания разбора листов; числа, которых нет в итоге задания, - null."""

    job_id: UUID
    status: str
    progress: float | None
    stage: str | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    files_total: int | None
    files_parsed: int | None
    pages: int | None
    created: int | None
    updated: int | None
    skipped_reviewed: int | None
    error_count: int | None
    errors: list[SheetPassportExtractError]
    versions: dict[str, str]
