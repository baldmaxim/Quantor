"""Исполнение плана: шаги по порядку графа, переводы единиц, допущения, результаты.

Чистая функция: план, сценарий и карта прежних шагов для повторного использования — на входе;
записи шагов и результатов с отпечатками — на выходе. База, запрос и реестры сюда не приходят.

- Каждый перевод единиц записывается в шаг.
- Промежуточные значения не округляются; округляется только итог, если его определение
  калькулятора это требует, и округление видно в цепочке.
- Отпечаток шага — калькулятор, реализация и её семантика, точная версия правила, входы в
  рабочих единицах, параметры, сценарий и отпечатки шагов-источников. Совпал с шагом прежнего
  успешного запуска того же проекта — результат берётся оттуда, и это видно (`REUSED`).
- Любая ошибка обработчика — `StepExecutionError`: запуск станет FAILED, а не «примерно так».
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, Inexact
from types import MappingProxyType

from app.contracts.calc.engine import (
    CalcAssumptionRecord,
    CalcConversion,
    CalcResultRead,
    CalcRoundingRecord,
    CalcRuleRef,
    CalcStepInput,
    CalcStepOutput,
    CalcStepRead,
)
from app.contracts.calc.enums import CalcInputSource, CalcScenario, CalcStepStatus
from app.contracts.calc.units import UNITS, to_canonical
from app.contracts.calc.values import CalcCountValue, CalcNumberValue
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.handlers import HandlerContext, run_handler
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.numbers import apply_rounding, exact_text, parse_exact, ru_number
from app.services.calc.engine.plan_types import Plan, PlannedStep, numeric_unit
from app.services.calc.engine.quantity import Quantity


class StepExecutionError(Exception):
    """Ошибка исполнения шага — ошибка программы, не нехватка данных."""

    def __init__(self, step_key: str, error: str, message: str) -> None:
        super().__init__(message)
        self.step_key = step_key
        self.error = error
        self.message = message


@dataclass(frozen=True, slots=True)
class PriorStep:
    """Шаг прежнего успешного запуска, пригодный для повторного использования."""

    run_id: uuid.UUID
    fingerprint: str
    outputs: tuple[CalcStepOutput, ...]
    explanation: str
    roundings: tuple[CalcRoundingRecord, ...] = ()


@dataclass(frozen=True)
class Execution:
    steps: tuple[CalcStepRead, ...]
    results: tuple[CalcResultRead, ...]
    assumptions: tuple[CalcAssumptionRecord, ...]
    result_sha256: str


@dataclass(frozen=True, slots=True)
class _Value:
    value: Decimal
    unit: str | None


def _convert(
    value: Decimal, unit: str | None, target: str | None
) -> tuple[Decimal, CalcConversion | None]:
    if unit == target or unit is None or target is None:
        return value, None
    converted = to_canonical(value, unit, target)
    return converted, CalcConversion(
        from_value=exact_text(value),
        from_unit=unit,
        to_value=exact_text(converted),
        to_unit=target,
    )


def result_sha256(
    definition: CalculatorDef, scenario: CalcScenario, results: tuple[CalcResultRead, ...]
) -> str:
    """Отпечаток набора результатов: только значения, без времени и служебных полей."""
    return canonical_sha256(
        {
            "calculator": definition.calculator_id,
            "version": definition.version,
            "scenario": scenario.value,
            "results": sorted(
                [
                    {"result_key": item.result_key, "value": item.value, "unit": item.unit}
                    for item in results
                ],
                key=lambda item: str(item["result_key"]),
            ),
        }
    )


class _Executor:
    def __init__(self, plan: Plan, run_id: uuid.UUID, reuse: Mapping[str, PriorStep]) -> None:
        self.plan = plan
        self.run_id = run_id
        self.reuse = reuse
        self.values: dict[tuple[str, str], _Value] = {}
        self.fingerprints: dict[str, str] = {}
        self.records: list[CalcStepRead] = []
        self.assumptions: list[CalcAssumptionRecord] = []

    def fingerprint(
        self,
        planned: PlannedStep,
        inputs: list[CalcStepInput],
        parameters: list[CalcStepInput],
    ) -> str:
        definition = self.plan.definition
        binding = planned.rule
        handler = planned.handler
        return canonical_sha256(
            {
                "calculator": definition.calculator_id,
                "calculator_version": definition.version,
                "calculator_sha256": definition.sha256,
                "step_key": planned.step.step_key,
                "scenario": self.plan.scenario.value,
                "applied": planned.applied,
                "rule": None
                if binding is None
                else {
                    "rule_key": binding.rule_key,
                    "version": binding.version,
                    "content_sha256": binding.content_sha256,
                },
                "implementation": None
                if handler is None
                else {
                    "key": handler.implementation_key,
                    "semantics_sha256": handler.semantics_sha256,
                },
                "inputs": [[item.name, item.value, item.unit] for item in inputs],
                "parameters": [[item.name, item.value, item.unit] for item in parameters],
                "upstream": {key: self.fingerprints[key] for key in planned.step.depends_on},
            }
        )

    def gather_inputs(self, planned: PlannedStep) -> list[CalcStepInput]:
        handler = planned.handler
        rule = planned.rule
        inputs: list[CalcStepInput] = []
        names = (
            [item.name for item in rule.content.inputs]
            if rule is not None and handler is not None
            else sorted(planned.step.steps)
        )
        for name in names:
            target = handler.inputs[name] if handler is not None else None
            if name in planned.facts:
                item = planned.facts[name]
                fact_value = item.value
                raw = (
                    parse_exact(fact_value.value)
                    if isinstance(fact_value, CalcNumberValue)
                    else Decimal(fact_value.value)
                    if isinstance(fact_value, CalcCountValue)
                    else None
                )
                if raw is None:
                    raise StepExecutionError(
                        planned.step.step_key, "FactNotNumeric", f"факт {item.fact_key} не число"
                    )
                unit = numeric_unit(item)
                value, conversion = _convert(raw, unit, target)
                inputs.append(
                    CalcStepInput(
                        name=name,
                        source=CalcInputSource.FACT,
                        fact_key=item.fact_key,
                        fact_id=item.fact_id,
                        value=exact_text(value),
                        unit=target or unit,
                        conversion=conversion,
                    )
                )
                continue
            link = planned.step.steps[name]
            upstream = self.values[(link.step_key, link.output)]
            value, conversion = _convert(upstream.value, upstream.unit, target or upstream.unit)
            inputs.append(
                CalcStepInput(
                    name=name,
                    source=CalcInputSource.STEP,
                    step_key=link.step_key,
                    output=link.output,
                    value=exact_text(value),
                    unit=target or upstream.unit,
                    conversion=conversion,
                )
            )
        return inputs

    def gather_parameters(self, planned: PlannedStep) -> list[CalcStepInput]:
        if planned.rule is None or planned.handler is None:
            return []
        parameters: list[CalcStepInput] = []
        for item in planned.rule.content.parameters:
            target = planned.handler.parameters[item.name]
            value, conversion = _convert(parse_exact(item.value), item.unit, target)
            parameters.append(
                CalcStepInput(
                    name=item.name,
                    source=CalcInputSource.PARAMETER,
                    value=exact_text(value),
                    unit=target or item.unit,
                    conversion=conversion,
                )
            )
        return parameters

    def rule_ref(self, planned: PlannedStep) -> CalcRuleRef | None:
        if planned.rule is None:
            return None
        return CalcRuleRef(
            rule_key=planned.rule.rule_key,
            version=planned.rule.version,
            rule_type=planned.rule.rule_type,
            content_sha256=planned.rule.content_sha256,
            implementation_key=planned.rule.content.implementation_key or "",
        )

    def compute(
        self,
        planned: PlannedStep,
        inputs: list[CalcStepInput],
        parameters: list[CalcStepInput],
    ) -> tuple[list[CalcStepOutput], str, list[CalcRoundingRecord]]:
        handler = planned.handler
        rule = planned.rule
        step_key = planned.step.step_key
        if handler is None or rule is None:
            raise StepExecutionError(step_key, "NotPlanned", "шаг без правила или реализации")
        try:
            context = HandlerContext(
                inputs=MappingProxyType(
                    {item.name: Quantity.of(parse_exact(item.value), item.unit) for item in inputs}
                ),
                parameters=MappingProxyType(
                    {
                        item.name: Quantity.of(parse_exact(item.value), item.unit)
                        for item in parameters
                    }
                ),
            )
            result = run_handler(handler, context)
            if set(result.outputs) != set(handler.outputs):
                raise ValueError("обработчик вернул не те выходы, что объявил")
            units = {item.name: item.unit for item in rule.content.outputs}
            outputs: list[CalcStepOutput] = []
            for name in sorted(handler.outputs):
                raw = result.outputs[name].in_unit(handler.outputs[name])
                value, conversion = _convert(raw, handler.outputs[name], units[name])
                outputs.append(
                    CalcStepOutput(
                        name=name,
                        value=exact_text(value),
                        unit=units[name],
                        conversion=conversion,
                    )
                )
            roundings = [
                CalcRoundingRecord(
                    target=item.target,
                    before=exact_text(item.before),
                    after=exact_text(item.after),
                    unit=item.unit,
                    mode=item.policy.mode,
                    quantum=item.policy.quantum,
                    reason=item.reason,
                )
                for item in result.roundings
            ]
        except Inexact as error:
            raise StepExecutionError(
                step_key,
                "Inexact",
                "неточная операция без явного округления — обработчик должен округлять явно",
            ) from error
        except Exception as error:
            raise StepExecutionError(step_key, type(error).__name__, str(error)) from error
        return outputs, result.explanation, roundings

    def affected_results(self, step_key: str) -> list[str]:
        definition = self.plan.definition
        downstream = {step_key}
        changed = True
        while changed:
            changed = False
            for step in definition.steps:
                if step.step_key not in downstream and set(step.depends_on) & downstream:
                    downstream.add(step.step_key)
                    changed = True
        return [item.result_key for item in definition.results if item.step_key in downstream]

    def assumption_record(
        self,
        planned: PlannedStep,
        inputs: list[CalcStepInput],
        outputs: list[CalcStepOutput],
        reason: str,
    ) -> CalcAssumptionRecord | None:
        spec = planned.step.assumption
        if spec is None:
            return None
        base = next(item for item in inputs if item.name == spec.base_input)
        output = outputs[0]
        base_value = parse_exact(base.value)
        value = parse_exact(output.value)
        rule = planned.rule
        return CalcAssumptionRecord(
            step_key=planned.step.step_key,
            rule_key=None if rule is None else rule.rule_key,
            version=None if rule is None else rule.version,
            applied=planned.applied,
            reason=reason,
            impact=None if rule is None else rule.content.impact,
            base_value=exact_text(base_value),
            value=exact_text(value),
            unit=output.unit,
            delta=exact_text(value - base_value),
            affected_results=self.affected_results(planned.step.step_key),
        )

    def run_step(self, planned: PlannedStep) -> None:
        step = planned.step
        inputs = self.gather_inputs(planned)
        parameters = self.gather_parameters(planned)
        fingerprint = self.fingerprint(planned, inputs, parameters)
        reused_from: uuid.UUID | None = None
        roundings: list[CalcRoundingRecord] = []

        if not planned.applied:
            base = next(
                item
                for item in inputs
                if step.assumption and item.name == step.assumption.base_input
            )
            outputs = [CalcStepOutput(name=step.outputs[0], value=base.value, unit=base.unit)]
            status = CalcStepStatus.NOT_APPLIED
            unit_title = UNITS[base.unit].title if base.unit is not None else ""
            shown = f"{ru_number(parse_exact(base.value))} {unit_title}".rstrip()
            explanation = f"{planned.not_applied_reason}: {shown}"
            reason = planned.not_applied_reason or ""
        else:
            prior = self.reuse.get(fingerprint)
            if prior is not None:
                outputs, explanation = list(prior.outputs), prior.explanation
                roundings = list(prior.roundings)
                status, reused_from = CalcStepStatus.REUSED, prior.run_id
            else:
                outputs, explanation, roundings = self.compute(planned, inputs, parameters)
                status = CalcStepStatus.EXECUTED
            reason = (
                f"Сценарий {self.plan.scenario.value} допускает тендерные допущения, шаг "
                f"«{step.title}» допускает допущение, версия правила утверждена"
            )
        assumption = self.assumption_record(planned, inputs, outputs, reason)
        if assumption is not None:
            self.assumptions.append(assumption)
        for output in outputs:
            self.values[(step.step_key, output.name)] = _Value(
                parse_exact(output.value), output.unit
            )
        self.fingerprints[step.step_key] = fingerprint
        self.records.append(
            CalcStepRead(
                step_key=step.step_key,
                position=planned.position,
                title=step.title,
                status=status,
                rule=self.rule_ref(planned),
                inputs=inputs,
                parameters=parameters,
                outputs=outputs,
                roundings=roundings,
                explanation=explanation,
                fingerprint=fingerprint,
                reused_from_run_id=reused_from,
                assumption=assumption,
            )
        )

    def results(self) -> tuple[CalcResultRead, ...]:
        definition = self.plan.definition
        found: list[CalcResultRead] = []
        for item in definition.results:
            source = self.values[(item.step_key, item.output)]
            value = source.value
            rounding: CalcRoundingRecord | None = None
            if item.rounding is not None:
                rounded = apply_rounding(value, item.rounding)
                rounding = CalcRoundingRecord(
                    target=item.result_key,
                    before=exact_text(value),
                    after=exact_text(rounded),
                    unit=source.unit,
                    mode=item.rounding.mode,
                    quantum=item.rounding.quantum,
                    reason="округление итогового значения по определению калькулятора",
                )
                value = rounded
            found.append(
                CalcResultRead(
                    run_id=self.run_id,
                    result_key=item.result_key,
                    title=item.title,
                    value=exact_text(value),
                    unit=source.unit,
                    category=item.category,
                    discipline=definition.discipline,
                    system_code=self.plan.scope.system_code,
                    scenario=self.plan.scenario,
                    step_key=item.step_key,
                    output=item.output,
                    rounding=rounding,
                )
            )
        return tuple(found)


def execute(plan: Plan, run_id: uuid.UUID, reuse: Mapping[str, PriorStep]) -> Execution:
    """Исполнение действительного плана. План с причинами блокировки сюда не приходит."""
    if not plan.valid:
        raise ValueError("исполнять можно только действительный план")
    executor = _Executor(plan, run_id, reuse)
    for planned in plan.steps:
        executor.run_step(planned)
    results = executor.results()
    return Execution(
        steps=tuple(executor.records),
        results=results,
        assumptions=tuple(executor.assumptions),
        result_sha256=result_sha256(plan.definition, plan.scenario, results),
    )
