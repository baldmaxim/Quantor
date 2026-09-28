"""Рабочий калькулятор ВК стадии П без базы (ADR-0030, PROMPT 06).

Примитивы и расширение ядра, определения калькуляторов и синтезаторов, вертикальная структура
(T07–T11), ожидаемые количества и сценарии (T12–T20). Числа — синтетические: G01 — 24 этажа,
первый без квартир, 6 квартир на этажах 2–24, высоты 4,2 и 3,0 м.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcCalculatorKind,
    CalcCompleteness,
    CalcQuantityDerivation,
    CalcRuleSourceKind,
    CalcRunStatus,
    CalcScenario,
    CalcStepStatus,
)
from app.contracts.calc.passport import MINIMUM_NOTICE
from app.contracts.calc.rules import CalcRuleContent
from app.services.calc.engine.calculators import definition_problems
from app.services.calc.engine.catalog import CALCULATORS, HANDLERS
from app.services.calc.engine.handlers import check_golden
from app.services.calc.engine.plan_types import Absence
from app.services.calc.engine.primitives import PRIMITIVE_PREFIX, PRIMITIVES
from app.services.calc.engine.reads import list_calculators
from app.services.calc.rules.legacy import load_catalog
from app.services.calc.rules.validation import content_problems
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.synthesis.definitions import check_golden as check_synthesis
from app.services.calc.synthesis.reads import list_synthesizers
from app.services.calc.systems.vk.rule_needs import NEEDS_BY_KEY, VK_RULE_NEEDS
from app.services.calc.systems.vk.spec import VK_SPECS
from tests.calc_vk_fixtures import TEST_PARAMETERS, Building, content_for, rule_keys
from tests.calc_vk_pure import count, facts_for, number, rules_for, run, system

E, M, T = CalcScenario.EXPECTED, CalcScenario.MINIMUM, CalcScenario.TENDER_SAFE
ALL_B1 = tuple(rule_keys("В1", tender=True))


def _amount(row_amount: object) -> tuple[str | None, str | None, str | None]:
    return (
        getattr(row_amount, "value", None),
        getattr(row_amount, "low", None),
        getattr(row_amount, "high", None),
    )


class TestPrimitives:
    def test_golden_cases_hold(self) -> None:
        assert all(not check_golden(spec) for spec in PRIMITIVES.values())

    def test_primitive_is_not_a_rule(self) -> None:
        """Примитив без параметров и вне реестра реализаций правил; правило на него не ссылается."""
        assert all(not spec.parameters for spec in PRIMITIVES.values())
        assert all(key.startswith(PRIMITIVE_PREFIX) for key in PRIMITIVES)
        assert not set(PRIMITIVES) & set(HANDLERS)
        content = CalcRuleContent.model_validate(
            content_for("vk.b1.risers.count_range")
            | {"implementation_key": "primitive.floor_structure.v1"}
        )
        assert any("примитив" in item for item in content_problems(content, load_catalog()))

    def test_primitive_step_is_marked_in_the_run(self) -> None:
        result = run("В1", E, facts_for(Building()), {})
        assert result.execution is not None
        steps = {step.step_key: step for step in result.execution.steps}
        floors = steps["structure_floors"]
        assert floors.rule is None
        assert floors.primitive is not None
        assert floors.primitive.implementation_key == "primitive.floor_structure.v1"
        members = [item for item in floors.inputs if item.series == "apartments"]
        assert {item.member for item in members} == {"1", "2..24"}


class TestDefinitions:
    def test_four_production_calculators_demo_hidden(self) -> None:
        production = [item for item in list_calculators() if item.kind.value == "PRODUCTION"]
        assert {item.calculator_id for item in production} == {
            spec.calculator_id for spec in VK_SPECS
        }
        assert all(item.partial for item in production)
        assert all(item.kind is not CalcCalculatorKind.DEMO for item in list_calculators())
        assert {item.synthesizer_id for item in list_synthesizers()} == {
            spec.synthesizer_id for spec in VK_SPECS
        }
        for definition in CALCULATORS.values():
            assert definition_problems(definition) == []
        for synthesizer in SYNTHESIZERS.values():
            assert check_synthesis(synthesizer) == []

    def test_every_engineering_decision_is_a_declared_need(self) -> None:
        """Инженерное решение — только версия правила из заявки; своего числа у калькулятора нет."""
        for spec in VK_SPECS:
            calculator = CALCULATORS[(spec.calculator_id, spec.version)]
            for step in calculator.steps:
                if step.rule_key is None:
                    assert step.primitive is not None
                    continue
                need = NEEDS_BY_KEY[step.rule_key]
                assert spec.code in need.systems
                assert set(step.allowed_rule_types) >= {need.rule_types[0]}
            for rule in SYNTHESIZERS[(spec.synthesizer_id, spec.version)].rules.values():
                assert spec.code in NEEDS_BY_KEY[rule.rule_key].systems

    def test_layers_are_separate_steps(self) -> None:
        """Слои A–D не смешаны: у шага один слой, количества собирает слой паспорта."""
        prefixes = ("demand_", "structure_", "quantity_", "tender_")
        for definition in CALCULATORS.values():
            if definition.kind is CalcCalculatorKind.PRODUCTION:
                assert all(step.step_key.startswith(prefixes) for step in definition.steps)

    def test_t21_no_legacy_rule_is_used(self) -> None:
        legacy = set(load_catalog().by_id)
        assert not legacy & set(NEEDS_BY_KEY)
        for need in VK_RULE_NEEDS:
            if need.rule_key in TEST_PARAMETERS:
                sources = CalcRuleContent.model_validate(content_for(need.rule_key)).sources
                assert all(item.kind != CalcRuleSourceKind.LEGACY_CODE.value for item in sources)


class TestInputs:
    def test_t03_t04_conflict_blocks_only_dependent_part(self) -> None:
        facts = facts_for(Building())
        key = next(key for key in facts if key.startswith("floor.height@") and "2..24" in key)
        facts[key] = Absence(CalcBlockCode.FACT_CONFLICT, "источники расходятся")
        result = run("В1", E, facts, rules_for(*ALL_B1))
        assert result.execution is not None
        blocked = {item.step_key for item in result.plan.reasons}
        assert "structure_vertical" in blocked
        assert "structure.interfloor_length" not in result.results
        assert result.results["structure.top_floor"].value == "24"
        assert result.results["structure.risers_min"].value == "2"
        assert result.rows["vk.b1.pipe.riser"].completeness is CalcCompleteness.BLOCKED
        assert result.rows["vk.b1.connection.floor"].completeness is CalcCompleteness.RANGE

    def test_t05_unknown_is_never_zero(self) -> None:
        building = Building(apartments={"2..24": 6})
        result = run("В1", E, facts_for(building), rules_for(*ALL_B1))
        assert result.execution is not None
        gaps = {item.step_key: item for item in result.execution.gaps}
        assert gaps["structure_floors"].code is CalcBlockCode.INPUT_INCOMPLETE
        assert "structure.top_floor" not in result.results
        riser = result.rows["vk.b1.pipe.riser"]
        assert riser.completeness is CalcCompleteness.BLOCKED
        assert _amount(riser.amount) == (None, None, None)


class TestVertical:
    def test_g01_simple_building(self) -> None:
        result = run("В1", E, facts_for(Building()), rules_for(*ALL_B1))
        values = {key: row.value for key, row in result.results.items()}
        assert values["structure.served_floors"] == "23"
        assert values["structure.apartments_total"] == "138"
        assert values["structure.interfloor_length"] == "70.2"
        assert values["structure.slab_crossings"] == "23"
        assert values["check.apartments_discrepancy"] == "0"
        assert values["structure.zones"] == "2"

    def test_t07_g02_different_heights_are_summed(self) -> None:
        heights = {"1": "4.5", "2..10": "3", "11": "3.6", "12..24": "3"}
        result = run("В1", E, facts_for(Building(heights=heights)), {})
        assert result.results["structure.interfloor_length"].value == "71.1"

    def test_g02_elevations_win_over_nominal_heights(self) -> None:
        building = Building(elevations={"1": "0", "24": "70.35"})
        result = run("В1", E, facts_for(building), {})
        assert result.results["structure.interfloor_length"].value == "70.35"

    def test_t23_no_default_height(self) -> None:
        """Нет высоты этажа — пролёт не определён: 3,3 м не подставляется."""
        result = run("В1", E, facts_for(Building(heights={"1": "4.2"})), {})
        assert "structure.interfloor_length" not in result.results
        assert result.execution is not None
        assert any("высоты этажей" in item.message for item in result.execution.gaps)

    def test_t09_technical_floor_counted_once(self) -> None:
        building = Building(
            floors=25,
            apartments={"1": 0, "2..24": 6, "25": 0},
            heights={"1": "4.2", "2..24": "3", "25": "2.5"},
        )
        result = run("В1", E, facts_for(building), {})
        assert result.results["structure.top_floor"].value == "24"
        assert result.results["structure.served_floors"].value == "23"
        assert result.results["structure.interfloor_length"].value == "70.2"
        assert result.results["structure.slab_crossings"].value == "23"

    def test_t08_typical_floor_multiplied_once(self) -> None:
        result = run("В1", E, facts_for(Building()), rules_for(*ALL_B1))
        assert result.graph is not None
        floors = next(node for node in result.graph.nodes if node.id == "served_floors")
        connections = next(node for node in result.graph.nodes if node.id == "floor_connections")
        assert floors.multiplicity == 23
        assert connections.multipliers == ["risers", "served_floors"]
        row = result.rows["vk.b1.connection.floor"]
        assert (row.amount.low, row.amount.high) == ("46", "69")

    def test_t10_t11_range_stays_range_without_selection(self) -> None:
        result = run("В1", E, facts_for(Building()), rules_for(*ALL_B1))
        assert result.graph is not None and result.synthesis is not None
        risers = next(node for node in result.graph.nodes if node.id == "risers")
        assert (risers.cardinality.min, risers.cardinality.max) == (2, 3)
        assert risers.cardinality.selected is None
        assert [item.key for item in result.synthesis.variants] == ["risers_2", "risers_3"]
        riser = result.rows["vk.b1.pipe.riser"]
        assert _amount(riser.amount) == (None, "144.4", "216.6")

    def test_observed_risers_win_and_discrepancy_is_visible(self) -> None:
        observed = count("system.risers_count", 4, **system("В1"))
        result = run("В1", E, facts_for(Building(), [observed]), rules_for(*ALL_B1))
        assert result.graph is not None
        risers = next(node for node in result.graph.nodes if node.id == "risers")
        assert risers.provenance.value == "OBSERVED"
        assert risers.cardinality.min == risers.cardinality.max == 4
        assert any("принят документ" in item for item in result.graph.warnings)


class TestQuantities:
    def test_t12_pipes_are_aggregated_per_system(self) -> None:
        b1 = run("В1", E, facts_for(Building()), rules_for(*ALL_B1)).rows
        k1 = run("К1", E, facts_for(Building()), rules_for(*rule_keys("К1"))).rows
        assert all(row.system_code == "В1" for row in b1.values())
        assert all(key.startswith("vk.k1.") for key in k1)
        assert _amount(k1["vk.k1.pipe.riser"].amount) == (None, "149.4", "224.1")

    def test_t13_t24_unknown_diameter_is_not_guessed(self) -> None:
        rows = run("В1", E, facts_for(Building()), rules_for(*ALL_B1)).rows
        assert rows["vk.b1.pipe.riser"].size is None
        assert rows["vk.b1.pipe.riser"].attributes["диаметр"] == "не определён"
        assert rows["vk.b1.pipe.total"].completeness is CalcCompleteness.PARTIAL
        documented = number("system.riser_diameter", "32", "mm", **system("В1"))
        sized = run("В1", E, facts_for(Building(), [documented]), rules_for(*ALL_B1)).rows
        assert sized["vk.b1.pipe.riser"].size == "32 мм"

    def test_t14_range_is_not_a_midpoint(self) -> None:
        rows = run("В1", E, facts_for(Building()), rules_for(*ALL_B1)).rows
        for row in rows.values():
            if row.amount.low is not None:
                assert row.amount.value is None
                assert row.amount.low != row.amount.high

    def test_t15_topology_fitting_differs_from_fallback(self) -> None:
        rows = run("В1", E, facts_for(Building()), rules_for(*ALL_B1)).rows
        branch = rows["vk.b1.fitting.branch"]
        fallback = rows["vk.b1.fitting.route_fallback"]
        assert branch.derivation is CalcQuantityDerivation.TOPOLOGY
        assert fallback.derivation is CalcQuantityDerivation.FALLBACK
        assert fallback.notice is not None and "Резервный метод" in fallback.notice
        assert fallback.rule_refs == ["vk.fittings.per_meter@1"]
        without = run(
            "В1", E, facts_for(Building()), rules_for(*(k for k in ALL_B1 if "fittings" not in k))
        ).rows
        assert without["vk.b1.fitting.route_fallback"].completeness is CalcCompleteness.BLOCKED

    def test_t16_t17_t18_reserve_only_in_tender_safe_and_separate(self) -> None:
        facts = facts_for(Building())
        rules = rules_for(*ALL_B1)
        minimum = run("В1", M, facts, rules).rows["vk.b1.pipe.riser"]
        expected = run("В1", E, facts, rules).rows["vk.b1.pipe.riser"]
        tender = run("В1", T, facts, rules).rows["vk.b1.pipe.riser"]
        assert minimum.reserve is None and expected.reserve is None
        assert _amount(minimum.amount) == ("144.4", None, None)
        assert minimum.notice == MINIMUM_NOTICE
        assert tender.base is not None and tender.reserve is not None
        assert _amount(tender.base) == (None, "144.4", "216.6")
        assert _amount(tender.reserve.amount) == (None, "2", "3")
        assert _amount(tender.amount) == (None, "146.4", "219.6")
        assert tender.reserve.rule_key == "vk.tender.riser_length_reserve"

    def test_no_global_percentage(self) -> None:
        """Тендерное допущение меняет только свой класс позиций, остальные совпадают."""
        facts = facts_for(Building())
        rules = rules_for(*ALL_B1)
        expected = run("В1", E, facts, rules).rows
        tender = run("В1", T, facts, rules).rows
        changed = {key for key in expected if expected[key].amount != tender[key].amount}
        assert changed == {"vk.b1.pipe.riser", "vk.b1.pipe.total"}

    def test_t19_insulation_is_not_whole_pipe_without_rule(self) -> None:
        without = run("В1", E, facts_for(Building()), {}).rows
        assert without["vk.b1.insulation.pipes"].completeness is CalcCompleteness.BLOCKED
        rows = run("В1", E, facts_for(Building()), rules_for(*ALL_B1)).rows
        assert _amount(rows["vk.b1.insulation.riser"].amount) == (None, "144.4", "216.6")
        assert "vk.b1.insulation.connection" not in rows

    def test_t20_supports_not_generated_without_rule(self) -> None:
        rows = run("В1", E, facts_for(Building()), {}).rows
        for key in ("vk.b1.support.riser", "vk.b1.support.horizontal"):
            assert rows[key].completeness is CalcCompleteness.BLOCKED
            assert rows[key].amount.value is None and rows[key].amount.low is None
        ruled = run("В1", E, facts_for(Building()), rules_for(*ALL_B1)).rows
        assert _amount(ruled["vk.b1.support.riser"].amount) == (None, "50", "75")

    def test_sleeves_penetrations_firestop_are_distinct(self) -> None:
        bare = run("В1", E, facts_for(Building()), rules_for("vk.b1.risers.count_range")).rows
        assert _amount(bare["vk.b1.penetration.slab"].amount) == (None, "46", "69")
        assert bare["vk.b1.sleeve.slab"].completeness is CalcCompleteness.BLOCKED
        assert bare["vk.b1.firestop.slab"].completeness is CalcCompleteness.BLOCKED

    def test_g07_known_and_unknown_routes(self) -> None:
        main = number("system.main_length", "45", "m", **system("В1"))
        rules = rules_for(*(key for key in ALL_B1 if "connection.length" not in key))
        rows = run("В1", E, facts_for(Building(), [main]), rules).rows
        assert _amount(rows["vk.b1.pipe.main"].amount) == ("45", None, None)
        assert rows["vk.b1.pipe.connection"].completeness is CalcCompleteness.BLOCKED
        total = rows["vk.b1.pipe.total"]
        assert total.completeness is CalcCompleteness.PARTIAL
        assert _amount(total.amount) == (None, "189.4", "261.6")
        assert "Полная длина пока не определена" in total.explanation
        known = {item.key: item.known for item in total.components}
        assert known == {"riser": True, "connection": False, "main": True}

    def test_t22_total_attribute_is_never_multiplied(self) -> None:
        main = number("system.main_length", "45", "m", **system("В1"))
        observed = count("system.risers_count", 5, **system("В1"))
        rows = run("В1", E, facts_for(Building(), [main, observed]), rules_for(*ALL_B1)).rows
        assert _amount(rows["vk.b1.pipe.main"].amount) == ("45", None, None)

    @pytest.mark.parametrize("code", ["В1", "Т3", "Т4", "К1"])
    def test_partial_without_any_rule(self, code: str) -> None:
        """Правил нет: расчёт частичный, найденное посчитано, остальное — «не определено»."""
        result = run(code, E, facts_for(Building()), {})
        assert result.execution is not None
        assert result.results["structure.interfloor_length"].value == "70.2"
        assert result.synthesis is not None
        assert result.synthesis.status.value == "PARTIAL"
        slug = next(spec.slug for spec in VK_SPECS if spec.code == code)
        riser = result.rows[f"vk.{slug}.pipe.riser"]
        assert riser.completeness is CalcCompleteness.BLOCKED
        assert "risers.count" in riser.blocked_by


def test_status_of_run_is_partial_when_steps_blocked() -> None:
    result = run("В1", E, facts_for(Building()), {})
    assert result.plan.reasons
    assert result.execution is not None
    assert all(step.status is not CalcStepStatus.REUSED for step in result.execution.steps)
    assert CalcRunStatus.PARTIAL.value == "PARTIAL"
    assert Decimal(result.results["structure.interfloor_length"].value) == Decimal("70.2")
