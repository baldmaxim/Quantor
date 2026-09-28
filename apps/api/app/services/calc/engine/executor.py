"""Исполнение плана: шаги по порядку графа, переводы единиц, допущения, результаты.

Чистая функция: план, сценарий и карта прежних шагов для повторного использования — на входе;
записи шагов и результатов с отпечатками — на выходе. База, запрос и реестры сюда не приходят.

- Каждый перевод единиц записывается в шаг.
- Промежуточные значения не округляются; округляется только итог, если его определение
  калькулятора это требует, и округление видно в цепочке.
- Отпечаток шага — калькулятор, реализация и её семантика, точная версия правила, входы в
  рабочих единицах, параметры, сценарий и отпечатки шагов-источников. Совпал с шагом прежнего
  успешного запуска того же проекта — результат берётся оттуда, и это видно (`REUSED`).
- Шаг-примитив (PROMPT 06) исполняется так же, но без правила: члены набора записываются
  входами шага. Если набор неполон (`InsufficientInputError`), шаг не определён — причина
  записывается, зависимые шаги не исполняются, независимые идут дальше.
- Любая другая ошибка обработчика — `StepExecutionError`: запуск станет FAILED, а не «примерно
  так».
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, Inexact
from types import MappingProxyType

from app.contracts.calc.engine import (
    CalcAssumptionRecord,
    CalcBlockingReason,
    CalcPrimitiveRef,
    CalcResultRead,
    CalcRoundingRecord,
    CalcRuleRef,
    CalcStepInput,
    CalcStepOutput,
    CalcStepRead,
)
from app.contracts.calc.enums import CalcBlockCode, CalcInputSource, CalcStepStatus
from app.contracts.calc.units import UNITS
from app.services.calc.engine.handlers import (
    HandlerContext,
    HandlerSpec,
    InsufficientInputError,
    SeriesMember,
    run_handler,
)
from app.services.calc.engine.numbers import apply_rounding, exact_text, parse_exact, ru_number
from app.services.calc.engine.plan_types import Plan, PlannedStep, reason
from app.services.calc.engine.quantity import Quantity
from app.services.calc.engine.step_inputs import (
    convert,
    fact_input,
    result_sha256,
    step_fingerprint,
)

__all__ = ["Execution", "PriorStep", "StepExecutionError", "execute", "result_sha256"]


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
    gaps: tuple[CalcBlockingReason, ...] = ()
    """Шаги, которые не определились: набор фактов неполон или противоречив."""


@dataclass(frozen=True, slots=True)
class _Value:
    value: Decimal
    unit: str | None


class _Executor:
    def __init__(self, plan: Plan, run_id: uuid.UUID, reuse: Mapping[str, PriorStep]) -> None:
        self.plan = plan
        self.run_id = run_id
        self.reuse = reuse
        self.values: dict[tuple[str, str], _Value] = {}
        self.fingerprints: dict[str, str] = {}
        self.records: list[CalcStepRead] = []
        self.assumptions: list[CalcAssumptionRecord] = []
        self.gaps: list[CalcBlockingReason] = []
        self.undetermined: set[str] = set()

    def gather_inputs(self, planned: PlannedStep) -> list[CalcStepInput]:
        handler = planned.handler
        rule = planned.rule
        inputs: list[CalcStepInput] = []
        if planned.primitive and handler is not None:
            names = sorted(handler.inputs)
        elif rule is not None and handler is not None:
            names = [item.name for item in rule.content.inputs]
        else:
            names = sorted(planned.step.steps)
        for name in names:
            target = handler.inputs[name] if handler is not None else None
            if name in planned.facts:
                try:
                    inputs.append(fact_input(name, planned.facts[name], target))
                except ValueError as error:
                    raise StepExecutionError(
                        planned.step.step_key, "FactNotNumeric", str(error)
                    ) from error
                continue
            link = planned.step.steps[name]
            upstream = self.values[(link.step_key, link.output)]
            value, conversion = convert(upstream.value, upstream.unit, target or upstream.unit)
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
        if handler is not None:
            for series_name, members in sorted(planned.series.items()):
                target = handler.series[series_name]
                binding = planned.step.series[series_name]
                for item in members:
                    member = str(getattr(item.subject, binding.member_field))
                    recorded = fact_input(f"{series_name}[{member}]", item, target)
                    inputs.append(
                        recorded.model_copy(update={"series": series_name, "member": member})
                    )
        return inputs

    def gather_parameters(self, planned: PlannedStep) -> list[CalcStepInput]:
        if planned.rule is None or planned.handler is None:
            return []
        parameters: list[CalcStepInput] = []
        for item in planned.rule.content.parameters:
            target = planned.handler.parameters[item.name]
            value, conversion = convert(parse_exact(item.value), item.unit, target)
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
        step_key = planned.step.step_key
        if handler is None or (planned.rule is None and not planned.primitive):
            raise StepExecutionError(step_key, "NotPlanned", "шаг без правила или реализации")
        units = (
            dict(handler.outputs)
            if planned.rule is None
            else {item.name: item.unit for item in planned.rule.content.outputs}
        )
        try:
            result = run_handler(handler, _context(handler, inputs, parameters))
            if set(result.outputs) != set(handler.outputs):
                raise ValueError("обработчик вернул не те выходы, что объявил")
            outputs: list[CalcStepOutput] = []
            for name in sorted(handler.outputs):
                raw = result.outputs[name].in_unit(handler.outputs[name])
                value, conversion = convert(raw, handler.outputs[name], units[name])
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
        except InsufficientInputError:
            raise
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
        reason_text: str,
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
            reason=reason_text,
            impact=None if rule is None else rule.content.impact,
            base_value=exact_text(base_value),
            value=exact_text(value),
            unit=output.unit,
            delta=exact_text(value - base_value),
            affected_results=self.affected_results(planned.step.step_key),
        )

    def run_step(self, planned: PlannedStep) -> None:
        step = planned.step
        if set(step.depends_on) & self.undetermined:
            self.undetermined.add(step.step_key)
            return
        inputs = self.gather_inputs(planned)
        parameters = self.gather_parameters(planned)
        fingerprint = step_fingerprint(self.plan, planned, inputs, parameters, self.fingerprints)
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
            reason_text = planned.not_applied_reason or ""
        else:
            prior = self.reuse.get(fingerprint)
            if prior is not None:
                outputs, explanation = list(prior.outputs), prior.explanation
                roundings = list(prior.roundings)
                status, reused_from = CalcStepStatus.REUSED, prior.run_id
            else:
                try:
                    outputs, explanation, roundings = self.compute(planned, inputs, parameters)
                except InsufficientInputError as error:
                    self.undetermined.add(step.step_key)
                    self.gaps.append(
                        reason(
                            CalcBlockCode.INPUT_INCOMPLETE,
                            f"«{step.title}» не определён: {error}",
                            step_key=step.step_key,
                        )
                    )
                    return
                status = CalcStepStatus.EXECUTED
            reason_text = (
                f"Сценарий {self.plan.scenario.value} допускает тендерные допущения, шаг "
                f"«{step.title}» допускает допущение, версия правила утверждена"
            )
        assumption = self.assumption_record(planned, inputs, outputs, reason_text)
        if assumption is not None:
            self.assumptions.append(assumption)
        for output in outputs:
            self.values[(step.step_key, output.name)] = _Value(
                parse_exact(output.value), output.unit
            )
        self.fingerprints[step.step_key] = fingerprint
        handler = planned.handler
        self.records.append(
            CalcStepRead(
                step_key=step.step_key,
                position=planned.position,
                title=step.title,
                status=status,
                rule=self.rule_ref(planned),
                primitive=CalcPrimitiveRef(
                    implementation_key=handler.implementation_key, title=handler.title
                )
                if planned.primitive and handler is not None
                else None,
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
            source = self.values.get((item.step_key, item.output))
            if source is None:
                continue  # шаг заблокирован или не определён — результата нет, а не ноль
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


def _context(
    handler: HandlerSpec, inputs: list[CalcStepInput], parameters: list[CalcStepInput]
) -> HandlerContext:
    series: dict[str, list[SeriesMember]] = {name: [] for name in handler.series}
    scalars: dict[str, Quantity] = {}
    for item in inputs:
        quantity = Quantity.of(parse_exact(item.value), item.unit)
        if item.series is not None and item.member is not None:
            series[item.series].append(SeriesMember(item.member, quantity))
        else:
            scalars[item.name] = quantity
    return HandlerContext(
        inputs=MappingProxyType(scalars),
        parameters=MappingProxyType(
            {item.name: Quantity.of(parse_exact(item.value), item.unit) for item in parameters}
        ),
        series=MappingProxyType({name: tuple(members) for name, members in series.items()}),
    )


def execute(plan: Plan, run_id: uuid.UUID, reuse: Mapping[str, PriorStep]) -> Execution:
    """Исполнение плана, в котором есть что исполнять. Заблокированные шаги в план не входят."""
    if not plan.runnable:
        raise ValueError("исполнять можно только действительный план — план с шагами")
    executor = _Executor(plan, run_id, reuse)
    for planned in plan.steps:
        executor.run_step(planned)
    results = executor.results()
    return Execution(
        steps=tuple(executor.records),
        results=results,
        assumptions=tuple(executor.assumptions),
        result_sha256=result_sha256(plan.definition, plan.scenario, results),
        gaps=tuple(executor.gaps),
    )
