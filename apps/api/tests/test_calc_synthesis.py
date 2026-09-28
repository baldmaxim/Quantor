"""Синтез структуры без базы (ADR-0030, PROMPT 05).

Демо-синтезатор на детерминированных входах: происхождение элементов, диапазоны и варианты,
сценарии, кратность и повторяемость без двойного умножения, честная геометрия, правила и
допущения, отпечатки реализации, объяснение. Запуски через базу и API — в
`test_calc_synthesis_api.py`.
"""

from __future__ import annotations

import ast
import uuid
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts.calc.engine import CalcBlockingReason
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcElementProvenance,
    CalcGeometryState,
    CalcQuantityBasis,
    CalcRuleType,
    CalcScenario,
    CalcSelectionSource,
    CalcSynthesisRuleRole,
    CalcSynthesisStatus,
    CalcUnresolvedKind,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import (
    CalcCardinality,
    CalcGeometry,
    CalcQuantityAttr,
    CalcSystemGraph,
    CalcSystemNode,
)
from app.core.features import REGISTRY as FEATURES
from app.services.calc.engine.catalog import HANDLERS
from app.services.calc.engine.plan_types import Absence
from app.services.calc.synthesis import demo_rules
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.synthesis.definitions import (
    DecisionInput,
    SynthesisOutcome,
    check_golden,
    synthesize,
)
from app.services.calc.synthesis.demo import RISER_STRUCTURE
from app.services.calc.synthesis.golden import GOLDEN_RUN, SCOPE, fact, resolved, result
from app.services.calc.synthesis.graph import attribute_total, graph_problems, instances
from app.services.calc.synthesis.reads import list_synthesizers

SYNTHESIS = Path(__file__).resolve().parents[1] / "app" / "services" / "calc" / "synthesis"
INLETS = fact(
    "system.inlets_count", CalcFactSubject(building="1", discipline="VK", system_code="В1"), 1
)
FLOORS = fact("building.floors_above_ground", CalcFactSubject(building="1"), 24)
SHAFTS = fact("floor.shafts_count", CalcFactSubject(building="1", floor="1..24"), 2)
RULES = {
    demo_rules.RULE_KEYS["topology"]: demo_rules.riser_topology,
    demo_rules.RULE_KEYS["selection"]: demo_rules.riser_choice,
    demo_rules.RULE_KEYS["reserve"]: demo_rules.riser_reserve,
}


def _facts(*items: Any) -> dict[str, Any]:
    return {item.fact_key: item for item in items}


def _rules(*names: str, **overrides: Any) -> dict[str, Any]:
    keys = [demo_rules.RULE_KEYS[name] for name in names]
    found: dict[str, Any] = {key: resolved(key, RULES[key]()) for key in keys}
    found.update(overrides)
    return found


def _run(
    scenario: CalcScenario = CalcScenario.EXPECTED,
    *,
    low: str = "4",
    high: str = "5",
    facts: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    decisions: tuple[DecisionInput, ...] = (),
) -> SynthesisOutcome:
    return synthesize(
        RISER_STRUCTURE,
        scenario=scenario,
        scope=SCOPE,
        calculation_run_id=GOLDEN_RUN,
        results={
            "demo.risers_min": result("demo.risers_min", low),
            "demo.risers_max": result("demo.risers_max", high),
        },
        facts=_facts(INLETS, FLOORS, SHAFTS) if facts is None else facts,
        rules=_rules("topology") if rules is None else rules,
        handlers=HANDLERS,
        decisions=decisions,
    )


def _node(outcome: SynthesisOutcome, node_id: str) -> CalcSystemNode:
    assert outcome.graph is not None
    return next(node for node in outcome.graph.nodes if node.id == node_id)


def _graph(outcome: SynthesisOutcome) -> CalcSystemGraph:
    assert outcome.graph is not None, [reason.message for reason in outcome.reasons]
    return outcome.graph


# ------------------------------------------------------------- детерминизм (T01, T02, T26)


class TestDeterminism:
    def test_t01_t02_same_inputs_same_graph_hash(self) -> None:
        first, second = _run(), _run()
        assert first.graph_sha256 == second.graph_sha256
        assert first.graph == second.graph

    def test_golden_cases_hold(self) -> None:
        for definition in SYNTHESIZERS.values():
            assert check_golden(definition) == []

    def test_t27_changed_implementation_changes_fingerprint(self) -> None:
        changed = replace(RISER_STRUCTURE, golden=(("range_expected", "1" * 64),))
        assert changed.implementation_sha256 != RISER_STRUCTURE.implementation_sha256
        assert check_golden(changed) != []


