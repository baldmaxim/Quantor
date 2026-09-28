"""Политика приоритета источников.

Глобальной истины вроде «спецификация всегда главнее плана» нет: приоритет задаётся на тип
факта и зависит от класса источника и заявленной стадии документа. По умолчанию политика
требует решения человека; автоматический выбор разрешён перечнем типов ниже — и даже тогда
конфликт остаётся открытым и видимым.

Политика — данные с версией: запуск расчёта запомнит, по какой версии выбрано значение.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.contracts.calc.enums import CalcDocumentStage, CalcPolicyMode, CalcSourceClass

POLICY_VERSION: Final = "calc.priority.v1"

Rank = tuple[CalcSourceClass, CalcDocumentStage | None]
"""Ступень приоритета: класс источника и стадия; пустая стадия — любая."""


@dataclass(frozen=True, slots=True)
class PolicyEntry:
    mode: CalcPolicyMode
    ranking: tuple[Rank, ...] = ()
    """Сверху вниз: первая подходящая ступень — самый сильный источник."""


DEFAULT_POLICY: Final = PolicyEntry(CalcPolicyMode.MANUAL_REQUIRED)

_P = CalcDocumentStage.P
_RD = CalcDocumentStage.RD

POLICIES: Final[MappingProxyType[str, PolicyEntry]] = MappingProxyType(
    {
        # Квартиры считает квартирография; планы АР — проверка. Более поздняя стадия того же
        # класса сильнее ранней: РД уточняет П.
        "floor.apartments_count": PolicyEntry(
            CalcPolicyMode.AUTO_PREFER,
            (
                (CalcSourceClass.APARTMENT_SCHEDULE, _RD),
                (CalcSourceClass.APARTMENT_SCHEDULE, _P),
                (CalcSourceClass.ARCHITECTURE, _RD),
                (CalcSourceClass.ARCHITECTURE, _P),
            ),
        ),
        # Высоты этажей — архитектура: разрезы сильнее пояснительной записки.
        "floor.height": PolicyEntry(
            CalcPolicyMode.AUTO_PREFER,
            (
                (CalcSourceClass.ARCHITECTURE, _RD),
                (CalcSourceClass.ARCHITECTURE, _P),
                (CalcSourceClass.EXPLANATORY_NOTE, None),
            ),
        ),
        "building.floors_above_ground": PolicyEntry(
            CalcPolicyMode.AUTO_PREFER,
            (
                (CalcSourceClass.ARCHITECTURE, _RD),
                (CalcSourceClass.ARCHITECTURE, _P),
                (CalcSourceClass.APARTMENT_SCHEDULE, None),
                (CalcSourceClass.EXPLANATORY_NOTE, None),
            ),
        ),
    }
)


def policy_for(fact_type: str) -> PolicyEntry:
    return POLICIES.get(fact_type, DEFAULT_POLICY)


def rank_of(
    entry: PolicyEntry, source_class: CalcSourceClass, stage: CalcDocumentStage
) -> int | None:
    """Место источника в ранжировании: меньше — сильнее; пусто — источник не ранжирован."""
    for index, (klass, klass_stage) in enumerate(entry.ranking):
        if klass is source_class and (klass_stage is None or klass_stage is stage):
            return index
    return None
