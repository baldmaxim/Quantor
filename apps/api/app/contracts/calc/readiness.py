"""Матрица готовности исходных данных и таблица фактов экрана «Исходные данные» (PROMPT 02).

Представление, а не хранимая сущность: считается при чтении из реестра фактов, записей о
сборе и каталога требований. Отвечает на вопрос «что известно для расчёта и чего не хватает»
и различает «проверено, не найдено» (MISSING) и «ещё не проверено» (NOT_INSPECTED).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.contracts.calc.enums import (
    CalcAssumptionPolicy,
    CalcConfidence,
    CalcDiscipline,
    CalcFactMethod,
    CalcFactUsage,
    CalcReadinessStatus,
    CalcRequirementGroup,
    CalcRequirementLevel,
    CalcResolutionState,
    CalcSourceClass,
)
from app.contracts.calc.facts import CalcFactRead
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcFactValue


class CalcReadinessValueRead(BaseModel):
    """Действующее значение одного ключа, закрывающего требование."""

    fact_key: str
    subject: CalcFactSubject
    state: CalcResolutionState
    value: CalcFactValue | None
    chosen_fact_id: uuid.UUID | None
    source_title: str | None
    source_class: CalcSourceClass | None
    method: CalcFactMethod | None
    confidence: CalcConfidence | None
    conflict_id: uuid.UUID | None


class CalcReadinessRowRead(BaseModel):
    requirement_id: str
    title: str
    group: CalcRequirementGroup
    fact_type: str
    level: CalcRequirementLevel
    assumption: CalcAssumptionPolicy
    status: CalcReadinessStatus
    reason: str | None
    """Почему статус такой: «проверено 3 документа — не найдено», «ТУ не найдены»."""
    values: list[CalcReadinessValueRead]
    excluded_count: int
    """Утверждения ВОР Заказчика по этому требованию: только для сверки, в расчёт не идут."""
    derivable_from: list[str]


class CalcLevelCountRead(BaseModel):
    """Сколько требований уровня закрыто: найдено или выводимо."""

    level: CalcRequirementLevel
    satisfied: int
    total: int


class CalcSystemReadinessRead(BaseModel):
    discipline: CalcDiscipline
    system_code: str
    title: str
    counts: list[CalcLevelCountRead]
    rows: list[CalcReadinessRowRead]


class CalcDocumentCoverageRead(BaseModel):
    """Документы проекта с точки зрения сбора фактов (последние ревизии)."""

    recognized: int
    inspected: int
    not_inspected: int
    without_recognition: int


class CalcReadinessRead(BaseModel):
    requirements_version: str
    fact_types_version: str
    systems: list[CalcSystemReadinessRead]
    documents: CalcDocumentCoverageRead


class CalcInputFactRead(BaseModel):
    """Строка таблицы фактов: утверждение и ответ, идёт ли оно в расчёт."""

    fact: CalcFactRead
    fact_type_title: str
    source_title: str
    usage: CalcFactUsage


class CalcInputFactPage(BaseModel):
    items: list[CalcInputFactRead]
    total: int