# ---------------------------------------------------- диапазоны и варианты (A, T16–T18)


class TestRanges:
    def test_a_t16_t17_t18_range_stays_range_with_variants(self) -> None:
        """Сценарий A: 4–5 стояков без правила выбора — не 4, не 5 и не 4,5."""
        outcome = _run()
        risers = _node(outcome, "risers")
        assert (risers.cardinality.min, risers.cardinality.max) == (4, 5)
        assert risers.cardinality.selected is None and risers.cardinality.selection is None
        assert outcome.status is CalcSynthesisStatus.PARTIAL
        unresolved = {item.key: item for item in _graph(outcome).unresolved}
        assert unresolved["risers.count"].kind is CalcUnresolvedKind.COUNT_RANGE
        assert unresolved["risers.count"].known == "4–5 по расчёту"
        assert [variant.key for variant in outcome.variants] == ["risers_4", "risers_5"]
        for variant in outcome.variants:
            assert "не выбран и не взвешен" in " ".join(variant.reasons)
            text = variant.model_dump_json()
            assert "%" not in text and "probability" not in text.lower()
        # Кратность ветвей — тоже диапазон: 4–5 стояков × 24 этажа.
        assert instances(_graph(outcome), "floor_branch") == (Decimal(96), Decimal(120))

    def test_exact_calculation_needs_no_choice(self) -> None:
        outcome = _run(low="4", high="4", facts=_facts(INLETS, FLOORS))
        risers = _node(outcome, "risers")
        assert risers.cardinality.exact and risers.cardinality.selection is None
        assert outcome.variants == ()
        # Нерешённой структуры нет, трасса неизвестна — это не делает запуск неполным.
        assert outcome.status is CalcSynthesisStatus.SUCCEEDED
        assert [item.key for item in _graph(outcome).unresolved] == ["supply_main.route"]

    def test_too_many_values_keep_only_range(self) -> None:
        outcome = _run(low="2", high="9")
        assert outcome.variants == ()
        assert any("больше 5" in item for item in outcome.warnings)

    def test_d_approved_selection_rule_chooses(self) -> None:
        """Сценарий D: утверждённое правило выбора — EXPECTED получает 5 со ссылкой на версию."""
        outcome = _run(rules=_rules("topology", "selection"))
        risers = _node(outcome, "risers")
        assert risers.cardinality.selected == 5
        selection = risers.cardinality.selection
        assert selection is not None and selection.source is CalcSelectionSource.RULE
        assert selection.rule is not None
        assert selection.rule.rule_key == demo_rules.RULE_KEYS["selection"]
        assert selection.rule.version == 1
        assert outcome.variants == ()
        assert "risers.count" not in {item.key for item in _graph(outcome).unresolved}

    def test_t08_selection_rule_absent_keeps_range(self) -> None:
        rules = _rules("topology")
        rules[demo_rules.RULE_KEYS["selection"]] = Absence(
            CalcBlockCode.RULE_NOT_APPROVED, "v1 DRAFT"
        )
        risers = _node(_run(rules=rules), "risers")
        assert risers.cardinality.selected is None

    def test_t19_minimum_is_lower_estimate_not_decision(self) -> None:
        outcome = _run(CalcScenario.MINIMUM, rules=_rules("topology", "selection"))
        risers = _node(outcome, "risers")
        assert risers.cardinality.selected is None
        assert risers.estimate is not None
        assert (risers.estimate.value, risers.estimate.meaning) == (4, "LOWER_BOUND")
        assert "не проектное решение" in risers.estimate.note
        assert outcome.variants == ()
        # Правило выбора в MINIMUM не применяется — в привязках его нет.
        assert [item.step_key for item in outcome.bindings] == ["topology"]

    def test_human_decision_selects_without_becoming_a_fact(self) -> None:
        decision = DecisionInput(uuid.uuid4(), "risers", 5, "Выбрано по опыту похожего дома.")
        outcome = _run(decisions=(decision,))
        risers = _node(outcome, "risers")
        assert risers.cardinality.selected == 5
        selection = risers.cardinality.selection
        assert selection is not None and selection.source is CalcSelectionSource.HUMAN_DECISION
        assert selection.decision_id == decision.id
        assert risers.provenance is CalcElementProvenance.CALCULATED
        assert outcome.applied_decisions == (decision.id,)
        assert "HUMAN_DECISION" in {source.kind for source in risers.sources}

    def test_out_of_range_decision_is_not_applied(self) -> None:
        decision = DecisionInput(uuid.uuid4(), "risers", 7, "Семь стояков без расчёта.")
        outcome = _run(decisions=(decision,))
        assert _node(outcome, "risers").cardinality.selected is None
        assert any("вне диапазона" in item for item in outcome.warnings)
        assert outcome.applied_decisions == ()


