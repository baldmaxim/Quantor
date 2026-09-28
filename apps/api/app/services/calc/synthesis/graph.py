"""Граф системы: проверки, счёт экземпляров, итоги атрибутов, отпечаток. Чистые функции.

Кратность и повторяемость имеют один смысл:

- `cardinality` — сколько экземпляров узла на одного «родителя» (или всего, если множителей нет);
- `multiplicity` — сколько раз повторяется группа (типовой этаж ×24);
- `multipliers` — узлы, число экземпляров которых умножает кратность: ветвь «на стояк и этаж».

Итог атрибута: `TOTAL` не умножается никогда — он уже итог; `PER_INSTANCE` умножается на число
экземпляров узла. Так «длина уже на 20 этажей × 20» невыразима.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from app.contracts.calc.enums import (
    CalcElementProvenance,
    CalcQuantityBasis,
    CalcRuleType,
    CalcScenario,
    CalcSynthesisRuleRole,
)
from app.contracts.calc.synthesis import (
    CalcQuantityAttr,
    CalcSystemEdge,
    CalcSystemGraph,
    CalcSystemNode,
)
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.numbers import parse_exact

Range = tuple[Decimal, Decimal]


def graph_sha256(graph: CalcSystemGraph) -> str:
    return canonical_sha256(graph.model_dump(mode="json"))


def _element_problems(element: CalcSystemNode | CalcSystemEdge, where: str) -> list[str]:
    """Происхождение подкреплено основанием своего вида."""
    kinds = {source.kind for source in element.sources}
    problems: list[str] = []
    match element.provenance:
        case CalcElementProvenance.OBSERVED:
            if "FACT" not in kinds:
                problems.append(f"{where}: наблюдённое без факта объекта")
        case CalcElementProvenance.CALCULATED:
            if "CALCULATION_RESULT" not in kinds:
                problems.append(f"{where}: рассчитанное без результата расчёта")
        case CalcElementProvenance.SYNTHESIZED:
            if not any(
                rule.rule_type is not CalcRuleType.TENDER_ASSUMPTION for rule in element.rules
            ):
                problems.append(f"{where}: синтезированное без утверждённого правила синтеза")
        case CalcElementProvenance.ASSUMED:
            if not any(
                rule.rule_type is CalcRuleType.TENDER_ASSUMPTION
                and rule.role is CalcSynthesisRuleRole.ASSUMPTION
                for rule in element.rules
            ):
                problems.append(f"{where}: принятое допущением без тендерного допущения")
    if not element.support.strip():
        problems.append(f"{where}: не сказано, почему элемент нужен")
    return problems


def graph_problems(graph: CalcSystemGraph) -> list[str]:
    """Ошибки графа. Непустой список — ошибка синтезатора: запуск FAILED, а не граф."""
    problems: list[str] = []
    node_ids = [node.id for node in graph.nodes]
    edge_ids = [edge.id for edge in graph.edges]
    if len(set(node_ids)) != len(node_ids) or len(set(edge_ids)) != len(edge_ids):
        problems.append("идентификаторы элементов повторяются")
    if set(node_ids) & set(edge_ids):
        problems.append("узел и связь с одним идентификатором")
    nodes = {node.id: node for node in graph.nodes}
    for node in graph.nodes:
        problems.extend(_element_problems(node, f"узел «{node.id}»"))
        if node.estimate is not None and graph.scenario is not CalcScenario.MINIMUM:
            problems.append(f"узел «{node.id}»: нижняя оценка допустима только в MINIMUM")
    for edge in graph.edges:
        problems.extend(_element_problems(edge, f"связь «{edge.id}»"))
        for end in (edge.source_node, edge.target_node):
            if end not in nodes:
                problems.append(f"связь «{edge.id}» ссылается на неизвестный узел «{end}»")
    for element in (*graph.nodes, *graph.edges):
        if element.provenance is CalcElementProvenance.ASSUMED and (
            graph.scenario is not CalcScenario.TENDER_SAFE
        ):
            problems.append(f"«{element.id}»: допущение вне TENDER_SAFE")
        if len(set(element.multipliers)) != len(element.multipliers):
            problems.append(f"«{element.id}»: множитель указан дважды")
        for multiplier in element.multipliers:
            if multiplier == element.id or multiplier not in nodes:
                problems.append(f"«{element.id}»: неверный множитель «{multiplier}»")
    problems.extend(_multiplier_cycles(graph))
    for item in graph.unresolved:
        if item.element_id is not None and item.element_id not in set(node_ids) | set(edge_ids):
            problems.append(f"нерешённое «{item.key}» ссылается на неизвестный элемент")
    return problems


def _multiplier_cycles(graph: CalcSystemGraph) -> list[str]:
    edges = {node.id: set(node.multipliers) for node in graph.nodes}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in done:
            return False
        if node_id in visiting:
            return True
        visiting.add(node_id)
        cyclic = any(visit(item) for item in sorted(edges.get(node_id, set())))
        visiting.discard(node_id)
        done.add(node_id)
        return cyclic

    return ["множители узлов образуют цикл"] if any(visit(key) for key in sorted(edges)) else []


def _count(node: CalcSystemNode) -> Range:
    cardinality = node.cardinality
    if cardinality.selected is not None:
        value = Decimal(cardinality.selected)
        return value, value
    return Decimal(cardinality.min), Decimal(cardinality.max)


def instances(graph: CalcSystemGraph, element_id: str) -> Range:
    """Число экземпляров узла или связи с учётом множителей и повторяемости групп."""
    nodes: Mapping[str, CalcSystemNode] = {node.id: node for node in graph.nodes}
    element = nodes.get(element_id) or next(e for e in graph.edges if e.id == element_id)
    low, high = _count(element) if isinstance(element, CalcSystemNode) else (Decimal(1),) * 2
    for multiplier in element.multipliers:
        node = nodes[multiplier]
        m_low, m_high = instances(graph, multiplier)
        low *= m_low * node.multiplicity
        high *= m_high * node.multiplicity
    return low, high


def attribute_total(graph: CalcSystemGraph, element_id: str, name: str) -> Range:
    """Итог атрибута по всем экземплярам. TOTAL не умножается: он уже итог."""
    element = next(e for e in (*graph.nodes, *graph.edges) if e.id == element_id)
    attribute: CalcQuantityAttr = next(item for item in element.attributes if item.name == name)
    if attribute.value is not None:
        low = high = parse_exact(attribute.value)
    else:
        low = parse_exact(attribute.low) if attribute.low is not None else Decimal(0)
        high = parse_exact(attribute.high) if attribute.high is not None else low
    if attribute.basis is CalcQuantityBasis.TOTAL:
        return low, high
    count_low, count_high = instances(graph, element_id)
    return low * count_low, high * count_high
