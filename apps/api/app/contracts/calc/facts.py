"""Контракты API реестра фактов (PROMPT 01).

Реестр хранит **утверждения**: «источник S утверждает, что факт K имеет значение V». Значение
утверждения не меняется никогда; новое значение того же источника — новая версия, прежняя
получает статус «заменено». Два источника с разными значениями одного ключа — конфликт, а не
тихий выбор одного из них.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcConflictStatus,
    CalcDocumentStage,
    CalcEvidenceKind,
    CalcFactMethod,
    CalcFactStatus,
    CalcResolutionState,
    CalcReviewStatus,
    CalcSourceClass,
    CalcValueKind,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcFactValue

Reason = Annotated[str, Field(min_length=1, max_length=1000)]
NormalizedBox = Annotated[
    list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]],
    Field(min_length=4, max_length=4),
]
"""Область на листе: [x0, y0, x1, y1] в нормализованных координатах от левого верхнего угла."""


class _Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------- источники


class CalcSourceCreate(BaseModel):
    """Заявление источника: откуда берутся факты.

    Стадия документа — заявление пользователя, а не свойство ревизии: ревизии неизменяемы
    (ADR-0003), и стадию в них не пишут.
    """

    model_config = ConfigDict(extra="forbid")

    source_class: CalcSourceClass
    title: Annotated[str, Field(min_length=1, max_length=200)]
    document_stage: CalcDocumentStage = CalcDocumentStage.UNKNOWN
    section_code: Annotated[str | None, Field(default=None, max_length=16)] = None
    """Раздел проекта: «АР», «ВК», «ПЗ»."""
    series_key: Annotated[str | None, Field(default=None, max_length=100)] = None
    """Серия документа: новая версия той же серии позже заменит утверждения старой."""
    document_revision_id: uuid.UUID | None = None
    """Ревизия документа проекта, если источник — загруженный документ."""
    note: Annotated[str | None, Field(default=None, max_length=1000)] = None


class CalcSourceRead(_Read):
    id: uuid.UUID
    project_id: uuid.UUID
    source_class: CalcSourceClass
    title: str
    document_stage: CalcDocumentStage
    section_code: str | None
    series_key: str | None
    document_revision_id: uuid.UUID | None
    content_sha256: str | None
    """Отпечаток файла источника: одинаковый файл, заведённый дважды, не даёт двух подтверждений."""
    calculation_eligible: bool
    """Идут ли факты источника в снимок расчётного ядра. У ВОР Заказчика — никогда."""
    note: str | None
    created_by: uuid.UUID | None
    created_at: datetime


# -------------------------------------------------------------------------- свидетельства


class CalcDocumentFragmentEvidence(BaseModel):
    """Место в документе проекта, где прочитано значение."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["DOCUMENT_FRAGMENT"] = "DOCUMENT_FRAGMENT"
    document_revision_id: uuid.UUID
    page_index: Annotated[int | None, Field(default=None, ge=0)] = None
    """Номер страницы PDF с нуля."""
    sheet_id: uuid.UUID | None = None
    bbox: NormalizedBox | None = None
    locator: Annotated[str | None, Field(default=None, max_length=200)] = None
    """Уточнение для человека: «табл. 3, строка 12», «п. 4.2»."""
    excerpt: Annotated[str | None, Field(default=None, max_length=500)] = None
    """Дословный фрагмент текста."""