# ----------------------------------------------------------- сценарии и допущения (E, T20)


class TestScenarios:
    def test_t20_tender_safe_without_assumption_equals_expected(self) -> None:
        expected = _graph(_run(CalcScenario.EXPECTED))
        tender = _run(CalcScenario.TENDER_SAFE)
        graph = _graph(tender)
        assert [node.id for node in graph.nodes] == [node.id for node in expected.nodes]
        assert graph.assumptions == []
        assert any("TENDER_SAFE = EXPECTED" in item for item in tender.warnings)

    def test_e_t13_t21_assumed_elements_only_in_tender_safe(self) -> None:
        rules = _rules("topology", "reserve")
        tender = _graph(_run(CalcScenario.TENDER_SAFE, rules=rules))
        assumed = [
            item for item in (*tender.nodes, *tender.edges) if item.provenance.value == "ASSUMED"
        ]
        assert {item.id for item in assumed} == {"reserve_risers", "reserve_supply"}
        for item in assumed:
            [rule] = item.rules
            assert rule.rule_type is CalcRuleType.TENDER_ASSUMPTION
            assert rule.role is CalcSynthesisRuleRole.ASSUMPTION
        [assumption] = tender.assumptions
        assert assumption.notice.startswith("Это не норматив")
        for scenario in (CalcScenario.MINIMUM, CalcScenario.EXPECTED):
            graph = _graph(_run(scenario, rules=rules))
            assert all(item.provenance.value != "ASSUMED" for item in (*graph.nodes, *graph.edges))

    def test_tender_rule_cannot_act_as_selection(self) -> None:
        rules = _rules("topology")
        rules[demo_rules.RULE_KEYS["selection"]] = resolved(
            demo_rules.RULE_KEYS["selection"],
            {
                **demo_rules.riser_choice(),
                **{
                    k: v
                    for k, v in demo_rules.riser_reserve().items()
                    if k in ("rule_type", "impact", "sources")
                },
            },
        )
        outcome = _run(rules=rules)
        assert outcome.status is CalcSynthesisStatus.BLOCKED
        assert [reason.code for reason in outcome.reasons] == [CalcBlockCode.RULE_TYPE_NOT_ALLOWED]


# ---------------------------------------------------- происхождение и геометрия (T11–T15)


