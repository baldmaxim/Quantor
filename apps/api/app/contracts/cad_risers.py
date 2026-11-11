"""Контракты реестра стояков листа CAD (ADR-0041, схема файла `cad_risers.v1`)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RISERS_SCHEMA: Final = "cad_risers.v1"
MAX_RISERS: Final = 40
MARK_MAX: Final = 32
TEXT_MAX: Final = 200
DN_MIN_MM: Final = 10
DN_MAX_MM: Final = 400
COUNT_MAX: Final = 8
SHAFT_ID_PATTERN: Final = r"^S\d{2,3}$"


class RiserSystem(StrEnum):
    """Система стояка. Отопление и К1 в реестр v1 не входят: генерируются как в cad_mep.v5."""

    V1 = "V1"
    T3 = "T3"
    T4 = "T4"
    VPV = "VPV"
    AUP = "AUP"
    FS = "FS"


class RiserRole(StrEnum):
    OWN = "own"
    TRANSIT = "transit"


class CadRiserEntry(BaseModel):
    """Одна запись реестра; поля - как в файле `risers.json`, который читает генератор."""

    model_config = ConfigDict(extra="forbid")

    system: RiserSystem
    mark: str = Field(min_length=1, max_length=MARK_MAX)
    dn_mm: int | None = Field(default=None, ge=DN_MIN_MM, le=DN_MAX_MM)
    role: RiserRole
    count: int = Field(default=1, ge=1, le=COUNT_MAX)
    shaft_id: str | None = Field(default=None, pattern=SHAFT_ID_PATTERN)
    source: str | None = Field(default=None, max_length=TEXT_MAX)
    note: str | None = Field(default=None, max_length=TEXT_MAX)

    @field_validator("mark", mode="before")
    @classmethod
    def _strip_mark(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("shaft_id", "source", "note", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Пустая строка поля формы - то же, что «не задано»."""
        if isinstance(value, str):
            return value.strip() or None
        return value


class CadSheetRisersPut(BaseModel):
    """Реестр листа заменяется целиком; пустой список = реестра нет."""

    model_config = ConfigDict(extra="forbid")

    risers: list[CadRiserEntry] = Field(max_length=MAX_RISERS)


class CadSheetRisersOut(BaseModel):
    revision_id: UUID
    page_index: int
    view: int
    risers: list[CadRiserEntry]
    # `null` - реестр не вводился.
    updated_at: datetime | None
