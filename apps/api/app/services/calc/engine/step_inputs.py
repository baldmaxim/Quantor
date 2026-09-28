"""Входы шага, переводы единиц и отпечатки — общие части исполнителя. Чистые функции."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from app.contracts.calc.engine import (
    CalcConversion,
    CalcResultRead,
    CalcSnapshotItem,
    CalcStepInput,
)
from app.contracts.calc.enums import CalcInputSource, CalcScenario
from app.contracts.calc.units import to_canonical
from app.contracts.calc.values import CalcCountValue, CalcNumberValue
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.numbers import exact_text, parse_exact
from app.services.calc.engine.plan_types import Plan, PlannedStep, numeric_unit


def convert(
    value: Decimal, unit: str | None, target: str | None
) -> tuple[Decimal, CalcConversion | None]:
    """Перевод в рабочую единицу обработчика — всегда с записью, если что-то переводилось."""
    if unit == target or unit is None or target is None:
        return value, None
    converted = to_canonical(value, unit, target)
    return converted, CalcConversion(
        from_value=exact_text(value),
        from_unit=unit,
        to_value=exact_text(converted),
        to_unit=target,
    )


def fact_input(name: str, item: CalcSnapshotItem, target: str | None) -> CalcStepInput:
    """Вход шага из факта снимка. ValueError — значение не число."""
    fact_value = item.value
    if isinstance(fact_value, CalcNumberValue):
        raw = parse_exact(fact_value.value)
    elif isinstance(fact_value, CalcCountValue):
        raw = Decimal(fact_value.value)
    else:
        raise ValueError(f"факт {item.fact_key} не число")
    unit = numeric_unit(item)
    value, conversion = convert(raw, unit, target)
    return CalcStepInput(
        name=name,
        source=CalcInputSource.FACT,
        fact_key=item.fact_key,
        fact_id=item.fact_id,
        value=exact_text(value),
        unit=target or unit,
        conversion=conversion,
    )


def step_fingerprint(
    plan: Plan,
    planned: PlannedStep,
    inputs: list[CalcStepInput],
    parameters: list[CalcStepInput],
    upstream: Mapping[str, str],
) -> str:
    """Отпечаток шага: у шагов с правилом — тот же состав, что в PROMPT 04."""
    definition = plan.definition
    binding = planned.rule
    handler = planned.handler
    return canonical_sha256(
        {
            "calculator": definition.calculator_id,
            "calculator_version": definition.version,
            "calculator_sha256": definition.sha256,
            "step_key": planned.step.step_key,
            "scenario": plan.scenario.value,
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
            "upstream": {key: upstream[key] for key in planned.step.depends_on},
        }
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