class TestProvenance:
    def test_t11_t12_every_element_has_its_basis(self) -> None:
        graph = _graph(_run(CalcScenario.TENDER_SAFE, rules=_rules("topology", "reserve")))
        assert graph_problems(graph) == []
        by_id = {item.id: item for item in (*graph.nodes, *graph.edges)}
        assert by_id["inlet"].provenance is CalcElementProvenance.OBSERVED
        assert {source.kind for source in by_id["inlet"].sources} == {"FACT"}
        assert by_id["risers"].provenance is CalcElementProvenance.CALCULATED
        assert {source.key for source in by_id["risers"].sources} == {
            "demo.risers_min",
            "demo.risers_max",
        }
        assert by_id["floor_branch"].provenance is CalcElementProvenance.SYNTHESIZED
        assert by_id["floor_branch"].rules[0].rule_key == demo_rules.RULE_KEYS["topology"]

    def test_validator_rejects_basis_less_elements(self) -> None:
        graph = _graph(_run())
        observed = graph.nodes[0].model_copy(update={"sources": []})
        synthesized = next(n for n in graph.nodes if n.id == "floor_branch").model_copy(
            update={"rules": []}
        )
        broken = graph.model_copy(update={"nodes": [observed, *graph.nodes[1:4], synthesized]})
        problems = graph_problems(broken)
        assert any("наблюдённое без факта" in item for item in problems)
        assert any("синтезированное без утверждённого правила" in item for item in problems)

    def test_c_t14_shafts_do_not_place_risers(self) -> None:
        """Сценарий C: две шахты есть, правила размещения нет — стояки не размещаются."""
        graph = _graph(_run())
        risers = next(node for node in graph.nodes if node.id == "risers")
        assert risers.geometry.state is CalcGeometryState.NONE
        assert risers.geometry.bbox is None and risers.geometry.anchor is None
        assert not [
            edge for edge in graph.edges if "shafts" in (edge.source_node, edge.target_node)
        ]
        placement = next(item for item in graph.unresolved if item.key == "risers.placement")
        assert placement.kind is CalcUnresolvedKind.PLACEMENT and placement.structural

    def test_t14_coordinates_only_from_source(self) -> None:
        with pytest.raises(ValidationError, match="наблюдённые"):
            CalcGeometry(state=CalcGeometryState.ESTIMATED, rule_key="x", bbox=[0.1, 0.1, 0.2, 0.2])
        with pytest.raises(ValidationError, match="факт-источник"):
            CalcGeometry(state=CalcGeometryState.OBSERVED)
        with pytest.raises(ValidationError, match="утверждённому правилу"):
            CalcGeometry(state=CalcGeometryState.ESTIMATED)
        observed = CalcGeometry(
            state=CalcGeometryState.OBSERVED,
            source_fact_key="floor.shafts_count@building=1|floor=1..24",
            bbox=[0.1, 0.2, 0.3, 0.4],
        )
        assert observed.bbox == [0.1, 0.2, 0.3, 0.4]

    def test_t15_logical_topology_without_geometry(self) -> None:
        graph = _graph(_run())
        assert {edge.id for edge in graph.edges} == {
            "supply_main",
            "riser_branches",
            "floor_membership",
        }
        assert all(item.geometry.state is CalcGeometryState.NONE for item in graph.edges)
        route = next(item for item in graph.unresolved if item.key == "supply_main.route")
        assert route.kind is CalcUnresolvedKind.ROUTE and not route.structural

    def test_missing_topology_rule_leaves_partial_structure(self) -> None:
        outcome = _run(rules={})
        graph = _graph(outcome)
        assert outcome.status is CalcSynthesisStatus.PARTIAL
        assert graph.edges == [] and "floor_branch" not in {node.id for node in graph.nodes}
        assert any(item.kind is CalcUnresolvedKind.MISSING_RULE for item in graph.unresolved)


# ----------------------------------------------------- кратность (F, T22, T23)


class TestMultiplicity:
    def _floor(self, basis: CalcQuantityBasis) -> CalcSystemGraph:
        graph = _graph(_run(low="4", high="4"))
        attribute = CalcQuantityAttr(name="length", value="3.3", unit="m", basis=basis)
        floors = next(node for node in graph.nodes if node.id == "typical_floors")
        return graph.model_copy(
            update={
                "nodes": [
                    node
                    if node.id != "typical_floors"
                    else floors.model_copy(update={"attributes": [attribute]})
                    for node in graph.nodes
                ]
            }
        )

    def test_f_t22_total_is_never_multiplied_again(self) -> None:
        """Сценарий F: итог по 24 этажам не умножается на кратность группы второй раз."""
        graph = self._floor(CalcQuantityBasis.TOTAL)
        assert attribute_total(graph, "typical_floors", "length") == (
            Decimal("3.3"),
            Decimal("3.3"),
        )

    def test_t22_per_instance_is_multiplied_once(self) -> None:
        graph = _graph(_run(low="4", high="4"))
        branch = next(node for node in graph.nodes if node.id == "floor_branch")
        attribute = CalcQuantityAttr(
            name="length", value="2", unit="m", basis=CalcQuantityBasis.PER_INSTANCE
        )
        changed = graph.model_copy(
            update={
                "nodes": [
                    node
                    if node.id != "floor_branch"
                    else branch.model_copy(update={"attributes": [attribute]})
                    for node in graph.nodes
                ]
            }
        )
        # 4 стояка × 24 этажа × 1 ветвь × 2 м = 192 м — ровно один раз.
        assert attribute_total(changed, "floor_branch", "length") == (Decimal(192), Decimal(192))

    def test_t23_typical_floor_is_one_group_node(self) -> None:
        graph = _graph(_run())
        floors = [node for node in graph.nodes if node.semantic_type == "TYPICAL_FLOOR_GROUP"]
        assert len(floors) == 1 and floors[0].multiplicity == 24
        assert len(graph.nodes) < 10
        assert instances(graph, "typical_floors") == (Decimal(1), Decimal(1))

    def test_multiplier_cycles_are_rejected(self) -> None:
        graph = _graph(_run())
        risers = next(node for node in graph.nodes if node.id == "risers")
        looped = graph.model_copy(
            update={
                "nodes": [
                    node
                    if node.id != "risers"
                    else risers.model_copy(update={"multipliers": ["floor_branch"]})
                    for node in graph.nodes
                ]
            }
        )
        assert "множители узлов образуют цикл" in graph_problems(looped)

    def test_cardinality_contract(self) -> None:
        with pytest.raises(ValidationError):
            CalcCardinality(min=5, max=4)
        with pytest.raises(ValidationError, match="основанием"):
            CalcCardinality(min=4, max=5, selected=5)


