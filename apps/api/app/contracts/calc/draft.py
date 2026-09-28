"""Черновые контракты сущностей следующих промтов.

Только типы. Таблиц, сервисов и маршрутов у этих сущностей нет и до их промта не будет:
пустая таблица без писателя и читателя — схема, которая почти наверняка окажется неверной
(`contracts/quantities.py`). Контракт уточняется до этапа реализации; в OpenAPI он не попадает,
пока на него не сослался маршрут.

Реализованы и вынесены: правила — `rules.py` (PROMPT 03); запуск, шаг, результат, снимок
входов, допущение и ссылка запуска на версию правила — `engine.py` (PROMPT 04); происхождение
элемента и граф системы — `synthesis.py` (PROMPT 05); ожидаемые количества и Расчётный паспорт —
`passport.py` (PROMPT 06).

| Сущность            | Промт реализации |
| ------------------- | ---------------- |
| CustomerVorItem     | 09               |
| VorMatch            | 09               |
| ProjectQuestion     | 10               |
"""

from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.contracts.calc.enums import CalcDiscipline
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import DecimalText

DRAFT_CONTRACTS_VERSION: Final = "calc.draft.v0"


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------------------ расчёт


class CalcItemDescriptor(_Draft):
    """Описатель позиции: по нему идёт сверка с ВОР, а не по названию."""

    discipline: CalcDiscipline
    system_code: str
    group: str
    """Категория позиции паспорта (PROMPT 06): PIPE, FITTING, VALVE…"""
    functional_type: str
    material: str | None
    size: str | None
    """Типоразмер с видом: «DN 32», «Ø110×3,4»."""
    scope: CalcFactSubject
    unit: str


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
