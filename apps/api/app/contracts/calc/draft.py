"""Черновые контракты сущностей следующих промтов.

Только типы. Таблиц, сервисов и маршрутов у этих сущностей нет и до их промта не будет:
пустая таблица без писателя и читателя — схема, которая почти наверняка окажется неверной
(`contracts/quantities.py`). Контракт уточняется до этапа реализации; в OpenAPI он не попадает,
пока на него не сослался маршрут.

| Сущность            | Промт реализации |
| ------------------- | ---------------- |
| RuleReference       | 03               |
| CalculationInput    | 04               |
| Assumption          | 04               |
| CalculationRun      | 04               |
| CalculationStep     | 04               |
| CalculationResult   | 04               |
| ExpectedQuantity    | 04–06            |
| CustomerVorItem     | 09               |
| VorMatch            | 09               |
| ProjectQuestion     | 10               |
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.calc.enums import CalcConfidence, CalcDiscipline
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcFactValue, DecimalText

DRAFT_CONTRACTS_VERSION: Final = "calc.draft.v0"


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------------------ правила


class CalcRuleType(StrEnum):
    PHYSICS = "PHYSICS"
    GEOMETRY = "GEOMETRY"
    NORMATIVE = "NORMATIVE"
    MANUFACTURER = "MANUFACTURER"
    ENGINEERING = "ENGINEERING"
    TENDER_ASSUMPTION = "TENDER_ASSUMPTION"


class CalcRuleReviewStatus(StrEnum):
    """Статус инженерной проверки — отдельно от содержимого правила и вне его хеша."""

    DRAFT = "DRAFT"
    UNVERIFIED_LEGACY = "UNVERIFIED_LEGACY"
    SOURCED = "SOURCED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REJECTED_LEGACY = "REJECTED_LEGACY"
    DEPRECATED = "DEPRECATED"


class CalcRuleReference(_Draft):
    """Ссылка на правило реестра так, как её запоминает запуск: версия и хеш содержимого."""

    rule_id: Annotated[str, Field(min_length=1, max_length=100)]
    version: Annotated[int, Field(ge=1)]
    content_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    rule_type: CalcRuleType
    review_status: CalcRuleReviewStatus
    """Статус на момент запуска."""


# ------------------------------------------------------------------------------ расчёт


class CalcScenario(StrEnum):
    MINIMUM = "MINIMUM"
    EXPECTED = "EXPECTED"
    TENDER_SAFE = "TENDER_SAFE"


class CalcResultStatus(StrEnum):
    DETERMINED = "DETERMINED"
    NOT_DETERMINED = "NOT_DETERMINED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED_BY_CONFLICT = "BLOCKED_BY_CONFLICT"


class CalcRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CalcElementProvenance(StrEnum):
    OBSERVED = "OBSERVED"
    CALCULATED = "CALCULATED"
    SYNTHESIZED = "SYNTHESIZED"
    ASSUMED = "ASSUMED"


class CalcCalculationInput(_Draft):
    """Вход запуска: действующее значение факта на момент расчёта — копия, а не ссылка."""

    fact_key: str
    subject: CalcFactSubject
    value: CalcFactValue
    chosen_fact_id: uuid.UUID
    """Утверждение-носитель. Только допущенное к расчёту: ВОР Заказчика сюда не попадает."""


class CalcAssumption(_Draft):
    """Зарегистрированное допущение: что принято, на каком основании и какие были альтернативы."""

    key: str
    subject: CalcFactSubject
    value: CalcFactValue
    basis: str
    rule: CalcRuleReference | None
    alternatives: list[CalcFactValue]


class CalcCalculationRun(_Draft):
    id: uuid.UUID
    project_id: uuid.UUID
    calculator: str
    """Калькулятор с версией: «vk.passport.v1»."""
    engine_version: str
    status: CalcRunStatus
    parent_run_id: uuid.UUID | None
    facts_snapshot_sha256: str
    rules: list[CalcRuleReference]
    started_at: datetime
    finished_at: datetime | None


class CalcStepInputRef(_Draft):
    """Вход шага: факт или результат другого шага, со значением на момент расчёта."""

    fact_key: str | None
    step_key: str | None
    value: CalcFactValue


class CalcCalculationStep(_Draft):
    run_id: uuid.UUID
    step_key: str
    """Стабильный ключ шага: «vk.v1/K1/sec:2/zone:1/riser:3/length»."""
    scenario: CalcScenario
    inputs: list[CalcStepInputRef]
    rule: CalcRuleReference | None
    formula: str | None
    """Русский шаблон формулы для раскрытия цифры."""
    output: CalcFactValue | None
    status: CalcResultStatus
    assumptions: list[str]


class CalcCalculationResult(_Draft):
    """Инженерная величина — расход, зона, DN, число стояков. Не позиция паспорта."""

    run_id: uuid.UUID
    result_key: str
    subject: CalcFactSubject
    values: dict[CalcScenario, CalcFactValue | None]
    status: dict[CalcScenario, CalcResultStatus]
    step_keys: list[str]


class CalcItemDescriptor(_Draft):
    """Описатель позиции: по нему идёт сверка с ВОР, а не по названию."""

    discipline: CalcDiscipline
    system_code: str
    group: str
    """Группа PROMPT 06: A–L."""
    functional_type: str
    material: str | None
    size: str | None
    """Типоразмер с видом: «DN 32», «Ø110×3,4»."""
    scope: CalcFactSubject
    unit: str


class CalcExpectedQuantity(_Draft):
    """Позиция Расчётного паспорта с тремя сценариями и долей значения на допущениях."""

    run_id: uuid.UUID
    result_key: str
    descriptor: CalcItemDescriptor
    minimum: DecimalText | None
    expected: DecimalText | None
    tender_safe: DecimalText | None
    status: dict[CalcScenario, CalcResultStatus]
    step_keys: list[str]
    assumption_share: DecimalText
    confidence: CalcConfidence
    warnings: list[str]


# --------------------------------------------------------------------------- сверка с ВОР


class CalcVorMatchStatus(StrEnum):
    MATCHED = "MATCHED"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    CALC_HIGHER = "CALC_HIGHER"
    CALC_LOWER = "CALC_LOWER"
    NOT_IN_CALC = "NOT_IN_CALC"
    MISSING_IN_CUSTOMER_VOR = "MISSING_IN_CUSTOMER_VOR"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


class CalcCustomerVorItem(_Draft):
    """Позиция ВОР Заказчика. Объект сверки: в расчёт не входит ни количеством, ни решением."""

    id: uuid.UUID
    project_id: uuid.UUID
    row_ref: str
    code: str | None
    name: str
    unit: str
    quantity: DecimalText | None
    normalized: CalcItemDescriptor | None


class CalcVorMatch(_Draft):
    """Сопоставление позиции ВОР с позицией паспорта. Количества сравнивает код."""

    vor_item_id: uuid.UUID
    run_id: uuid.UUID
    result_keys: list[str]
    status: CalcVorMatchStatus
    deviation: DecimalText | None
    deviation_percent: DecimalText | None
    tolerance_class: str
    method: str
    """Детерминированное правило, ручное подтверждение; позже — принятый кандидат модели."""
    confirmed_by: uuid.UUID | None


# -------------------------------------------------------------------------------- вопросы


class CalcQuestionStatus(StrEnum):
    OPEN = "OPEN"
    SENT = "SENT"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"


class CalcProjectQuestion(_Draft):
    """Вопрос Заказчику: только при существенном влиянии, с оценкой в количествах."""

    id: uuid.UUID
    project_id: uuid.UUID
    discipline: CalcDiscipline | None
    topic: str
    description: str
    checked_sources: list[uuid.UUID]
    not_found: list[str]
    run_id: uuid.UUID | None
    affected_result_keys: list[str]
    impact: str
    current_assumption: str | None
    change_after_answer: str
    status: CalcQuestionStatus
    due: date | None
