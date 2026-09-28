"""Расчётное ядро без базы (ADR-0030, PROMPT 04).

Планирование, граф, единицы, округление, сценарии, допущения, повторное использование,
реестр обработчиков и объяснение — на синтетике: демо-калькулятор, правила `test.*`, снимок
фактов из фабрик. Запуски через базу и API — в `test_calc_runs_api.py`.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from app.contracts.calc.engine import CalcRoundingPolicy, CalcRunRead, CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcCalculatorKind,
    CalcResolutionState,
    CalcRoundingMode,
    CalcRuleType,
    CalcScenario,
    CalcSourceClass,
    CalcStepStatus,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcCountValue, CalcNumberValue, CalcRangeValue
from app.core.features import REGISTRY as FEATURES
from app.errors import InvariantError
from app.models import CalcFact
from app.services.calc.engine import handlers as handlers_module
from app.services.calc.engine import inputs
from app.services.calc.engine.calculators import (
    CalculatorDef,
    DefinitionError,
    StepBinding,
    build_registry,
    definition_problems,
    topological_order,
)
from app.services.calc.engine.catalog import CALCULATORS, HANDLERS
from app.services.calc.engine.demo import DEMO_CALCULATOR
from app.services.calc.engine.executor import (
    PriorStep,
    StepExecutionError,
    execute,
)
from app.services.calc.engine.handlers import (
    GoldenCase,
    HandlerContext,
    HandlerResult,
    check_golden,
)
from app.services.calc.engine.numbers import apply_rounding
from app.services.calc.engine.plan_types import Absence, Plan
from app.services.calc.engine.planner import plan
from app.services.calc.engine.quantity import Quantity, UnitMismatchError
from app.services.calc.engine.trace import compare, explain
from app.services.calc.facts.resolution import KeyResolution, Resolution
from tests.calc_engine_fixtures import (
    SCOPE,
    demo_facts,
    demo_rules,
    reserve_rule,
    resolved,
    snapshot_item,
    total_length_rule,
    vertical_length_rule,
)

ENGINE = Path(__file__).resolve().parents[1] / "app" / "services" / "calc" / "engine"
PURE_MODULES = (
    "numbers.py",
    "hashing.py",
    "quantity.py",
    "handlers.py",
    "calculators.py",
    "policy.py",
    "planner.py",
    "plan_types.py",
    "executor.py",
    "trace.py",
    "demo.py",
)
HEIGHT_KEY = "floor.height@building=1|floor=2..24"


def _plan(
    scenario: CalcScenario = CalcScenario.EXPECTED,
    *,
    facts: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    definition: CalculatorDef = DEMO_CALCULATOR,
    scope: CalcFactSubject = SCOPE,
) -> Plan:
    return plan(
        definition,
        scenario,
        scope,
        demo_facts() if facts is None else facts,
        demo_rules() if rules is None else rules,
        HANDLERS,
    )


def _codes(result: Plan) -> list[CalcBlockCode]:
    return [reason.code for reason in result.reasons]


def _run(scenario: CalcScenario = CalcScenario.EXPECTED, **kwargs: Any) -> Any:
    result = _plan(scenario, **kwargs)
    assert result.valid, [reason.message for reason in result.reasons]
    return execute(result, uuid.uuid4(), {})


def _value(execution: Any, result_key: str) -> str:
    return next(item.value for item in execution.results if item.result_key == result_key)


def _run_read(execution: Any, planned: Plan, run_id: uuid.UUID | None = None) -> CalcRunRead:
    from datetime import UTC, date, datetime

    from app.services.calc.engine.inputs import snapshot_of
    from app.services.calc.engine.runs import versions

    return CalcRunRead(
        id=run_id or uuid.uuid4(),
        project_id=uuid.uuid4(),
        calculator_id=planned.definition.calculator_id,
        calculator_version=planned.definition.version,
        calculator_title=planned.definition.title,
        scenario=planned.scenario,
        status="SUCCEEDED",
        results_count=len(execution.results),
        blocking=None,
        result_sha256=execution.result_sha256,
        created_by=None,
        created_at=datetime(2026, 9, 28, tzinfo=UTC),
        scope=planned.scope,
        effective_on=date(2026, 9, 28),
        idempotency_key=None,
        calculator_sha256=planned.definition.sha256,
        versions=versions(),
        snapshot=snapshot_of(planned.snapshot_items),
        rule_bindings=list(planned.bindings),
        rule_bindings_sha256="0" * 64,
        blocking_reasons=[],
        failure=None,
        assumptions=list(execution.assumptions),
        warnings=list(planned.warnings),
        steps=list(execution.steps),
        results=list(execution.results),
    )


# ------------------------------------------------------------------------ детерминизм (T01)


class TestDeterminism:
    def test_t01_same_inputs_same_result(self) -> None:
        first = _run()
        second = _run()
        assert first.result_sha256 == second.result_sha256
        assert [step.fingerprint for step in first.steps] == [
            step.fingerprint for step in second.steps
        ]
        assert _value(first, "demo.vertical_length") == "79.2"
        assert _value(first, "demo.total_length") == "158.4"

    def test_changed_fact_changes_hash(self) -> None:
        """Этажность 24 → 25: 79,2 м → 82,5 м, другой отпечаток результата."""
        before = _run()
        after = _run(facts=demo_facts(floors=25))
        assert _value(after, "demo.vertical_length") == "82.5"
        assert before.result_sha256 != after.result_sha256


# ------------------------------------------------------------- нехватка данных (T02–T06, A–C)


class TestMissingData:
    def test_t02_missing_required_fact_blocks(self) -> None:
        facts = demo_facts()
        del facts[HEIGHT_KEY]
        result = _plan(facts=facts)
        assert _codes(result) == [CalcBlockCode.FACT_MISSING]
        assert result.reasons[0].fact_key == HEIGHT_KEY
        assert result.steps == ()

    @pytest.mark.parametrize(
        "absence",
        [
            Absence(CalcBlockCode.FACT_MISSING, "значения нет"),
            Absence(CalcBlockCode.FACT_CONFLICT, "источники расходятся"),
            Absence(CalcBlockCode.FACT_EXCLUDED, "только ВОР"),
            Absence(CalcBlockCode.FACT_DECISION_STALE, "решение устарело"),
        ],
    )
    def test_t03_t04_absence_is_never_zero(self, absence: Absence) -> None:
        """Сценарий A и B: «не определено» и конфликт — блокировка, не 0 и не «вероятное»."""
        facts: dict[str, Any] = dict(demo_facts())
        facts[HEIGHT_KEY] = absence
        result = _plan(facts=facts)
        assert not result.valid
        assert _codes(result) == [absence.code]
        with pytest.raises(ValueError, match="действительный план"):
            execute(result, uuid.uuid4(), {})

    def test_t03_range_is_not_an_exact_number(self) -> None:
        facts = demo_facts()
        facts[HEIGHT_KEY] = snapshot_item(
            "floor.height",
            CalcFactSubject(building="1", floor="2..24"),
            CalcRangeValue(low="3", high="3.3", unit="m"),
        )
        assert _codes(_plan(facts=facts)) == [CalcBlockCode.FACT_NOT_EXACT]

    def _resolution(self, state: CalcResolutionState, excluded: bool = False) -> KeyResolution:
        return KeyResolution(
            fact_key=HEIGHT_KEY,
            fact_type="floor.height",
            subject_key="building=1|floor=2..24",
            resolution=Resolution(
                state=state,
                value=None,
                chosen=None,
                claim_ids=(),
                excluded_ids=(uuid.uuid4(),) if excluded else (),
                claim_set_hash="",
                disagreement=state is not CalcResolutionState.MISSING,
                warnings=(),
            ),
        )

    @pytest.mark.parametrize(
        ("state", "excluded", "code"),
        [
            (CalcResolutionState.UNRESOLVED, False, CalcBlockCode.FACT_CONFLICT),
            (CalcResolutionState.AUTO_PREFERRED, False, CalcBlockCode.FACT_CONFLICT),
            (CalcResolutionState.DECIDED_STALE, False, CalcBlockCode.FACT_DECISION_STALE),
            (CalcResolutionState.MISSING, True, CalcBlockCode.FACT_EXCLUDED),
            (CalcResolutionState.MISSING, False, CalcBlockCode.FACT_MISSING),
        ],
    )
    def test_t04_snapshot_admits_only_settled_values(
        self, state: CalcResolutionState, excluded: bool, code: CalcBlockCode
    ) -> None:
        """Значение по политике при открытом конфликте в снимок не попадает (сценарий B)."""
        absence = inputs._absence(self._resolution(state, excluded))
        assert absence is not None and absence.code is code

    @pytest.mark.parametrize("source_class", [CalcSourceClass.CUSTOMER_VOR, CalcSourceClass.MANUAL])
    def test_t05_t06_ineligible_claim_never_enters_snapshot(
        self, source_class: CalcSourceClass
    ) -> None:
        """Утверждение, не допущенное к расчёту, в снимке — нарушение инварианта, а не значение."""
        fact = CalcFact(
            id=uuid.uuid4(),
            fact_type="floor.height",
            source_class=source_class,
            calculation_eligible=False,
            value={"kind": "NUMBER", "value": "3.3", "unit": "m"},
        )
        with pytest.raises(InvariantError, match="не допущенное к расчёту"):
            inputs._item(self._resolution(CalcResolutionState.SINGLE), fact)

    @pytest.mark.parametrize(
        "state",
        [
            CalcResolutionState.SINGLE,
            CalcResolutionState.CORROBORATED,
            CalcResolutionState.DECIDED,
        ],
    )
    def test_settled_states_are_admitted(self, state: CalcResolutionState) -> None:
        assert inputs._absence(self._resolution(state)) is None


# ------------------------------------------------------------------------- правила (T07–T11)


class TestRules:
    @pytest.mark.parametrize(
        "code",
        [
            CalcBlockCode.RULE_NOT_FOUND,
            CalcBlockCode.RULE_NOT_APPROVED,
            CalcBlockCode.RULE_NOT_EFFECTIVE,
        ],
    )
    def test_rule_absence_blocks_without_fallback(self, code: CalcBlockCode) -> None:
        """Нет утверждённой версии — блокировка, а не коэффициент старого портала (T30, D)."""
        rules: dict[str, Any] = demo_rules()
        rules["test.geometry.vertical_length"] = Absence(code, "нет версии")
        result = _plan(rules=rules)
        assert _codes(result) == [code]
        # Зависимый шаг не получает второй причины: блокирован уже источник.
        assert [reason.step_key for reason in result.reasons] == ["vertical_length"]

    def test_t11_exact_version_is_bound(self) -> None:
        rules = demo_rules()
        rules["test.geometry.vertical_length"] = resolved(
            "test.geometry.vertical_length", vertical_length_rule(), version=3
        )
        result = _plan(rules=rules)
        binding = next(item for item in result.bindings if item.step_key == "vertical_length")
        assert binding.version == 3
        assert binding.content_sha256 == rules["test.geometry.vertical_length"].content_sha256
        assert (
            binding.handler_semantics_sha256 == HANDLERS["test.vertical_length.v1"].semantics_sha256
        )
        assert binding.content.formula == "L = h × n"

    def test_missing_implementation_blocks(self) -> None:
        rules = demo_rules(
            vertical_length=vertical_length_rule(implementation_key="test.absent.v1")
        )
        assert _codes(_plan(rules=rules)) == [CalcBlockCode.IMPLEMENTATION_MISSING]

    def test_rule_contract_must_match_handler_and_bindings(self) -> None:
        renamed = vertical_length_rule()
        renamed["inputs"][1] = {**renamed["inputs"][1], "name": "storeys"}
        renamed["dimension_checks"] = []
        result = _plan(rules=demo_rules(vertical_length=renamed))
        assert CalcBlockCode.RULE_CONTRACT_MISMATCH in _codes(result)

    def test_rule_must_be_applicable_to_system(self) -> None:
        other = vertical_length_rule(
            applicability={**vertical_length_rule()["applicability"], "systems": ["К1"]}
        )
        assert _codes(_plan(rules=demo_rules(vertical_length=other))) == [
            CalcBlockCode.RULE_NOT_APPLICABLE
        ]


# ---------------------------------------------------------------------- единицы (T14, T15)


class TestUnits:
    def test_quantity_arithmetic_checks_dimensions(self) -> None:
        metres = Quantity.of(Decimal("3.3"), "m")
        floors = Quantity.of(Decimal(24), "floor")
        pressure = Quantity.of(Decimal(24), "kPa")
        assert (metres * floors).in_unit("m") == Decimal("79.2")
        with pytest.raises(UnitMismatchError, match="давление"):
            (metres * pressure).in_unit("m")
        with pytest.raises(UnitMismatchError):
            metres + pressure
        with pytest.raises(UnitMismatchError, match="канонических"):
            Quantity.of(Decimal(3300), "mm")

    def test_t14_incompatible_units_block(self) -> None:
        """Вход ждёт давление, а шаг-источник даёт метры; факт в метрах на входе «кПа»."""
        pressure_input = total_length_rule()
        pressure_input["inputs"][0] = {**pressure_input["inputs"][0], "unit": "kPa"}
        pressure_input["dimension_checks"] = []
        result = _plan(rules=demo_rules(total_length=pressure_input))
        assert CalcBlockCode.UNIT_INCOMPATIBLE in _codes(result)
        assert result.steps == ()

        pressure_fact = vertical_length_rule()
        pressure_fact["inputs"][0] = {**pressure_fact["inputs"][0], "unit": "kPa"}
        pressure_fact["dimension_checks"] = []
        result = _plan(rules=demo_rules(vertical_length=pressure_fact))
        unit = next(item for item in result.reasons if item.code is CalcBlockCode.UNIT_INCOMPATIBLE)
        assert unit.fact_key == HEIGHT_KEY

    def test_t15_millimetres_are_converted_and_shown(self) -> None:
        """Вход правила в миллиметрах: 3300 мм → 3,3 м перед обработчиком — видно в шаге."""
        facts = demo_facts()
        facts[HEIGHT_KEY] = snapshot_item(
            "floor.height",
            CalcFactSubject(building="1", floor="2..24"),
            CalcNumberValue(value="3300", unit="mm"),
        )
        rule = vertical_length_rule()
        rule["inputs"][0] = {**rule["inputs"][0], "unit": "mm"}
        execution = _run(facts=facts, rules=demo_rules(vertical_length=rule))
        step = execution.steps[0]
        height = next(item for item in step.inputs if item.name == "floor_height")
        assert height.conversion is not None
        assert (height.conversion.from_value, height.conversion.from_unit) == ("3300", "mm")
        assert (height.conversion.to_value, height.conversion.to_unit) == ("3.3", "m")
        assert _value(execution, "demo.vertical_length") == "79.2"

    def test_parameter_units_are_converted(self) -> None:
        rule = reserve_rule()
        rule["parameters"] = [{**rule["parameters"][0], "value": "1.07"}]
        execution = _run(CalcScenario.TENDER_SAFE, rules=demo_rules(length_reserve=rule))
        step = next(item for item in execution.steps if item.step_key == "total_with_reserve")
        assert step.parameters[0].conversion is None
        assert step.parameters[0].value == "1.07"


# ---------------------------------------------------------------------------- граф (T16–T17)


class TestGraph:
    def test_t16_steps_run_in_dependency_order(self) -> None:
        execution = _run()
        assert [step.step_key for step in execution.steps] == [
            "vertical_length",
            "total_length",
            "total_with_reserve",
        ]
        shuffled = replace(DEMO_CALCULATOR, steps=tuple(reversed(DEMO_CALCULATOR.steps)))
        order, problems = topological_order(shuffled.steps)
        assert problems == []
        assert order == ["vertical_length", "total_length", "total_with_reserve"]

    def test_t17_cycle_blocks_before_any_calculation(self) -> None:
        first, second, third = DEMO_CALCULATOR.steps
        cyclic = replace(
            DEMO_CALCULATOR,
            steps=(
                replace(first, steps={"floors": StepBinding("total_with_reserve", "value")}),
                second,
                third,
            ),
        )
        problems = definition_problems(cyclic)
        assert any("цикл" in item for item in problems)
        with pytest.raises(DefinitionError, match="цикл"):
            build_registry([cyclic])
        result = _plan(definition=cyclic)
        assert _codes(result)[0] is CalcBlockCode.CALCULATOR_INVALID
        assert result.steps == ()

    def test_definition_checks_keys_and_references(self) -> None:
        first, second, third = DEMO_CALCULATOR.steps
        broken = replace(
            DEMO_CALCULATOR,
            steps=(first, replace(second, step_key="vertical_length"), third),
        )
        assert any("повторяются" in item for item in definition_problems(broken))
        dangling = replace(
            DEMO_CALCULATOR,
            steps=(first, replace(second, steps={"length": StepBinding("nowhere", "x")}), third),
        )
        assert any("неизвестного" in item for item in definition_problems(dangling))

    def test_catalog_answers_what_exists(self) -> None:
        assert set(CALCULATORS) == {("test.vertical_length", 1), ("test.riser_demand", 1)}
        demo = CALCULATORS[("test.vertical_length", 1)]
        assert demo.kind is CalcCalculatorKind.DEMO
        assert "не расчёт ВК" in demo.title
        assert demo.rule_keys == (
            "test.geometry.vertical_length",
            "test.geometry.total_length",
            "test.tender.length_reserve",
        )


# ---------------------------------------------------------------- округление и точность (T24)


class TestRounding:
    def test_t24_intermediate_values_are_not_rounded(self) -> None:
        """2,95 × 3 = 8,85 и 8,85 × 3 = 26,55 — промежуточные без округления, итог — явно."""
        execution = _run(
            CalcScenario.TENDER_SAFE,
            facts=demo_facts(height="2.95", floors=3, risers=3),
        )
        values = {step.step_key: step.outputs[0].value for step in execution.steps}
        assert values == {
            "vertical_length": "8.85",
            "total_length": "26.55",
            "total_with_reserve": "28.4085",
        }
        assert all(step.roundings == [] for step in execution.steps)
        total = next(item for item in execution.results if item.result_key == "demo.total_length")
        assert total.value == "28.5"
        assert total.rounding is not None
        assert (total.rounding.before, total.rounding.after) == ("28.4085", "28.5")
        vertical = next(
            item for item in execution.results if item.result_key == "demo.vertical_length"
        )
        assert (vertical.value, vertical.rounding) == ("8.85", None)

    def test_decimal_is_exact(self) -> None:
        execution = _run(facts=demo_facts(height="0.1", floors=3, risers=1))
        assert _value(execution, "demo.vertical_length") == "0.3"

    def test_rounding_policy_is_explicit(self) -> None:
        up = CalcRoundingPolicy(mode=CalcRoundingMode.CEILING, quantum="0.1")
        half = CalcRoundingPolicy(mode=CalcRoundingMode.HALF_UP, quantum="1")
        assert apply_rounding(Decimal("79.2000001"), up) == Decimal("79.3")
        assert apply_rounding(Decimal("2.5"), half) == Decimal("3")

    def test_inexact_arithmetic_fails_instead_of_rounding(self) -> None:
        """Деление с бесконечной дробью без явного округления — FAILED, не «примерно»."""

        def divide(context: HandlerContext) -> HandlerResult:
            length = context.inputs["floor_height"] / context.inputs["floors"]
            return HandlerResult(
                outputs={"length": length * context.inputs["floors"]}, explanation=""
            )

        broken = replace(HANDLERS["test.vertical_length.v1"], compute=divide)
        registry = MappingProxyType({**HANDLERS, "test.vertical_length.v1": broken})
        result = plan(
            DEMO_CALCULATOR,
            CalcScenario.EXPECTED,
            SCOPE,
            demo_facts(height="10", floors=3),
            demo_rules(),
            registry,
        )
        with pytest.raises(StepExecutionError) as caught:
            execute(result, uuid.uuid4(), {})
        assert caught.value.error == "Inexact"
        assert caught.value.step_key == "vertical_length"


# -------------------------------------------------------------- сценарии и допущения (T20–T22)


class TestScenarios:
    @pytest.mark.parametrize("scenario", [CalcScenario.MINIMUM, CalcScenario.EXPECTED])
    def test_t20_t21_tender_assumption_is_not_applied(self, scenario: CalcScenario) -> None:
        execution = _run(scenario)
        step = next(item for item in execution.steps if item.step_key == "total_with_reserve")
        assert step.status is CalcStepStatus.NOT_APPLIED
        assert step.rule is None
        assert f"Сценарий {scenario.value} не допускает" in step.explanation
        assert _value(execution, "demo.total_length") == "158.4"
        [assumption] = execution.assumptions
        assert assumption.applied is False and assumption.delta == "0"

    def test_t22_tender_safe_applies_only_approved_assumption(self) -> None:
        execution = _run(CalcScenario.TENDER_SAFE)
        step = next(item for item in execution.steps if item.step_key == "total_with_reserve")
        assert step.status is CalcStepStatus.EXECUTED
        assert step.rule is not None and step.rule.rule_type is CalcRuleType.TENDER_ASSUMPTION
        [assumption] = execution.assumptions
        assert assumption.applied is True
        assert (assumption.base_value, assumption.value, assumption.delta) == (
            "158.4",
            "169.488",
            "11.088",
        )
        assert assumption.impact == "Длина больше на долю запаса."
        assert assumption.affected_results == ["demo.total_length"]
        assert _value(execution, "demo.total_length") == "169.5"

    def test_t22_without_approved_assumption_tender_safe_equals_expected(self) -> None:
        rules: dict[str, Any] = demo_rules()
        rules["test.tender.length_reserve"] = Absence(CalcBlockCode.RULE_NOT_APPROVED, "черновик")
        result = _plan(CalcScenario.TENDER_SAFE, rules=rules)
        assert result.valid
        assert any("Допущение не применено" in item for item in result.warnings)
        execution = execute(result, uuid.uuid4(), {})
        assert _value(execution, "demo.total_length") == "158.4"

    def test_t22_inapplicable_assumption_is_not_applied(self) -> None:
        other = reserve_rule(applicability={**reserve_rule()["applicability"], "systems": ["К1"]})
        result = _plan(CalcScenario.TENDER_SAFE, rules=demo_rules(length_reserve=other))
        assert result.valid
        assert any("не к В1" in item for item in result.warnings)

    def test_tender_rule_in_ordinary_step_is_forbidden(self) -> None:
        """Версия правила сменила тип на тендерное допущение — обычный шаг его не примет."""
        tender = vertical_length_rule(
            rule_type="TENDER_ASSUMPTION",
            impact="Скрытый резерв.",
            sources=reserve_rule()["sources"],
        )
        for scenario in CalcScenario:
            result = _plan(scenario, rules=demo_rules(vertical_length=tender))
            assert _codes(result) == [CalcBlockCode.RULE_TYPE_NOT_ALLOWED], scenario

    def test_scenario_must_be_supported(self) -> None:
        narrow = replace(DEMO_CALCULATOR, scenarios=frozenset({CalcScenario.EXPECTED}))
        assert _codes(_plan(CalcScenario.MINIMUM, definition=narrow)) == [
            CalcBlockCode.SCENARIO_NOT_SUPPORTED
        ]

    def test_scope_must_fit_calculator(self) -> None:
        missing_floor = SCOPE.model_copy(update={"floor": None})
        assert _codes(_plan(scope=missing_floor)) == [CalcBlockCode.SCOPE_INVALID]
        other_system = SCOPE.model_copy(update={"system_code": "К1"})
        assert CalcBlockCode.SCOPE_INVALID in _codes(_plan(scope=other_system))


# ------------------------------------------------------------ повторное использование шагов


class TestReuse:
    def test_same_fingerprint_is_reused_and_visible(self) -> None:
        first = _run()
        source_run = uuid.uuid4()
        reuse = {
            step.fingerprint: PriorStep(
                run_id=source_run,
                fingerprint=step.fingerprint,
                outputs=tuple(step.outputs),
                explanation=step.explanation,
            )
            for step in first.steps
            if step.status is CalcStepStatus.EXECUTED
        }
        changed = _plan(facts=demo_facts(risers=3))
        second = execute(changed, uuid.uuid4(), reuse)
        statuses = {step.step_key: step.status for step in second.steps}
        # Этажность и высота прежние — первый шаг взят из прежнего запуска; стояков стало 3.
        assert statuses["vertical_length"] is CalcStepStatus.REUSED
        assert second.steps[0].reused_from_run_id == source_run
        assert statuses["total_length"] is CalcStepStatus.EXECUTED
        assert _value(second, "demo.total_length") == "237.6"

    def test_new_rule_version_is_never_reused(self) -> None:
        first = _run()
        reuse = {
            step.fingerprint: PriorStep(uuid.uuid4(), step.fingerprint, tuple(step.outputs), "")
            for step in first.steps
        }
        rules = demo_rules()
        rules["test.geometry.vertical_length"] = resolved(
            "test.geometry.vertical_length", vertical_length_rule(formula="L = h · n"), version=2
        )
        second = execute(_plan(rules=rules), uuid.uuid4(), reuse)
        assert second.steps[0].status is CalcStepStatus.EXECUTED


# -------------------------------------------------------- обработчики и изоляция (T18, T30)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


class TestHandlers:
    def test_golden_cases_hold(self) -> None:
        for spec in HANDLERS.values():
            assert check_golden(spec) == [], spec.implementation_key

    def test_semantics_hash_changes_with_algorithm_contract(self) -> None:
        spec = HANDLERS["test.vertical_length.v1"]
        changed = replace(
            spec,
            golden=(GoldenCase({"floor_height": "3", "floors": "2"}, {}, {"length": "6.5"}),),
        )
        assert changed.semantics_sha256 != spec.semantics_sha256
        assert check_golden(changed) != []

    def test_registry_rejects_bad_declarations(self) -> None:
        spec = HANDLERS["test.vertical_length.v1"]
        with pytest.raises(ValueError, match="дважды"):
            handlers_module.build_registry([spec, spec])
        with pytest.raises(ValueError, match="рабочей единице"):
            handlers_module.build_registry([replace(spec, inputs={"floor_height": "mm"})])
        with pytest.raises(ValueError, match="шаблону"):
            handlers_module.build_registry([replace(spec, implementation_key="os.system")])

    def test_t18_handlers_cannot_reach_registries(self) -> None:
        """Обработчик видит только неизменяемые входы; чистые модули ядра не знают о базе."""
        forbidden = (
            "sqlalchemy",
            "app.models",
            "app.db",
            "app.services.calc.facts",
            "app.services.calc.rules.registry",
            "app.services.calc.rules.legacy",
            "fastapi",
        )
        for name in PURE_MODULES:
            for module in _imports(ENGINE / name):
                assert not module.startswith(forbidden), f"{name}: {module}"
        fields = set(HandlerContext.__dataclass_fields__)
        assert fields == {"inputs", "parameters"}
        execution_inputs = _plan().steps[0]
        assert execution_inputs.handler is not None

    def test_t30_no_legacy_or_executable_path(self) -> None:
        """Сценарий D: коэффициенту старого портала неоткуда попасть в обработчик."""
        for path in ENGINE.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "legacy" not in _imports(path).__repr__(), path.name
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in {"eval", "exec", "compile", "__import__"}
        demo = (ENGINE / "demo.py").read_text(encoding="utf-8")
        assert "0.145" not in demo


# -------------------------------------------------------------------- объяснение и сравнение


class TestTrace:
    def test_t23_trace_reaches_facts_and_rule_versions(self) -> None:
        planned = _plan(CalcScenario.TENDER_SAFE)
        execution = execute(planned, uuid.uuid4(), {})
        run = _run_read(execution, planned)
        trace = explain(run, "demo.total_length")
        kinds: list[str] = []

        def walk(node: Any) -> None:
            kinds.append(node.kind.value)
            for child in node.children:
                walk(child)

        walk(trace.root)
        assert {"RESULT", "ROUNDING", "STEP", "RULE", "ASSUMPTION", "FACT", "PARAMETER"} <= set(
            kinds
        )
        assert trace.text.startswith("Длина по всем стоякам (демо) = 169,5 м.")
        assert "Высота этажа 3,3 м × 24 эт. = 79,2 м" in trace.text
        vertical = explain(run, "demo.vertical_length")
        rule = next(child for child in vertical.root.children[0].children if child.kind == "RULE")
        assert rule.key == "test.geometry.vertical_length@1"
        facts = [child for child in vertical.root.children[0].children if child.kind == "FACT"]
        assert {child.key for child in facts} == {
            HEIGHT_KEY,
            "building.floors_above_ground@building=1",
        }

    def test_compare_names_what_changed(self) -> None:
        base_plan = _plan()
        other_plan = _plan(facts=demo_facts(floors=25))
        base = _run_read(execute(base_plan, uuid.uuid4(), {}), base_plan)
        other = _run_read(execute(other_plan, uuid.uuid4(), {}), other_plan)
        diff = compare(base, other)
        assert [item.fact_key for item in diff.facts] == ["building.floors_above_ground@building=1"]
        assert {item.step_key for item in diff.invalidated_steps} == {
            "vertical_length",
            "total_length",
            "total_with_reserve",
        }
        first = next(item for item in diff.invalidated_steps if item.step_key == "vertical_length")
        assert first.causes == ["другие входы"]
        assert {(item.result_key, item.base_value, item.other_value) for item in diff.results} == {
            ("demo.vertical_length", "79.2", "82.5"),
            ("demo.total_length", "158.4", "165"),
        }


def test_t31_calc_portal_stays_off() -> None:
    flag = FEATURES["calc.portal"]
    assert flag.default is False
    assert flag.admin_editable is False


def test_snapshot_item_contract_forbids_extra_fields() -> None:
    item = next(iter(demo_facts().values()))
    with pytest.raises(ValueError):
        CalcSnapshotItem.model_validate({**item.model_dump(), "note": "лишнее"})
    assert isinstance(item.value, CalcNumberValue | CalcCountValue)
