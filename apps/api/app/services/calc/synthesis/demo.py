"""Демо-синтезатор `test.riser_structure@1` — доказательство архитектуры, не синтез ВК.

Из запуска `test.riser_demand@1` (диапазон числа стояков) и фактов (ввод, этажность, шахты):

```text
ввод (OBSERVED) ─SUPPLY→ стояки (CALCULATED, 4–5) ─BRANCH_CONNECTION→ этажная ветвь
                                                  (SYNTHESIZED, на стояк и этаж)
типовой этаж (OBSERVED, ×24) ─CONTAINS→ этажная ветвь
шахты (OBSERVED, 2) — размещение стояков по шахтам не определено
резервные стояки (ASSUMED, только TENDER_SAFE)
```

Правила: топология (ветвь на стояк и этаж), выбор кратности из диапазона, тендерный резерв —
только утверждённые версии. Нет топологии — узлы есть, связей нет, запуск PARTIAL. Нет правила
выбора — диапазон остаётся диапазоном, варианты перечислены, вероятностей нет.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Final

from app.contracts.calc.engine import CalcResultRead, CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcElementProvenance,
    CalcRuleType,
    CalcScenario,
    CalcSelectionSource,
    CalcSynthesisRuleRole,
    CalcUnresolvedKind,
)
from app.contracts.calc.rules import TENDER_NOTICE
from app.contracts.calc.synthesis import (
    CalcCardinality,
    CalcElementSource,
    CalcScenarioEstimate,
    CalcSelection,
    CalcSynthesisAssumption,
    CalcSynthesisRuleRef,
    CalcSynthesisVariant,
    CalcSystemEdge,
    CalcSystemGraph,
    CalcSystemNode,
    CalcUnresolvedItem,
    CalcVariantSelection,
)
from app.contracts.calc.values import CalcCountValue
from app.services.calc.engine.numbers import exact_text
from app.services.calc.synthesis.definitions import (
    BuildResult,
    SynthesisContext,
    SynthesisFactSpec,
    SynthesizerDef,
)
from app.services.calc.synthesis.demo_rules import RULE_KEYS
from app.services.calc.synthesis.rules import (
    AppliedRule,
    ResultInput,
    RuleUnavailable,
    SynthesisRuleSpec,
)

MAX_VARIANTS: Final = 5
"""Больше вариантов не перечисляется — хранится только диапазон. Это предел показа, не инженерия."""


def _count(item: CalcSnapshotItem) -> int:
    if not isinstance(item.value, CalcCountValue):
        raise ValueError(f"факт {item.fact_key} — не счётчик")
    return item.value.value


def _fact_source(item: CalcSnapshotItem) -> CalcElementSource:
    value = item.value
    return CalcElementSource(
        kind="FACT",
        key=item.fact_key,
        fact_id=item.fact_id,
        value=str(value.value) if isinstance(value, CalcCountValue) else None,
        unit=value.unit if isinstance(value, CalcCountValue) else None,
    )


def _result_source(context: SynthesisContext, result: CalcResultRead) -> CalcElementSource:
    return CalcElementSource(
        kind="CALCULATION_RESULT",
        key=result.result_key,
        run_id=context.calculation_run_id,
        value=result.value,
        unit=result.unit,
    )


def _integer(value: Decimal, what: str) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"{what}: {value} — не целое")
    return int(value)


class _Builder:
    def __init__(self, context: SynthesisContext) -> None:
        self.context = context
        self.nodes: list[CalcSystemNode] = []
        self.edges: list[CalcSystemEdge] = []
        self.unresolved: list[CalcUnresolvedItem] = []
        self.assumptions: list[CalcSynthesisAssumption] = []
        self.warnings: list[str] = []
        self.variant_counts: list[int] = []
        self.applied: list[uuid.UUID] = []

    def applied_rule(self, name: str) -> AppliedRule | None:
        used = self.context.rules.get(name)
        return used if isinstance(used, AppliedRule) else None

    def unavailable(self, name: str) -> str:
        used = self.context.rules.get(name)
        if isinstance(used, RuleUnavailable):
            return used.message
        return "правило не применяется в этом сценарии"

    def node(self, **values: object) -> CalcSystemNode:
        node = CalcSystemNode.model_validate({"scope": self.context.scope, **values})
        self.nodes.append(node)
        return node

    def edge(self, **values: object) -> CalcSystemEdge:
        edge = CalcSystemEdge.model_validate(values)
        self.edges.append(edge)
        return edge

    def risers(self) -> CalcSystemNode:
        context = self.context
        low_result = context.results["demo.risers_min"]
        high_result = context.results["demo.risers_max"]
        low = _integer(Decimal(low_result.value), "нижняя граница")
        high = _integer(Decimal(high_result.value), "верхняя граница")
        sources = [_result_source(context, low_result), _result_source(context, high_result)]
        rules: list[CalcSynthesisRuleRef] = []
        selected: int | None = None
        selection: CalcSelection | None = None
        estimate: CalcScenarioEstimate | None = None
        if low != high:
            decision = next((item for item in context.decisions if item.node_id == "risers"), None)
            choice = self.applied_rule("selection")
            if context.scenario is CalcScenario.MINIMUM:
                estimate = CalcScenarioEstimate(
                    value=low,
                    meaning="LOWER_BOUND",
                    note="Нижняя оценка для MINIMUM, а не проектное решение: выбор не сделан",
                )
                if decision is not None:
                    self.warnings.append("Решение инженера к нижней оценке MINIMUM не применяется")
            elif decision is not None and low <= decision.selected_count <= high:
                selected = decision.selected_count
                selection = CalcSelection(
                    source=CalcSelectionSource.HUMAN_DECISION,
                    decision_id=decision.id,
                    explanation=f"Решение инженера: {selected} ст. — {decision.comment}",
                )
                sources.append(
                    CalcElementSource(
                        kind="HUMAN_DECISION", key=str(decision.id), value=str(selected)
                    )
                )
                self.applied.append(decision.id)
            elif choice is not None:
                if decision is not None:
                    self.warnings.append(
                        f"Решение инженера {decision.selected_count} вне диапазона расчёта "
                        f"{low}–{high} — не применено"
                    )
                selected = _integer(choice.outputs["count"], "выбор правила")
                if not low <= selected <= high:
                    raise ValueError(f"правило выбрало {selected} вне диапазона {low}–{high}")
                rules.append(choice.ref)
                selection = CalcSelection(
                    source=CalcSelectionSource.RULE, rule=choice.ref, explanation=choice.explanation
                )
            elif decision is not None:
                self.warnings.append(
                    f"Решение инженера {decision.selected_count} вне диапазона расчёта "
                    f"{low}–{high} — не применено"
                )
        node = self.node(
            id="risers",
            semantic_type="RISER_GROUP",
            title="Стояки",
            provenance=CalcElementProvenance.CALCULATED,
            sources=sources,
            rules=rules,
            cardinality=CalcCardinality(min=low, max=high, selected=selected, selection=selection),
            estimate=estimate,
            support=f"Необходимость стояков следует из расчёта: {low}–{high} ст."
            if low != high
            else f"Необходимость стояков следует из расчёта: {low} ст.",
        )
        if low != high and selected is None:
            self.unresolved.append(
                CalcUnresolvedItem(
                    key="risers.count",
                    kind=CalcUnresolvedKind.COUNT_RANGE,
                    title="Количество стояков",
                    element_id="risers",
                    known=f"{low}–{high} по расчёту",
                    needed="утверждённое правило выбора или решение инженера",
                    structural=True,
                )
            )
            if context.scenario is not CalcScenario.MINIMUM:
                self.add_variants(low, high)
        return node

    def add_variants(self, low: int, high: int) -> None:
        if high - low + 1 > MAX_VARIANTS:
            self.warnings.append(
                f"Допустимых значений больше {MAX_VARIANTS} — хранится только диапазон {low}–{high}"
            )
            return
        self.variant_counts = list(range(low, high + 1))

    def variants(self) -> tuple[CalcSynthesisVariant, ...]:
        if not self.variant_counts:
            return ()
        low, high = self.variant_counts[0], self.variant_counts[-1]
        open_questions = [
            item.title for item in self.unresolved if item.structural and item.key != "risers.count"
        ]
        return tuple(
            CalcSynthesisVariant(
                key=f"risers_{count}",
                title=f"{count} стояков",
                selections=[CalcVariantSelection(node_id="risers", count=count)],
                reasons=[
                    f"{count} в пределах расчёта {low}–{high}",
                    "правила выбора нет — вариант не выбран и не взвешен",
                ],
                open_questions=open_questions,
            )
            for count in self.variant_counts
        )

    def build(self) -> BuildResult:
        context = self.context
        inlets = context.facts["inlets"]
        floors = context.facts["floors"]
        inlet_count = _count(inlets)
        floor_count = _count(floors)
        self.node(
            id="inlet",
            semantic_type="INLET",
            title="Ввод",
            provenance=CalcElementProvenance.OBSERVED,
            sources=[_fact_source(inlets)],
            cardinality=CalcCardinality(min=inlet_count, max=inlet_count),
            support=f"Ввод указан в документации: {inlet_count}",
        )
        self.risers()
        self.node(
            id="typical_floors",
            semantic_type="TYPICAL_FLOOR_GROUP",
            title="Типовой этаж",
            provenance=CalcElementProvenance.OBSERVED,
            sources=[_fact_source(floors)],
            cardinality=CalcCardinality(min=1, max=1),
            multiplicity=floor_count,
            support=f"Этажность по документации: типовой этаж повторяется {floor_count} раз",
        )
        shafts = context.facts.get("shafts")
        if shafts is not None:
            shaft_count = _count(shafts)
            self.node(
                id="shafts",
                semantic_type="SHAFT_GROUP",
                title="Шахты",
                provenance=CalcElementProvenance.OBSERVED,
                sources=[_fact_source(shafts)],
                cardinality=CalcCardinality(min=shaft_count, max=shaft_count),
                support=f"Шахты указаны в документации: {shaft_count}",
            )
            self.unresolved.append(
                CalcUnresolvedItem(
                    key="risers.placement",
                    kind=CalcUnresolvedKind.PLACEMENT,
                    title="Размещение стояков по шахтам",
                    element_id="shafts",
                    known=f"шахт {shaft_count}",
                    needed="утверждённое правило размещения — без него стояки не размещаются",
                    structural=True,
                )
            )
        self.topology()
        self.reserve()
        graph = CalcSystemGraph(
            graph_type="test.riser_structure",
            discipline=CalcDiscipline.VK,
            system_code=context.scope.system_code,
            scope=context.scope,
            scenario=context.scenario,
            synthesizer_id=context.definition.synthesizer_id,
            synthesizer_version=context.definition.version,
            nodes=self.nodes,
            edges=self.edges,
            unresolved=self.unresolved,
            assumptions=self.assumptions,
            warnings=self.warnings,
        )
        return BuildResult(graph, self.variants(), tuple(self.applied))

    def topology(self) -> None:
        rule = self.applied_rule("topology")
        if rule is None:
            self.unresolved.append(
                CalcUnresolvedItem(
                    key="topology",
                    kind=CalcUnresolvedKind.MISSING_RULE,
                    title="Связи ввода, стояков и этажных ветвей",
                    known="элементы системы известны",
                    needed=f"утверждённое правило топологии {RULE_KEYS['topology']} "
                    f"({self.unavailable('topology')})",
                    structural=True,
                )
            )
            return
        branches = _integer(rule.outputs["branches"], "ветвей на стояк и этаж")
        support = f"По правилу {rule.rule.rule_key}@{rule.rule.version}: {rule.explanation}"
        self.node(
            id="floor_branch",
            semantic_type="FLOOR_BRANCH",
            title="Этажная ветвь",
            provenance=CalcElementProvenance.SYNTHESIZED,
            rules=[rule.ref],
            cardinality=CalcCardinality(min=branches, max=branches),
            multipliers=["risers", "typical_floors"],
            support=support + " — на каждый стояк на каждом типовом этаже",
        )
        self.edge(
            id="supply_main",
            semantic_type="SUPPLY",
            title="Магистраль от ввода к стоякам",
            provenance=CalcElementProvenance.SYNTHESIZED,
            rules=[rule.ref],
            source_node="inlet",
            target_node="risers",
            multipliers=["risers"],
            support=support + " — ввод питает каждый стояк",
        )
        self.edge(
            id="riser_branches",
            semantic_type="BRANCH_CONNECTION",
            title="Присоединение этажной ветви к стояку",
            provenance=CalcElementProvenance.SYNTHESIZED,
            rules=[rule.ref],
            source_node="risers",
            target_node="floor_branch",
            multipliers=["floor_branch"],
            support=support + " — узел присоединения на каждую ветвь",
        )
        self.edge(
            id="floor_membership",
            semantic_type="CONTAINS",
            title="Ветви на типовом этаже",
            provenance=CalcElementProvenance.SYNTHESIZED,
            rules=[rule.ref],
            source_node="typical_floors",
            target_node="floor_branch",
            support=support,
        )
        self.unresolved.append(
            CalcUnresolvedItem(
                key="supply_main.route",
                kind=CalcUnresolvedKind.ROUTE,
                title="Трасса магистрали от ввода до стояков",
                element_id="supply_main",
                known="логическая связь ввода со стояками",
                needed="трасса РД или утверждённое правило оценки длины — координаты не "
                "выдумываются",
                structural=False,
            )
        )

    def reserve(self) -> None:
        context = self.context
        if context.scenario is not CalcScenario.TENDER_SAFE:
            return
        rule = self.applied_rule("reserve")
        if rule is None:
            self.warnings.append(
                "TENDER_SAFE = EXPECTED: утверждённого тендерного допущения нет "
                f"({self.unavailable('reserve')})"
            )
            return
        count = _integer(rule.outputs["reserve"], "резерв стояков")
        support = (
            f"Тендерное допущение {rule.rule.rule_key}@{rule.rule.version}: {rule.explanation}"
        )
        elements = ["reserve_risers"]
        self.node(
            id="reserve_risers",
            semantic_type="RISER_GROUP",
            title="Резервные стояки",
            provenance=CalcElementProvenance.ASSUMED,
            rules=[rule.ref],
            cardinality=CalcCardinality(min=count, max=count),
            support=support,
        )
        if self.applied_rule("topology") is not None:
            self.edge(
                id="reserve_supply",
                semantic_type="SUPPLY",
                title="Магистраль к резервным стоякам",
                provenance=CalcElementProvenance.ASSUMED,
                rules=[rule.ref],
                source_node="inlet",
                target_node="reserve_risers",
                multipliers=["reserve_risers"],
                support=support,
            )
            elements.append("reserve_supply")
        self.assumptions.append(
            CalcSynthesisAssumption(
                element_ids=elements,
                rule=rule.ref,
                reason="Сценарий TENDER_SAFE допускает утверждённые тендерные допущения",
                impact=rule.rule.content.impact,
                notice=TENDER_NOTICE,
                value=exact_text(Decimal(count)),
                unit="riser",
            )
        )


def build(context: SynthesisContext) -> BuildResult:
    return _Builder(context).build()


def _golden_contexts() -> dict[str, SynthesisContext]:
    from app.services.calc.synthesis.golden import golden_contexts

    return golden_contexts()


RISER_STRUCTURE: Final = SynthesizerDef(
    synthesizer_id="test.riser_structure",
    version=1,
    title="ДЕМО: структура стояков — проверка синтеза, не синтез ВК",
    kind=CalcCalculatorKind.DEMO,
    discipline=CalcDiscipline.VK,
    systems=("В1",),
    stage=CalcDocumentStage.P,
    scenarios=frozenset(CalcScenario),
    graph_type="test.riser_structure",
    calculator_id="test.riser_demand",
    calculator_version=1,
    results=("demo.risers_min", "demo.risers_max"),
    facts={
        "inlets": SynthesisFactSpec(
            "system.inlets_count", ("building", "discipline", "system_code")
        ),
        "floors": SynthesisFactSpec("building.floors_above_ground", ("building",)),
        "shafts": SynthesisFactSpec("floor.shafts_count", ("building", "floor"), required=False),
    },
    rules={
        "topology": SynthesisRuleSpec(
            role=CalcSynthesisRuleRole.TOPOLOGY,
            rule_key=RULE_KEYS["topology"],
            allowed_types=frozenset({CalcRuleType.ENGINEERING, CalcRuleType.GEOMETRY}),
            outputs=("branches",),
        ),
        "selection": SynthesisRuleSpec(
            role=CalcSynthesisRuleRole.SELECTION,
            rule_key=RULE_KEYS["selection"],
            allowed_types=frozenset({CalcRuleType.ENGINEERING}),
            outputs=("count",),
            inputs={
                "count_min": ResultInput("demo.risers_min"),
                "count_max": ResultInput("demo.risers_max"),
            },
        ),
        "reserve": SynthesisRuleSpec(
            role=CalcSynthesisRuleRole.ASSUMPTION,
            rule_key=RULE_KEYS["reserve"],
            allowed_types=frozenset({CalcRuleType.TENDER_ASSUMPTION}),
            outputs=("reserve",),
        ),
    },
    build=build,
    golden=(
        ("range_expected", "67cb7f1a939841bbc318092ab595860f602e3a4876d3a9b587301cf04d3871f8"),
        ("tender_selected", "2623cd8c4a88af6e86e73e98433bd8aa99285393a728cfa2baf20fa28f2753d6"),
    ),
    golden_contexts=_golden_contexts,
)
