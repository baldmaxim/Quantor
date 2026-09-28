"""Правила синтеза: утверждённая версия → реализация из реестра обработчиков ядра → решение.

Синтезатор не считает инженерные величины своей формулой — числа приходят из запуска расчёта.
Правило синтеза решает структурный вопрос: сколько ветвей на стояк и этаж, какую кратность
выбрать из диапазона, какой тендерный резерв принять. Исполняется оно той же реализацией из
того же статического реестра, что шаги ядра, с тем же отпечатком семантики.

Недоступное правило — не ошибка: структура остаётся неполной, диапазон — диапазоном, допущение
не применяется. Ошибка — несовпадение контракта или типа правила: это блокировка.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from app.contracts.calc.engine import CalcBlockingReason, CalcResultRead, CalcRuleBinding
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcDocumentStage,
    CalcRuleInputKind,
    CalcRuleType,
    CalcScenario,
    CalcSynthesisRuleRole,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcSynthesisRuleRef
from app.contracts.calc.units import to_canonical
from app.services.calc.engine import policy
from app.services.calc.engine.handlers import HandlerContext, HandlerSpec, run_handler
from app.services.calc.engine.numbers import parse_exact
from app.services.calc.engine.plan_types import (
    Absence,
    ResolvedRule,
    RuleOutcome,
    contract_problems,
)
from app.services.calc.engine.quantity import Quantity


@dataclass(frozen=True, slots=True)
class ResultInput:
    """Вход правила синтеза — результат запуска расчёта по ключу."""

    result_key: str


@dataclass(frozen=True)
class SynthesisRuleSpec:
    role: CalcSynthesisRuleRole
    rule_key: str
    allowed_types: frozenset[CalcRuleType]
    outputs: tuple[str, ...]
    inputs: Mapping[str, ResultInput] = field(default_factory=dict)


@dataclass(frozen=True)
class AppliedRule:
    spec: SynthesisRuleSpec
    rule: ResolvedRule
    handler: HandlerSpec
    outputs: Mapping[str, Decimal]
    """Выходы в единицах правила."""
    explanation: str

    @property
    def ref(self) -> CalcSynthesisRuleRef:
        return CalcSynthesisRuleRef(
            rule_key=self.rule.rule_key,
            version=self.rule.version,
            rule_type=self.rule.rule_type,
            content_sha256=self.rule.content_sha256,
            implementation_key=self.handler.implementation_key,
            role=self.spec.role,
        )

    def binding(self, name: str) -> CalcRuleBinding:
        return CalcRuleBinding(
            step_key=name,
            rule_key=self.rule.rule_key,
            rule_version_id=self.rule.rule_version_id,
            version=self.rule.version,
            status_at_run=self.rule.status,
            rule_type=self.rule.rule_type,
            content_sha256=self.rule.content_sha256,
            implementation_key=self.handler.implementation_key,
            handler_semantics_sha256=self.handler.semantics_sha256,
            content=self.rule.content,
        )


@dataclass(frozen=True, slots=True)
class RuleUnavailable:
    spec: SynthesisRuleSpec
    message: str


RuleUse = AppliedRule | RuleUnavailable


class SynthesisRuleError(Exception):
    """Реализация правила синтеза упала — ошибка программы, запуск FAILED."""


def _convert(value: Decimal, unit: str | None, target: str | None) -> Decimal:
    if unit == target or unit is None or target is None:
        return value
    return to_canonical(value, unit, target)


def use_rule(
    name: str,
    spec: SynthesisRuleSpec,
    outcome: RuleOutcome | None,
    *,
    scenario: CalcScenario,
    scope: CalcFactSubject,
    stage: CalcDocumentStage,
    results: Mapping[str, CalcResultRead],
    handlers: Mapping[str, HandlerSpec],
) -> RuleUse | CalcBlockingReason:
    """Применение правила синтеза или причина, почему оно недоступно либо блокирует запуск."""

    def blocked(code: CalcBlockCode, message: str) -> CalcBlockingReason:
        return CalcBlockingReason(code=code, message=message, step_key=name, rule_key=spec.rule_key)

    if outcome is None or isinstance(outcome, Absence):
        message = outcome.message if outcome is not None else f"правила {spec.rule_key} нет"
        return RuleUnavailable(spec, message)
    if outcome.rule_type not in spec.allowed_types or not policy.allows(
        scenario, outcome.rule_type
    ):
        return blocked(
            CalcBlockCode.RULE_TYPE_NOT_ALLOWED,
            f"версия {outcome.rule_key}@{outcome.version} типа {outcome.rule_type.value} не "
            f"допускается ролью {spec.role.value} или сценарием {scenario.value}",
        )
    applicability = outcome.content.applicability
    if scope.system_code is not None and scope.system_code not in applicability.systems:
        return RuleUnavailable(
            spec, f"{outcome.rule_key}@{outcome.version} не применимо к {scope.system_code}"
        )
    if stage not in applicability.stages:
        return RuleUnavailable(
            spec, f"{outcome.rule_key}@{outcome.version} не применимо к стадии {stage.value}"
        )
    handler = handlers.get(outcome.content.implementation_key or "")
    if handler is None:
        return blocked(
            CalcBlockCode.IMPLEMENTATION_MISSING,
            f"нет реализации «{outcome.content.implementation_key}» для "
            f"{outcome.rule_key}@{outcome.version}",
        )
    problems = contract_problems(outcome.content, handler)
    declared = {item.name: item for item in outcome.content.inputs}
    if set(declared) != set(spec.inputs) or any(
        item.kind is not CalcRuleInputKind.QUANTITY for item in declared.values()
    ):
        problems.append(
            f"входы версии ({', '.join(sorted(declared)) or '—'}) не совпадают с результатами "
            f"расчёта синтезатора ({', '.join(sorted(spec.inputs)) or '—'})"
        )
    rule_outputs = {item.name: item.unit for item in outcome.content.outputs}
    if not set(spec.outputs) <= set(rule_outputs):
        problems.append("у версии правила нет выходов: " + ", ".join(spec.outputs))
    for input_name, source in spec.inputs.items():
        if source.result_key not in results:
            problems.append(
                f"нет результата расчёта «{source.result_key}» для входа «{input_name}»"
            )
    if problems:
        return blocked(CalcBlockCode.RULE_CONTRACT_MISMATCH, "; ".join(problems))

    try:
        context = HandlerContext(
            inputs=MappingProxyType(
                {
                    input_name: Quantity.of(
                        _convert(
                            parse_exact(results[source.result_key].value),
                            results[source.result_key].unit,
                            handler.inputs[input_name],
                        ),
                        handler.inputs[input_name],
                    )
                    for input_name, source in spec.inputs.items()
                }
            ),
            parameters=MappingProxyType(
                {
                    item.name: Quantity.of(
                        _convert(parse_exact(item.value), item.unit, handler.parameters[item.name]),
                        handler.parameters[item.name],
                    )
                    for item in outcome.content.parameters
                }
            ),
        )
        result = run_handler(handler, context)
        outputs = {
            output: _convert(
                result.outputs[output].in_unit(handler.outputs[output]),
                handler.outputs[output],
                rule_outputs[output],
            )
            for output in spec.outputs
        }
    except Exception as error:
        raise SynthesisRuleError(f"{spec.rule_key}: {type(error).__name__}: {error}") from error
    return AppliedRule(spec, outcome, handler, MappingProxyType(outputs), result.explanation)