# ------------------------------------------------------ блокировки и изоляция (T06–T10)


class TestBlocked:
    @pytest.mark.parametrize(
        "absence",
        [
            Absence(CalcBlockCode.FACT_MISSING, "значения нет"),
            Absence(CalcBlockCode.FACT_CONFLICT, "источники расходятся"),
            Absence(CalcBlockCode.FACT_EXCLUDED, "только ВОР"),
        ],
    )
    def test_t09_t10_missing_or_conflicting_input_blocks(self, absence: Absence) -> None:
        facts: dict[str, Any] = _facts(INLETS, FLOORS)
        facts[FLOORS.fact_key] = absence
        outcome = _run(facts=facts)
        assert outcome.status is CalcSynthesisStatus.BLOCKED
        assert outcome.graph is None
        assert [reason.code for reason in outcome.reasons] == [absence.code]

    def test_missing_calculation_result_blocks(self) -> None:
        outcome = synthesize(
            RISER_STRUCTURE,
            scenario=CalcScenario.EXPECTED,
            scope=SCOPE,
            calculation_run_id=GOLDEN_RUN,
            results={"demo.risers_min": result("demo.risers_min", "4")},
            facts=_facts(INLETS, FLOORS),
            rules=_rules("topology"),
            handlers=HANDLERS,
        )
        assert [reason.code for reason in outcome.reasons] == [
            CalcBlockCode.CALCULATION_RESULT_MISSING
        ]

    def test_optional_fact_absent_is_not_zero(self) -> None:
        graph = _graph(_run(facts=_facts(INLETS, FLOORS)))
        assert "shafts" not in {node.id for node in graph.nodes}

    def test_t06_t07_no_path_to_vor_legacy_or_facts_writes(self) -> None:
        """Синтез не импортирует ВОР, карантин и запись реестра фактов; eval и exec нет."""
        forbidden = (
            "app.services.calc.rules.legacy",
            "app.services.calc.adapters",
            "app.services.calc.facts.registry",
            "app.services.calc.rules.registry",
        )
        for path in SYNTHESIS.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith(forbidden), f"{path.name}: {node.module}"
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    assert node.func.id not in {"eval", "exec", "compile", "__import__"}
            assert "CUSTOMER_VOR" not in path.read_text(encoding="utf-8"), path.name


def test_t28_demo_synthesizer_hidden_by_default() -> None:
    assert {item.synthesizer_id for item in list_synthesizers()} == {
        "vk.b1.structure",
        "vk.t3.structure",
        "vk.t4.structure",
        "vk.k1.structure",
    }
    debug = {item.synthesizer_id for item in list_synthesizers(include_demo=True)}
    assert debug == {"vk.b1.structure", "vk.t3.structure", "vk.t4.structure", "vk.k1.structure"} | {
        "test.riser_structure"
    }


def test_t32_calc_portal_stays_off() -> None:
    flag = FEATURES["calc.portal"]
    assert flag.default is False and flag.admin_editable is False


def test_blocking_reason_contract_is_shared() -> None:
    reason = CalcBlockingReason(code=CalcBlockCode.CALCULATION_NOT_USABLE, message="x")
    assert reason.code.value == "CALCULATION_NOT_USABLE"
