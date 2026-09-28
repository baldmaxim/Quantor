"""Типы плана запуска и разбор области — общие для планировщика, исполнителя и слоя запусков.

Исход по факту — значение из снимка или причина отсутствия; исход по правилу — точная версия
или причина. Требования к фактам выводятся из привязок калькулятора и области запуска.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.contracts.calc.engine import (
    CalcBlockingReason,
    CalcRuleBinding,
    CalcSnapshotItem,
)
from app.contracts.calc.enums import CalcBlockCode, CalcRuleStatus, CalcRuleType, CalcScenario
from app.contracts.calc.fact_types import check_subject, fact_type_def
from app.contracts.calc.rules import CalcRuleContent
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.units import UnitError, compatible
from app.contracts.calc.values import CalcCountValue, CalcNumberValue
from app.services.calc.engine.calculators import CalculatorDef, StepDef
from app.services.calc.engine.handlers import HandlerSpec


@dataclass(frozen=True, slots=True)
class ResolvedRule:
    """Точная версия правила, выбранная для запуска (или восстановленная из запуска)."""

    rule_key: str
    rule_version_id: uuid.UUID
    version: int
    status: CalcRuleStatus
    rule_type: CalcRuleType
    content: CalcRuleContent
    content_sha256: str


@dataclass(frozen=True, slots=True)
class Absence:
    """Почему значения или правила нет — с кодом для интерфейса и текстом для человека."""

    code: CalcBlockCode
    message: str


FactOutcome = CalcSnapshotItem | Absence
RuleOutcome = ResolvedRule | Absence


@dataclass(frozen=True, slots=True)
class FactRequirement:
    step_key: str
    input: str
    fact_type: str
    subject: CalcFactSubject
    fact_key: str


@dataclass(frozen=True, slots=True)
class OutputContract:
    unit: str | None
    quantity: str | None


@dataclass(frozen=True)
class PlannedStep:
    step: StepDef
    position: int
    applied: bool
    not_applied_reason: str | None
    rule: ResolvedRule | None
    handler: HandlerSpec | None
    facts: Mapping[str, CalcSnapshotItem]
    outputs: Mapping[str, OutputContract]


@dataclass(frozen=True)
class Plan:
    definition: CalculatorDef
    scenario: CalcScenario
    scope: CalcFactSubject
    steps: tuple[PlannedStep, ...]
    bindings: tuple[CalcRuleBinding, ...]
    snapshot_items: tuple[CalcSnapshotItem, ...]
    warnings: tuple[str, ...]
    reasons: tuple[CalcBlockingReason, ...] = field(default=())

    @property
    def valid(self) -> bool:
        return not self.reasons


def reason(
    code: CalcBlockCode,
    message: str,
    *,
    step_key: str | None = None,
    fact_key: str | None = None,
    rule_key: str | None = None,
) -> CalcBlockingReason:
    return CalcBlockingReason(
        code=code, message=message, step_key=step_key, fact_key=fact_key, rule_key=rule_key
    )


def scope_problems(definition: CalculatorDef, scope: CalcFactSubject) -> list[CalcBlockingReason]:
    reasons: list[CalcBlockingReason] = []
    missing = set(definition.scope_fields) - scope.present_fields()
    if missing:
        reasons.append(
            reason(
                CalcBlockCode.SCOPE_INVALID,
                "в области запуска не указано: " + ", ".join(sorted(missing)),
            )
        )
    if scope.discipline is not None and scope.discipline is not definition.discipline:
        reasons.append(
            reason(
                CalcBlockCode.SCOPE_INVALID,
                f"калькулятор считает раздел {definition.discipline.value}, "
                f"а в области — {scope.discipline.value}",
            )
        )
    if scope.system_code is not None and scope.system_code not in definition.systems:
        reasons.append(
            reason(
                CalcBlockCode.SCOPE_INVALID,
                f"калькулятор считает системы {', '.join(definition.systems)}, "
                f"а в области — {scope.system_code}",
            )
        )
    return reasons


def fact_requirements(
    definition: CalculatorDef, scope: CalcFactSubject
) -> tuple[list[FactRequirement], list[CalcBlockingReason]]:
    """Какие ключи фактов нужны калькулятору для этой области."""
    found: list[FactRequirement] = []
    reasons: list[CalcBlockingReason] = []
    for step in definition.steps:
        for name, binding in step.facts.items():
            definition_of_fact = fact_type_def(binding.fact_type)
            if definition_of_fact is None:
                continue
            values = {
                field_name: getattr(scope, field_name) for field_name in binding.subject_fields
            }
            try:
                subject = CalcFactSubject.model_validate(values)
            except ValueError as error:
                reasons.append(
                    reason(CalcBlockCode.SCOPE_INVALID, str(error), step_key=step.step_key)
                )
                continue
            problem = check_subject(definition_of_fact, subject)
            if problem is not None:
                reasons.append(
                    reason(
                        CalcBlockCode.SCOPE_INVALID,
                        f"факт «{definition_of_fact.title}»: {problem}",
                        step_key=step.step_key,
                    )
                )
                continue
            found.append(
                FactRequirement(
                    step_key=step.step_key,
                    input=name,
                    fact_type=binding.fact_type,
                    subject=subject,
                    fact_key=f"{binding.fact_type}@{subject.key()}",
                )
            )
    return found, reasons


def numeric_unit(item: CalcSnapshotItem) -> str | None:
    """Единица числового значения факта; для счётчика без единицы — единица типа факта."""
    value = item.value
    if isinstance(value, CalcNumberValue):
        return value.unit
    if isinstance(value, CalcCountValue):
        if value.unit is not None:
            return value.unit
        definition = fact_type_def(item.fact_type)
        return None if definition is None else definition.unit
    return None


def units_compatible(source: str | None, target: str | None) -> bool:
    if source is None or target is None:
        return source is None and target is None
    try:
        return compatible(source, target)
    except UnitError:
        return False


def contract_problems(content: CalcRuleContent, handler: HandlerSpec) -> list[str]:
    """Контракт версии правила против контракта обработчика: имена и единицы."""
    problems: list[str] = []
    groups = (
        ("входы", {item.name: item.unit for item in content.inputs}, handler.inputs),
        ("параметры", {item.name: item.unit for item in content.parameters}, handler.parameters),
        ("выходы", {item.name: item.unit for item in content.outputs}, handler.outputs),
    )
    for title, rule_side, handler_side in groups:
        if set(rule_side) != set(handler_side):
            problems.append(
                f"{title} правила ({', '.join(sorted(rule_side)) or '—'}) не совпадают с "
                f"реализацией ({', '.join(sorted(handler_side)) or '—'})"
            )
            continue
        for name, unit in rule_side.items():
            if not units_compatible(unit, handler_side[name]):
                problems.append(
                    f"«{name}»: единица правила {unit or '—'} не совместима с реализацией "
                    f"{handler_side[name] or '—'}"
                )
    return problems


def rule_binding(step: StepDef, rule: ResolvedRule, handler: HandlerSpec) -> CalcRuleBinding:
    return CalcRuleBinding(
        step_key=step.step_key,
        rule_key=rule.rule_key,
        rule_version_id=rule.rule_version_id,
        version=rule.version,
        status_at_run=rule.status,
        rule_type=rule.rule_type,
        content_sha256=rule.content_sha256,
        implementation_key=handler.implementation_key,
        handler_semantics_sha256=handler.semantics_sha256,
        content=rule.content,
    )
