"""Контракты вопросов к документации (ADR-0043, шаг 2, этап В3)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

TEXT_MAX: Final = 500
NOTE_MAX: Final = 2000
VALUE_NUMBERS_MAX: Final = 8


class DocAnswerSource(StrEnum):
    DOCUMENT = "document"
    MANUAL = "manual"
    NORM_ASSUMPTION = "norm_assumption"
    NOT_IN_PROJECT = "not_in_project"


class DocCandidateStatus(StrEnum):
    CANDIDATE = "candidate"
    REJECTED = "rejected"


class DocValueOut(BaseModel):
    """Нормализованное значение: мм целыми числами, диапазон, «ширина×высота» либо текст."""

    kind: str
    display: str
    numbers: list[int]
    qualifier: str | None
    code: str | None


class DocAssumptionOut(BaseModel):
    """Норматив-допущение каталога: предложение со ссылкой на пункт СП, а не ответ проекта."""

    mm_from: int
    mm_to: int | None
    reference: str
    status: str
    note: str


class DocCandidateOut(BaseModel):
    id: UUID
    question_code: str
    value: DocValueOut
    value_text: str
    quote: str
    revision_id: UUID
    page_index: int
    page_label: str | None
    file_name: str
    building: str | None
    section: str | None
    level: str | None
    score: int
    occurrences: int
    status: DocCandidateStatus
    versions: dict[str, str]
    created_at: datetime


class DocAnswerOut(BaseModel):
    id: UUID
    question_code: str
    source: DocAnswerSource
    scope_building: str | None
    scope_section: str | None
    value: DocValueOut | None
    value_text: str | None
    candidate_id: UUID | None
    file_name: str | None
    revision_id: UUID | None
    page_index: int | None
    quote: str | None
    norm_ref: str | None
    note: str | None
    catalog_version: str
    confirmed_by: UUID
    confirmed_at: datetime


class DocSearchSummary(BaseModel):
    """Итог последнего задания поиска; числа, которых нет в итоге задания, - null."""

    job_id: UUID
    status: str
    progress: float | None
    stage: str | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    questions_found: int | None
    candidates: int | None
    revisions_total: int | None
    revisions_scanned: int | None
    revisions_no_text: int | None
    no_text_files: list[str]
    revisions_unreadable: int | None
    unreadable_files: list[str]
    versions: dict[str, str]


class DocQuestionOut(BaseModel):
    code: str
    title: str
    receiver_param: str
    value_kind: str
    # Допустимый разброс каждого размера, мм: границы ручного ввода.
    min_mm: int
    max_mm: int
    assumption: DocAssumptionOut | None
    candidates: list[DocCandidateOut]
    answers: list[DocAnswerOut]


class DocQuestionsOut(BaseModel):
    catalog_version: str
    questions: list[DocQuestionOut]
    last_search: DocSearchSummary | None


class DocScopeOut(BaseModel):
    """Область ответа; оба поля null - весь проект."""

    building: str | None
    section: str | None


class DocAnswerFlatOut(BaseModel):
    """Подтверждённый ответ с происхождением: контракт для CAD-трасс (В5)."""

    answer_id: UUID
    question_code: str
    receiver_param: str
    value: DocValueOut | None
    value_text: str | None
    source: DocAnswerSource
    scope: DocScopeOut
    file_name: str | None
    revision_id: UUID | None
    page_index: int | None
    quote: str | None
    norm_ref: str | None
    note: str | None
    catalog_version: str
    confirmed_at: datetime


class DocAnswersOut(BaseModel):
    items: list[DocAnswerFlatOut]


# --------------------------------------------------------------------------- тело ответа


def _strip_or_none(value: object) -> object:
    if isinstance(value, str):
        return value.strip() or None
    return value


class _AnswerBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Не передано - для document область кандидата, для остальных весь проект.
    scope_building: str | None = Field(default=None, max_length=TEXT_MAX)
    scope_section: str | None = Field(default=None, max_length=TEXT_MAX)

    @field_validator("scope_building", "scope_section", mode="before")
    @classmethod
    def _empty_scope_is_none(cls, value: object) -> object:
        return _strip_or_none(value)


class DocumentAnswerIn(_AnswerBase):
    source: Literal["document"]
    candidate_id: UUID
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("note", mode="before")
    @classmethod
    def _empty_note_is_none(cls, value: object) -> object:
        return _strip_or_none(value)


class ManualValueIn(BaseModel):
    """Значение ручного ответа: размеры в мм целыми; `display` собирает сервер по виду вопроса.

    length_mm - одно число; range_mm - одно или два (от < до); section_mm - ширина и высота
    (для воздуховода круглого сечения - один диаметр с code="round"); text - необязательные
    числа в границах каталога; enum - без чисел, code только rosette_down / rosette_up.
    """

    model_config = ConfigDict(extra="forbid")

    numbers: list[int] = Field(default_factory=list, max_length=VALUE_NUMBERS_MAX)
    qualifier: Literal["min", "max"] | None = None
    code: str | None = Field(default=None, max_length=32)


class ManualAnswerIn(_AnswerBase):
    source: Literal["manual"]
    value_text: str = Field(min_length=1, max_length=TEXT_MAX)
    value: ManualValueIn
    # Ручной ответ без пояснения откуда число не принимается.
    note: str = Field(min_length=1, max_length=NOTE_MAX)

    @field_validator("value_text", "note", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class NormAssumptionAnswerIn(_AnswerBase):
    source: Literal["norm_assumption"]
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("note", mode="before")
    @classmethod
    def _empty_note_is_none(cls, value: object) -> object:
        return _strip_or_none(value)


class NotInProjectAnswerIn(_AnswerBase):
    source: Literal["not_in_project"]
    note: str | None = Field(default=None, max_length=NOTE_MAX)

    @field_validator("note", mode="before")
    @classmethod
    def _empty_note_is_none(cls, value: object) -> object:
        return _strip_or_none(value)


DocAnswerIn = Annotated[
    DocumentAnswerIn | ManualAnswerIn | NormAssumptionAnswerIn | NotInProjectAnswerIn,
    Field(discriminator="source"),
]
