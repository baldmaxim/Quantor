"""Демо для синтеза структуры (PROMPT 05) — синтетика, не инженерная методика ВК.

- Калькулятор `test.riser_demand@1`: диапазон числа стояков по числу квартир и тестовой
  «вместимости стояка» — `ceil(квартир / макс)` … `ceil(квартир / мин)`. Округление вверх —
  явное, внутри обработчика, и видно в шаге.
- Обработчики правил синтеза: число ветвей на стояк и этаж, выбор верхней границы диапазона,
  тендерный резерв стояков. Утверждённые версии этих правил заводят только тесты.
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
from app.services.calc.engine.calculators import CalculatorDef, FactBinding, ResultDef, StepDef
from app.services.calc.engine.handlers import (
    GoldenCase,
    HandlerContext,
    HandlerResult,
    HandlerRounding,
    HandlerSpec,
)
from app.services.calc.engine.numbers import ru_number

_UP: Final = CalcRoundingPolicy(mode=CalcRoundingMode.CEILING, quantum="1")
_WHOLE: Final = "число стояков — целое: частное округляется вверх"


def _riser_range(context: HandlerContext) -> HandlerResult:
    apartments = context.inputs["apartments"]
    low = context.parameters["per_riser_min"]
    high = context.parameters["per_riser_max"]
    risers_min, quotient_min = apartments.divided_rounded(high, _UP)
    risers_max, quotient_max = apartments.divided_rounded(low, _UP)
    count = ru_number(apartments.value)
    return HandlerResult(
        outputs={"risers_min": risers_min, "risers_max": risers_max},
        explanation=(
            f"{count} кв. / {ru_number(high.value)} кв. на стояк = "
            f"{ru_number(quotient_min)} → {ru_number(risers_min.value)} ст.; "
            f"{count} кв. / {ru_number(low.value)} кв. на стояк = "
            f"{ru_number(quotient_max)} → {ru_number(risers_max.value)} ст."
        ),
        roundings=(
            HandlerRounding("risers_min", quotient_min, risers_min.value, "riser", _UP, _WHOLE),
            HandlerRounding("risers_max", quotient_max, risers_max.value, "riser", _UP, _WHOLE),
        ),
    )


def _branches_per_floor(context: HandlerContext) -> HandlerResult:
    branches = context.parameters["per_floor"]
    return HandlerResult(
        outputs={"branches": branches},
        explanation=f"Ветвей на стояк на этаже: {ru_number(branches.value)}",
    )


def _select_upper_count(context: HandlerContext) -> HandlerResult:
    low = context.inputs["count_min"]
    high = context.inputs["count_max"]
    return HandlerResult(
        outputs={"count": high},
        explanation=(
            f"Из диапазона {ru_number(low.value)}–{ru_number(high.value)} выбрана верхняя граница "
            f"{ru_number(high.value)}"
        ),
    )


def _reserve_count(context: HandlerContext) -> HandlerResult:
    reserve = context.parameters["reserve_count"]
    return HandlerResult(
        outputs={"reserve": reserve},
        explanation=f"Тендерный резерв: {ru_number(reserve.value)} ст.",
    )


STRUCTURE_HANDLERS: Final = (
    HandlerSpec(
        implementation_key="test.riser_range.v1",
        title="Демо: диапазон числа стояков",
        inputs={"apartments": "apartment"},
        parameters={"per_riser_min": None, "per_riser_max": None},
        outputs={"risers_min": "riser", "risers_max": "riser"},
        compute=_riser_range,
        golden=(
            GoldenCase(
                {"apartments": "96"},
                {"per_riser_min": "20", "per_riser_max": "24"},
                {"risers_min": "4", "risers_max": "5"},
            ),
            GoldenCase(
                {"apartments": "96"},
                {"per_riser_min": "24", "per_riser_max": "24"},
                {"risers_min": "4", "risers_max": "4"},
            ),
            GoldenCase(
                {"apartments": "100"},
                {"per_riser_min": "20", "per_riser_max": "24"},
                {"risers_min": "5", "risers_max": "5"},
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="test.branches_per_floor.v1",
        title="Демо: ветвей на стояк на этаже",
        inputs={},
        parameters={"per_floor": None},
        outputs={"branches": None},
        compute=_branches_per_floor,
        golden=(GoldenCase({}, {"per_floor": "1"}, {"branches": "1"}),),
    ),
    HandlerSpec(
        implementation_key="test.select_upper_count.v1",
        title="Демо: выбор верхней границы диапазона",
        inputs={"count_min": "riser", "count_max": "riser"},
        parameters={},
        outputs={"count": "riser"},
        compute=_select_upper_count,
        golden=(GoldenCase({"count_min": "4", "count_max": "5"}, {}, {"count": "5"}),),
    ),
    HandlerSpec(
        implementation_key="test.reserve_count.v1",
        title="Демо: тендерный резерв стояков",
        inputs={},
        parameters={"reserve_count": "riser"},
        outputs={"reserve": "riser"},
        compute=_reserve_count,
        golden=(GoldenCase({}, {"reserve_count": "1"}, {"reserve": "1"}),),
    ),
)

RISER_DEMAND_CALCULATOR: Final = CalculatorDef(
    calculator_id="test.riser_demand",
    version=1,
    title="ДЕМО: диапазон числа стояков — проверка синтеза, не расчёт ВК",
    kind=CalcCalculatorKind.DEMO,
    discipline=CalcDiscipline.VK,
    systems=("В1",),
    stage=CalcDocumentStage.P,
    scenarios=frozenset(CalcScenario),
    scope_fields=("building", "floor", "discipline", "system_code"),
    steps=(
        StepDef(
            step_key="riser_range",
            title="Диапазон числа стояков",
            rule_key="test.engineering.riser_range",
            allowed_rule_types=frozenset(
                {CalcRuleType.ENGINEERING, CalcRuleType.GEOMETRY, CalcRuleType.PHYSICS}
            ),
            outputs=("risers_min", "risers_max"),
            facts={"apartments": FactBinding("building.apartments_total", ("building",))},
        ),
    ),
    results=(
        ResultDef(
            result_key="demo.risers_min",
            title="Стояков не меньше (демо)",
            step_key="riser_range",
            output="risers_min",
            category=CalcResultCategory.ENGINEERING,
        ),
        ResultDef(
            result_key="demo.risers_max",
            title="Стояков не больше (демо)",
            step_key="riser_range",
            output="risers_max",
            category=CalcResultCategory.ENGINEERING,
        ),
    ),
)
