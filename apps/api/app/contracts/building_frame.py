"""Контракты каркаса здания и проверок комплектности (ADR-0043, этап С2)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.consistency.building_frame import NodeKind, NodeOrigin, NodeStatus
from app.services.consistency.frame_checks import CheckCode, CheckStatus, RefKind

BULK_MAX: Final = 2000
TEXT_MAX: Final = 200
ORDINAL_MIN: Final = -50
ORDINAL_MAX: Final = 300
ELEVATION_ABS_MAX_M: Final = 1000.0
HEIGHT_MAX_M: Final = 30.0


class FramePassportRef(BaseModel):
    id: str
    file_name: str
    page_index: int
    section_mark: str | None


class FrameElevationSource(BaseModel):
    value_m: float
    passport_id: str
    file_name: str
    page_index: int


class FrameNodeOut(BaseModel):
    id: UUID
    kind: NodeKind
    parent_id: UUID | None
    building: str | None
    section: str | None
    code: str | None
    ordinal: int | None
    elevation_m: float | None
    # Высота «пол - пол», введённая человеком, и выведенная из отметок соседнего уровня.
    height_m: float | None
    height_derived_m: float | None
    status: NodeStatus
    origin: NodeOrigin
    passport_count: int
    passports: list[FramePassportRef]
    elevation_sources: list[FrameElevationSource]
    # Разные отметки источников; больше одной - отметку выбирает человек.
    elevation_values: list[float]
    manual_fields: list[str]
    confirmed_at: datetime | None


class FrameCheckRefOut(BaseModel):
    kind: RefKind
    id: str
    label: str
    file_name: str | None
    page_index: int | None


class FrameCheckOut(BaseModel):
    code: CheckCode
    title: str
    status: CheckStatus
    message: str
    building: str | None
    section: str | None
    level: str | None
    refs: list[FrameCheckRefOut]


class FrameOut(BaseModel):
    """Каркас проекта, проверки по подтверждённым данным и счётчики входов."""

    nodes: list[FrameNodeOut]
    checks: list[FrameCheckOut]
    # Подтверждённые паспорта планов - вход сборки; планы-кандидаты в каркас не идут.
    confirmed_plans: int
    candidate_plans: int
    versions: dict[str, str]


class FrameRebuildOut(BaseModel):
    created: int
    updated: int
    removed: int
    kept_reviewed: int


def _clean_text(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError("значение должно быть конечным числом")
    return value


class FrameNodeCreate(BaseModel):
    """Узел, добавленный человеком. Недостающие корпус и секция создаются кандидатами-ручными."""

    model_config = ConfigDict(extra="forbid")

    kind: NodeKind
    building: str | None = Field(default=None, max_length=TEXT_MAX)
    section: str | None = Field(default=None, max_length=TEXT_MAX)
    code: str | None = Field(default=None, max_length=TEXT_MAX)
    ordinal: int | None = Field(default=None, ge=ORDINAL_MIN, le=ORDINAL_MAX)
    elevation_m: float | None = Field(default=None, ge=-ELEVATION_ABS_MAX_M, le=ELEVATION_ABS_MAX_M)
    height_m: float | None = Field(default=None, gt=0, le=HEIGHT_MAX_M)

    @field_validator("building", "section", "code", mode="before")
    @classmethod
    def _texts(cls, value: object) -> object:
        """Пустая строка поля формы - то же, что «не указано»."""
        return _clean_text(value)

    @field_validator("elevation_m", "height_m")
    @classmethod
    def _numbers(cls, value: float | None) -> float | None:
        return _finite(value)

    @model_validator(mode="after")
    def _fields_match_kind(self) -> FrameNodeCreate:
        if self.kind is NodeKind.LEVEL:
            if self.code is None:
                raise ValueError("у уровня нужен код, например «3 этаж» или «кровля»")
            return self
        if self.code is not None or self.ordinal is not None:
            raise ValueError("код и номер бывают только у уровня")
        if self.elevation_m is not None or self.height_m is not None:
            raise ValueError("отметка и высота бывают только у уровня")
        if self.kind is NodeKind.BUILDING and self.section is not None:
            raise ValueError("у корпуса нет секции")
        return self


class FrameNodePatch(BaseModel):
    """Правка уровня и/или статуса узла; переданное поле меняется (в том числе на null)."""

    model_config = ConfigDict(extra="forbid")

    ordinal: int | None = Field(default=None, ge=ORDINAL_MIN, le=ORDINAL_MAX)
    elevation_m: float | None = Field(default=None, ge=-ELEVATION_ABS_MAX_M, le=ELEVATION_ABS_MAX_M)
    height_m: float | None = Field(default=None, gt=0, le=HEIGHT_MAX_M)
    status: NodeStatus | None = None

    @field_validator("elevation_m", "height_m")
    @classmethod
    def _numbers(cls, value: float | None) -> float | None:
        return _finite(value)

    @model_validator(mode="after")
    def _not_empty(self) -> FrameNodePatch:
        if not self.model_fields_set:
            raise ValueError("в запросе нет ни одного поля")
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("статус нельзя сбросить в null")
        return self


class FrameBulkStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(min_length=1, max_length=BULK_MAX)
    status: NodeStatus


class FrameBulkOut(BaseModel):
    updated: int