class CalcAssumptionEvidence(BaseModel):
    """Основание инженерного допущения."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ASSUMPTION_BASIS"] = "ASSUMPTION_BASIS"
    basis: Reason
    """Почему принято именно это значение."""
    alternatives: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=10)
    ] = Field(default_factory=list)
    """Рассмотренные альтернативы — понадобятся анализу чувствительности."""


CalcEvidenceCreate = Annotated[
    CalcDocumentFragmentEvidence | CalcAssumptionEvidence, Field(discriminator="kind")
]


class CalcEvidenceRead(_Read):
    id: uuid.UUID
    kind: CalcEvidenceKind
    document_revision_id: uuid.UUID | None
    page_index: int | None
    sheet_id: uuid.UUID | None
    bbox: list[float] | None
    locator: str | None
    excerpt: str | None
    basis: str | None
    alternatives: list[str]
    author_id: uuid.UUID | None
    created_at: datetime


# ---------------------------------------------------------------------------- утверждения


class CalcFactCreate(BaseModel):
    """Новое утверждение. Если у источника уже есть действующее по этому ключу — оно заменяется."""

    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    fact_type: Annotated[str, Field(min_length=1, max_length=64)]
    subject: CalcFactSubject
    value: CalcFactValue
    method: CalcFactMethod
    confidence: CalcConfidence | None = None
    """Пусто — по методу получения."""
    evidence: Annotated[list[CalcEvidenceCreate], Field(max_length=10)] = Field(
        default_factory=list
    )
    note: Annotated[str | None, Field(default=None, max_length=1000)] = None


class CalcFactRead(_Read):
    id: uuid.UUID
    project_id: uuid.UUID
    source_id: uuid.UUID
    source_class: CalcSourceClass
    fact_type: str
    subject: CalcFactSubject
    subject_key: str
    fact_key: str
    value: CalcFactValue
    """Каноническая форма: в единице типа факта."""
    stated_value: CalcFactValue
    """Как значение пришло от источника."""
    method: CalcFactMethod
    confidence: CalcConfidence
    review_status: CalcReviewStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_comment: str | None
    status: CalcFactStatus
    version: int
    supersedes_id: uuid.UUID | None
    calculation_eligible: bool
    withdrawn_reason: str | None
    withdrawn_at: datetime | None
    note: str | None
    created_by: uuid.UUID | None
    created_at: datetime
    evidence: list[CalcEvidenceRead]


class CalcFactReview(BaseModel):
    """Проверка утверждения человеком."""

    model_config = ConfigDict(extra="forbid")

    status: Literal[CalcReviewStatus.CONFIRMED, CalcReviewStatus.REJECTED]
    comment: Annotated[str | None, Field(default=None, max_length=1000)] = None

    @model_validator(mode="after")
    def _reject_needs_reason(self) -> CalcFactReview:
        if self.status is CalcReviewStatus.REJECTED and not (self.comment or "").strip():
            raise ValueError("отклонение требует комментария")
        return self


class CalcFactWithdraw(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Reason


# ------------------------------------------------------------------ конфликты и решения


class CalcDecisionCreate(BaseModel):
    """Решение конфликта человеком: выбрать утверждение или ввести своё значение.

    Своё значение становится обычным утверждением ручного ввода с основанием — и решение
    выбирает его. Так у любого действующего значения остаётся утверждение-носитель.
    """

    model_config = ConfigDict(extra="forbid")

    chosen_fact_id: uuid.UUID | None = None
    value: CalcFactValue | None = None
    reason: Reason

    @model_validator(mode="after")
    def _exactly_one(self) -> CalcDecisionCreate:
        if (self.chosen_fact_id is None) == (self.value is None):
            raise ValueError("укажите либо выбранное утверждение, либо своё значение")
        return self


class CalcDecisionRead(_Read):
    id: uuid.UUID
    fact_key: str
    conflict_id: uuid.UUID | None
    chosen_fact_id: uuid.UUID
    reason: str
    claim_set_hash: str
    decided_by: uuid.UUID | None
    created_at: datetime
    revoked_at: datetime | None


class CalcConflictRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    fact_key: str
    fact_type: str
    subject_key: str
    status: CalcConflictStatus
    claim_set_hash: str
    claims: list[CalcFactRead]
    decision: CalcDecisionRead | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------ действующие значения


class CalcFactValueRead(BaseModel):
    """Действующее значение ключа и то, как оно получено.

    Считается только по утверждениям, допущенным к расчёту. Утверждения из ВОР Заказчика
    перечислены отдельно и на значение не влияют.
    """

    fact_key: str
    fact_type: str
    subject: CalcFactSubject
    state: CalcResolutionState
    value: CalcFactValue | None
    chosen_fact_id: uuid.UUID | None
    claim_ids: list[uuid.UUID]
    excluded_claim_ids: list[uuid.UUID]
    """Утверждения, не допущенные к расчёту: ВОР Заказчика."""
    conflict_id: uuid.UUID | None
    policy_version: str
    warnings: list[str]


# -------------------------------------------------------------------------- типы фактов


class CalcEnumOptionRead(BaseModel):
    value: str
    title: str


class CalcFactTypeRead(BaseModel):
    """Тип факта для форм ввода: что ждать и где."""

    key: str
    title: str
    description: str
    value_kind: CalcValueKind
    unit: str | None
    unit_title: str | None
    required_subject: list[str]
    allowed_subject: list[str]
    options: list[CalcEnumOptionRead]
    customer_vor_admissible: bool
