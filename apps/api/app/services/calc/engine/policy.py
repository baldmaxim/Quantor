"""Политика сценариев стадии П: какие классы правил допустимы в каком сценарии.

Политика — жёсткие ограничения, а не инженерное решение. Сколько трубы относится к какому
сценарию, решают калькуляторы PROMPT 05–06 выбором шагов и правил; ядро только не даёт
применить недопустимое:

- тендерное допущение — только в TENDER_SAFE и только в шаге, который его явно допускает;
- в MINIMUM и EXPECTED шаг допущения не применяется: значение передаётся без изменения, и
  причина видна в цепочке расчёта;
- универсального «+10 %» нет: резерв — только утверждённое правило с источником.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.contracts.calc.enums import CalcRuleType, CalcScenario

SCENARIO_POLICY_VERSION: Final = "calc.scenario_policy.v1"

_WITHOUT_RESERVE: Final = frozenset(
    {
        CalcRuleType.PHYSICS,
        CalcRuleType.GEOMETRY,
        CalcRuleType.NORMATIVE,
        CalcRuleType.MANUFACTURER,
        CalcRuleType.ENGINEERING,
    }
)

ALLOWED_RULE_TYPES: Final[MappingProxyType[CalcScenario, frozenset[CalcRuleType]]] = (
    MappingProxyType(
        {
            CalcScenario.MINIMUM: _WITHOUT_RESERVE,
            CalcScenario.EXPECTED: _WITHOUT_RESERVE,
            CalcScenario.TENDER_SAFE: _WITHOUT_RESERVE | {CalcRuleType.TENDER_ASSUMPTION},
        }
    )
)


def allows(scenario: CalcScenario, rule_type: CalcRuleType) -> bool:
    return rule_type in ALLOWED_RULE_TYPES[scenario]


def assumptions_apply(scenario: CalcScenario) -> bool:
    """Применяются ли шаги тендерного допущения в сценарии."""
    return allows(scenario, CalcRuleType.TENDER_ASSUMPTION)


def not_applied_reason(scenario: CalcScenario) -> str:
    return (
        f"Сценарий {scenario.value} не допускает тендерных допущений — значение передано "
        "без изменения"
    )
