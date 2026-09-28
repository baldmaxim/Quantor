"""«Почему Quantor считает, что этот элемент нужен?» и сравнение графов. Чистые функции.

Цепочка собирается из структуры запуска, без модели:

- рассчитанное: элемент → результат расчёта → шаг → версия правила → факт → свидетельство
  (цепочка ядра PROMPT 04 целиком);
- наблюдённое: элемент → факт объекта → свидетельство;
- синтезированное: элемент → решение → утверждённая версия правила;
- принятое допущением: элемент → тендерное допущение → решение ответственного лица.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.contracts.calc.engine import CalcRuleBinding, CalcRunRead, CalcSnapshotItem
from app.contracts.calc.enums import CalcElementProvenance, CalcSynthesisTraceKind
from app.contracts.calc.synthesis import (
    CalcElementDiff,
    CalcSynthesisCompareRead,
    CalcSynthesisDecisionRead,
    CalcSynthesisRuleRef,
    CalcSynthesisRunRead,
    CalcSynthesisTraceNode,
    CalcSynthesisTraceRead,
    CalcSystemEdge,
    CalcSystemGraph,
    CalcSystemNode,
)
from app.services.calc.engine.trace import explain
from app.services.calc.rules.validation import source_label

PROVENANCE_TITLES = {
    CalcElementProvenance.OBSERVED: "наблюдено в документации",
    CalcElementProvenance.CALCULATED: "следует из расчёта",
    CalcElementProvenance.SYNTHESIZED: "предложено синтезом по правилу",
    CalcElementProvenance.ASSUMED: "принято тендерным допущением",
}


def _cardinality_text(node: CalcSystemNode) -> str:
    cardinality = node.cardinality
    if cardinality.selected is not None:
        return f"выбрано {cardinality.selected} из {cardinality.min}–{cardinality.max}"
    if cardinality.min == cardinality.max:
        return f"{cardinality.min}"
    return f"{cardinality.min}–{cardinality.max} — не выбрано"


class _Tracer:
    def __init__(
        self,
        run: CalcSynthesisRunRead,
        graph: CalcSystemGraph,
        calculation: CalcRunRead,
        decisions: Mapping[str, CalcSynthesisDecisionRead],
    ) -> None:
        self.run = run
        self.graph = graph
        self.calculation = calculation
        self.decisions = decisions
        self.bindings: Mapping[str, CalcRuleBinding] = {
            f"{item.rule_key}@{item.version}": item for item in run.rule_bindings
        }
        self.facts: Mapping[str, CalcSnapshotItem] = {
            item.fact_key: item for item in run.snapshot.items
        }

    def rule(self, ref: CalcSynthesisRuleRef) -> CalcSynthesisTraceNode:
        key = f"{ref.rule_key}@{ref.version}"
        binding = self.bindings.get(key)
        text = f"{ref.rule_type.value}, роль {ref.role.value}, реализация {ref.implementation_key}"
        if binding is not None:
            text += f"; формула: {binding.content.formula}; источники: " + (
                "; ".join(source_label(item) for item in binding.content.sources) or "—"
            )
        return CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.RULE,
            key=key,
            title=binding.content.title if binding is not None else ref.rule_key,
            text=text,
            ref=None if binding is None else str(binding.rule_version_id),
        )

    def fact(self, fact_key: str) -> CalcSynthesisTraceNode:
        item = self.facts.get(fact_key)
        if item is None:
            return CalcSynthesisTraceNode(
                kind=CalcSynthesisTraceKind.FACT, key=fact_key, title=fact_key, text="нет в снимке"
            )
        value = getattr(item.value, "value", item.value.kind)
        return CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.FACT,
            key=fact_key,
            title=item.fact_type,
            text=(
                f"значение {value}; способ {item.method.value}, уверенность "
                f"{item.confidence.value}, выбор {item.resolution_state.value}"
            ),
            ref=str(item.fact_id),
            children=[
                CalcSynthesisTraceNode(
                    kind=CalcSynthesisTraceKind.EVIDENCE,
                    key=str(evidence.id),
                    title=evidence.kind.value,
                    text=evidence.locator or "свидетельство утверждения",
                    ref=str(evidence.id),
                )
                for evidence in item.evidence
            ],
        )

    def decision(self, decision_id: str) -> CalcSynthesisTraceNode:
        decision = self.decisions.get(decision_id)
        return CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.HUMAN_DECISION,
            key=decision_id,
            title="Решение инженера",
            text=(
                "нет данных решения"
                if decision is None
                else f"выбрано {decision.selected_count} из {decision.alternatives}: "
                f"{decision.comment}"
            ),
            ref=decision_id,
        )

    def element(self, element: CalcSystemNode | CalcSystemEdge) -> CalcSynthesisTraceNode:
        children: list[CalcSynthesisTraceNode] = []
        if isinstance(element, CalcSystemNode) and element.cardinality.selection is not None:
            selection = element.cardinality.selection
            decision_children = []
            if selection.rule is not None:
                decision_children.append(self.rule(selection.rule))
            if selection.decision_id is not None:
                decision_children.append(self.decision(str(selection.decision_id)))
            children.append(
                CalcSynthesisTraceNode(
                    kind=CalcSynthesisTraceKind.DECISION,
                    key=f"{element.id}.selection",
                    title="Выбор кратности",
                    text=f"{_cardinality_text(element)}: {selection.explanation}",
                    children=decision_children,
                )
            )
        selected_rule = (
            element.cardinality.selection.rule
            if isinstance(element, CalcSystemNode) and element.cardinality.selection is not None
            else None
        )
        for ref in element.rules:
            if ref != selected_rule:
                children.append(self.rule(ref))
        for source in element.sources:
            if source.kind == "CALCULATION_RESULT":
                known = any(item.result_key == source.key for item in self.calculation.results)
                children.append(
                    CalcSynthesisTraceNode(
                        kind=CalcSynthesisTraceKind.CALCULATION_RESULT,
                        key=source.key,
                        title=f"Результат расчёта {source.key}",
                        text=f"{source.value} {source.unit or ''}".rstrip()
                        + f" — запуск {source.run_id}",
                        ref=None if source.run_id is None else str(source.run_id),
                        calculation=explain(self.calculation, source.key) if known else None,
                    )
                )
            elif source.kind == "FACT":
                children.append(self.fact(source.key))
        for assumption in self.graph.assumptions:
            if element.id in assumption.element_ids:
                children.append(
                    CalcSynthesisTraceNode(
                        kind=CalcSynthesisTraceKind.ASSUMPTION,
                        key=f"{assumption.rule.rule_key}@{assumption.rule.version}",
                        title="Тендерное допущение",
                        text=f"{assumption.notice} {assumption.reason}. Влияние: "
                        f"{assumption.impact or 'не описано'}",
                        children=[self.rule(assumption.rule)],
                    )
                )
        text = f"{element.title} ({PROVENANCE_TITLES[element.provenance]}). {element.support}"
        if isinstance(element, CalcSystemNode):
            text += f"; кратность {_cardinality_text(element)}"
            if element.multiplicity > 1:
                text += f"; повторяется ×{element.multiplicity}"
        return CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.ELEMENT,
            key=element.id,
            title=element.title,
            text=text,
            children=children,
        )


def element_trace(
    run: CalcSynthesisRunRead,
    graph: CalcSystemGraph,
    calculation: CalcRunRead,
    element_id: str,
) -> CalcSynthesisTraceRead:
    """Цепочка объяснения элемента. KeyError — такого элемента в графе нет."""
    element: CalcSystemNode | CalcSystemEdge | None = next(
        (node for node in graph.nodes if node.id == element_id), None
    ) or next((edge for edge in graph.edges if edge.id == element_id), None)
    if element is None:
        raise KeyError(element_id)
    decisions = {str(item.id): item for item in (*run.applied_decisions, *run.decisions)}
    root = _Tracer(run, graph, calculation, decisions).element(element)
    return CalcSynthesisTraceRead(
        run_id=run.id,
        element_id=element_id,
        provenance=element.provenance,
        text=root.text,
        root=root,
    )


def _diff(
    base: list[CalcSystemNode] | list[CalcSystemEdge],
    other: list[CalcSystemNode] | list[CalcSystemEdge],
) -> list[CalcElementDiff]:
    before = {item.id: item.model_dump(mode="json") for item in base}
    after = {item.id: item.model_dump(mode="json") for item in other}
    diffs: list[CalcElementDiff] = []
    for key in sorted(set(before) | set(after)):
        if key not in after:
            diffs.append(CalcElementDiff(element_id=key, change="REMOVED", fields=[]))
        elif key not in before:
            diffs.append(CalcElementDiff(element_id=key, change="ADDED", fields=[]))
        else:
            fields = sorted(name for name in before[key] if before[key][name] != after[key][name])
            if fields:
                diffs.append(CalcElementDiff(element_id=key, change="CHANGED", fields=fields))
    return diffs


def compare(
    base: CalcSynthesisRunRead,
    base_graph: CalcSystemGraph | None,
    other: CalcSynthesisRunRead,
    other_graph: CalcSystemGraph | None,
) -> CalcSynthesisCompareRead:
    base_nodes = [] if base_graph is None else base_graph.nodes
    other_nodes = [] if other_graph is None else other_graph.nodes
    base_edges = [] if base_graph is None else base_graph.edges
    other_edges = [] if other_graph is None else other_graph.edges
    before = {item.key for item in base.unresolved}
    after = {item.key for item in other.unresolved}
    return CalcSynthesisCompareRead(
        base_run_id=base.id,
        other_run_id=other.id,
        same_synthesizer=(base.synthesizer_id, base.synthesizer_version, base.implementation_sha256)
        == (other.synthesizer_id, other.synthesizer_version, other.implementation_sha256),
        same_calculation=base.calculation_run_id == other.calculation_run_id,
        nodes=_diff(base_nodes, other_nodes),
        edges=_diff(base_edges, other_edges),
        unresolved_added=sorted(after - before),
        unresolved_removed=sorted(before - after),
    )
