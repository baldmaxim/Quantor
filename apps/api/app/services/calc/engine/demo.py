"""Демонстрационный калькулятор — доказательство архитектуры ядра, не расчёт ВК.

`test.vertical_length@1`: длина по высоте этажа и этажности → × число стояков → тендерный
запас (только в TENDER_SAFE). Формулы синтетические и не являются инженерными правилами:
правил `test.*` в рабочей базе нет, без них запуск честно блокируется. Утверждённые тестовые
правила заводят только тесты.
"""

from __future__ import annotations

from typing import Final

from app.contracts.calc.engine import CalcRoundingPolicy
from app.contracts.calc.enums import (
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcResultCategory,
    CalcRoundingMode,
    CalcRuleType,
    CalcScenario,
)
from app.contracts.calc.units import UNITS
from app.services.calc.engine.calculators import (
    AssumptionSpec,
    CalculatorDef,
    FactBinding,
    ResultDef,
    StepBinding,
    StepDef,
)
from app.services.calc.engine.handlers import (
    GoldenCase,
    HandlerContext,
    HandlerResult,
    HandlerSpec,
)
from app.services.calc.engine.numbers import ru_number
from app.services.calc.engine.quantity import Quantity


def _show(quantity: Quantity, unit: str | None) -> str:
    number = ru_number(quantity.in_unit(unit))
    return number if unit is None else f"{number} {UNITS[unit].title}"


def _vertical_length(context: HandlerContext) -> HandlerResult:
    height = context.inputs["floor_height"]
    floors = context.inputs["floors"]
    length = height * floors
    return HandlerResult(
        outputs={"length": length},
        explanation=(
            f"Высота этажа {_show(height, 'm')} × {_show(floors, 'floor')} = {_show(length, 'm')}"
        ),
    )


def _multiply_by_count(context: HandlerContext) -> HandlerResult:
    length = context.inputs["length"]
    risers = context.inputs["risers"]
    total = length * risers
    return HandlerResult(
        outputs={"total": total},
        explanation=f"{_show(length, 'm')} × {_show(risers, 'riser')} = {_show(total, 'm')}",
    )


def _reserve_factor(context: HandlerContext) -> HandlerResult:
    base = context.inputs["base"]
    factor = context.parameters["factor"]
    value = base * factor
    return HandlerResult(
        outputs={"value": value},
        explanation=(
            f"Тендерный запас: {_show(base, 'm')} × {_show(factor, None)} = {_show(value, 'm')}"
        ),
    )


DEMO_HANDLERS: Final = (
    HandlerSpec(
        implementation_key="test.vertical_length.v1",
        title="Демо: высота этажа × этажность",
        inputs={"floor_height": "m", "floors": "floor"},
        parameters={},
        outputs={"length": "m"},
        compute=_vertical_length,
        golden=(
            GoldenCase({"floor_height": "3.3", "floors": "24"}, {}, {"length": "79.2"}),
            GoldenCase({"floor_height": "2.95", "floors": "3"}, {}, {"length": "8.85"}),
        ),
    ),
    HandlerSpec(
        implementation_key="test.multiply_by_count.v1",
        title="Демо: длина × число стояков",
        inputs={"length": "m", "risers": "riser"},
        parameters={},
        outputs={"total": "m"},
        compute=_multiply_by_count,
        golden=(GoldenCase({"length": "79.2", "risers": "2"}, {}, {"total": "158.4"}),),
    ),
    HandlerSpec(
        implementation_key="test.reserve_factor.v1",
        title="Демо: тендерный запас множителем",
        inputs={"base": "m"},
        parameters={"factor": None},
        outputs={"value": "m"},
        compute=_reserve_factor,
        golden=(GoldenCase({"base": "158.4"}, {"factor": "1.07"}, {"value": "169.488"}),),
    ),
)

_GEOMETRY: Final = frozenset({CalcRuleType.GEOMETRY, CalcRuleType.PHYSICS})

DEMO_CALCULATOR: Final = CalculatorDef(
    calculator_id="test.vertical_length",
    version=1,
    title="ДЕМО: вертикальная длина — проверка ядра, не расчёт ВК",
    kind=CalcCalculatorKind.DEMO,
    discipline=CalcDiscipline.VK,
    systems=("В1",),
    stage=CalcDocumentStage.P,
    scenarios=frozenset(CalcScenario),
    scope_fields=("building", "floor", "discipline", "system_code"),
    steps=(
        StepDef(
            step_key="vertical_length",
            title="Вертикальная длина",
            rule_key="test.geometry.vertical_length",
            allowed_rule_types=_GEOMETRY,
            outputs=("length",),
            facts={
                "floor_height": FactBinding("floor.height", ("building", "floor")),
                "floors": FactBinding("building.floors_above_ground", ("building",)),
            },
        ),
        StepDef(
            step_key="total_length",
            title="Длина по всем стоякам",
            rule_key="test.geometry.total_length",
            allowed_rule_types=_GEOMETRY,
            outputs=("total",),
            facts={
                "risers": FactBinding(
                    "system.risers_count", ("building", "discipline", "system_code")
                )
            },
            steps={"length": StepBinding("vertical_length", "length")},
        ),
        StepDef(
            step_key="total_with_reserve",
            title="Тендерный запас",
            rule_key="test.tender.length_reserve",
            allowed_rule_types=frozenset({CalcRuleType.TENDER_ASSUMPTION}),
            outputs=("value",),
            steps={"base": StepBinding("total_length", "total")},
            assumption=AssumptionSpec(base_input="base"),
        ),
    ),
    results=(
        ResultDef(
            result_key="demo.vertical_length",
            title="Вертикальная длина (демо)",
            step_key="vertical_length",
            output="length",
            category=CalcResultCategory.INTERMEDIATE,
        ),
        ResultDef(
            result_key="demo.total_length",
            title="Длина по всем стоякам (демо)",
            step_key="total_with_reserve",
            output="value",
            category=CalcResultCategory.ENGINEERING,
            rounding=CalcRoundingPolicy(mode=CalcRoundingMode.CEILING, quantum="0.1"),
        ),
    ),
)
