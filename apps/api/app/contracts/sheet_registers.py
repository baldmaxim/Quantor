"""Контракты ведомостей листов (ADR-0043, С2, подэтап «ведомость ↔ листы»)."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.services.consistency.sheet_register import RegisterStatus

BULK_MAX: Final = 2000


class RegisterEntryOut(BaseModel):
    number: str
    title: str
    snippet: str
    page_index: int


class SheetRegisterOut(BaseModel):
    id: UUID
    revision_id: UUID
    file_name: str
    page_index: int
    pages: list[int]
    heading: str
    entries: list[RegisterEntryOut]
    # Номера, встреченные в самой ведомости больше одного раза.
    duplicates: list[str]
    status: RegisterStatus
    confirmed_at: datetime | None


class RegisterExtractSummary(BaseModel):
    """Итог последнего задания разбора ведомостей; чисел, которых нет в итоге, - null."""

    job_id: UUID
    status: str
    progress: float | None
    stage: str | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    registers: int | None
    revisions_total: int | None
    revisions_scanned: int | None
    revisions_no_text: int | None
    no_text_files: list[str]
    revisions_unreadable: int | None
    unreadable_files: list[str]
    versions: dict[str, str]


class SheetRegistersOut(BaseModel):
    """Ведомости последних ревизий PDF проекта и итог последнего разбора."""

    registers: list[SheetRegisterOut]
    last_extract: RegisterExtractSummary | None
    versions: dict[str, str]


class SheetRegisterBulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1, max_length=BULK_MAX)
    status: RegisterStatus


class SheetRegisterBulkOut(BaseModel):
    updated: int
