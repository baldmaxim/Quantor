"""Связи графа ВК: магистраль, этажные подключения, арматура по узлам, выпуски и потребители.

Связи появляются только по утверждённому правилу схемы: без него элементы есть, связей нет, и
это структурная неопределённость (запуск PARTIAL). Этажное подключение — узел «на каждый стояк
на каждом обслуживаемом этаже» (множители), поэтому типовой этаж не умножается дважды.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.contracts.calc.enums import CalcElementProvenance, CalcQuantityBasis, CalcUnresolvedKind
from app.contracts.calc.synthesis import CalcCardinality, CalcQuantityAttr, CalcSystemNode
from app.services.calc.synthesis.rules import AppliedRule
from app.services.calc.systems.vk.graph_parts import (
    attr_range,
    attr_value,
    code_of,
    decimal_of,
    fact_source,
    number_of,
    result_source,
    whole,
)

if TYPE_CHECKING:
    from app.services.calc.systems.vk.structure import Builder

_O, _C, _S = (
    CalcElementProvenance.OBSERVED,
    CalcElementProvenance.CALCULATED,
    CalcElementProvenance.SYNTHESIZED,
)


def _main(builder: Builder, topology: AppliedRule | None) -> CalcSystemNode | None:
    length = builder.fact("main_length")
    length_value = None if length is None else number_of(length)
    if (length is None or length_value is None) and topology is None:
        builder.issue(
            "main.route",
            CalcUnresolvedKind.ROUTE,
            "Магистраль",
            "магистраль в документах не описана, схема системы не утверждена",
            "длина по документу или обмеру; методики грубой трассировки нет — длина не "
            "выводится из коридора",
            structural=False,
        )
        return None
    attributes: list[CalcQuantityAttr] = []
    diameter = builder.fact("main_diameter")
    diameter_value = None if diameter is None else number_of(diameter)
    if diameter is not None and diameter_value is not None:
        attributes.append(
            attr_value("diameter", diameter_value, "mm", CalcQuantityBasis.TOTAL, "по схеме")
        )
    common = {
        "id": "main",
        "semantic_type": "MAIN_LINE",
        "title": "Магистраль",
        "cardinality": CalcCardinality(min=1, max=1),
    }
    if length is not None and length_value is not None:
        attributes.append(
            attr_value("length", length_value, "m", CalcQuantityBasis.TOTAL, "документ или обмер")
        )
        return builder.node(
            **common,
            provenance=_O,
            sources=[fact_source(length)]
            + ([] if diameter is None or diameter_value is None else [fact_source(diameter)]),
            attributes=attributes,
            support=f"Длина магистрали указана: {length_value} м",
        )
    if topology is None:
        raise ValueError("магистраль без длины строится только по схеме")
    builder.issue(
        "main.route",
        CalcUnresolvedKind.ROUTE,
        "Трасса магистрали",
        "магистраль есть в схеме",
        "длина по документу или обмеру — трасса не выдумывается",
        structural=False,
        element_id="main",
    )
    return builder.node(
        **common,
        provenance=_S,
        rules=[topology.ref],
        sources=[] if diameter is None or diameter_value is None else [fact_source(diameter)],
        attributes=attributes,
        support=f"По схеме {topology.rule.rule_key}@{topology.rule.version}: магистраль "
        "связывает начало системы со стояками",
    )


def _connections(builder: Builder, topology: AppliedRule) -> CalcSystemNode:
    per = decimal_of(topology.outputs["connections"])
    attributes: list[CalcQuantityAttr] = []
    sources = []
    low = builder.result("quantity.connection_length_min")
    high = builder.result("quantity.connection_length_max")
    if low is not None and high is not None:
        attributes.append(attr_range("length", low, high, note="на одно подключение, по правилу"))
        sources = [
            result_source(builder.context, low),
            result_source(builder.context, high),
        ]
    else:
        rule_key = builder.spec.connection_rule
        builder.issue(
            "connections.length",
            CalcUnresolvedKind.ROUTE,
            "Длина этажных подключений",
            f"подключений {per} на стояк и этаж",
            f"утверждённое правило {rule_key}"
            if rule_key is not None
            else "документ П: для этой системы правила длины подключений нет",
            structural=False,
            element_id="floor_connections",
        )
    return builder.node(
        id="floor_connections",
        semantic_type="FLOOR_CONNECTION",
        title="Этажные подключения",
        provenance=_S,
        rules=[topology.ref],
        sources=sources,
        attributes=attributes,
        cardinality=CalcCardinality(min=per, max=per),
        multipliers=["risers", "served_floors"],
        support=f"По схеме {topology.rule.rule_key}@{topology.rule.version}: "
        f"{topology.explanation} — на каждый стояк на каждом обслуживаемом этаже",
    )


def _edges(
    builder: Builder,
    topology: AppliedRule,
    source: CalcSystemNode | None,
    main: CalcSystemNode | None,
    connections: CalcSystemNode,
) -> None:
    drain = builder.spec.source == "OUTLET"
    ref = [topology.ref]
    support = f"По схеме {topology.rule.rule_key}@{topology.rule.version}"
    flow = "DRAIN" if drain else "SUPPLY"
    if main is not None and source is not None:
        ends = ("main", "source") if drain else ("source", "main")
        builder.edge(
            id="source_main",
            semantic_type=flow,
            title="Магистраль — выпуски" if drain else "Начало системы — магистраль",
            provenance=_S,
            rules=ref,
            source_node=ends[0],
            target_node=ends[1],
            support=support,
        )
    if main is not None:
        ends = ("risers", "main") if drain else ("main", "risers")
        builder.edge(
            id="main_risers",
            semantic_type=flow,
            title="Стояки — магистраль" if drain else "Магистраль — стояки",
            provenance=_S,
            rules=ref,
            source_node=ends[0],
            target_node=ends[1],
            multipliers=["risers"],
            support=support + ": каждый стояк присоединён к магистрали",
        )
    ends = ("floor_connections", "risers") if drain else ("risers", connections.id)
    builder.edge(
        id="riser_branches",
        semantic_type="BRANCH_CONNECTION",
        title="Присоединение этажного подключения к стояку",
        provenance=_S,
        rules=ref,
        source_node=ends[0],
        target_node=ends[1],
        multipliers=["floor_connections"],
        support=support + ": узел присоединения на каждое подключение",
    )


def _valves(builder: Builder) -> None:
    for name, rule_key, node_id, title in (
        ("riser_valves", builder.spec.riser_valves_rule, "riser_valves", "Арматура стояков"),
        ("balancing", builder.spec.balancing_rule, "balancing_valves", "Балансировочная арматура"),
    ):
        if rule_key is None:
            continue
        rule = builder.rule(name)
        if rule is None:
            builder.issue(
                f"valves.{node_id}",
                CalcUnresolvedKind.MISSING_RULE,
                title,
                "стояки известны, правила арматуры нет",
                f"утверждённое правило {rule_key}; «N кранов на этаж» не применяется",
                structural=False,
            )
            continue
        per = decimal_of(rule.outputs["count"])
        builder.node(
            id=node_id,
            semantic_type="VALVE_GROUP",
            title=title,
            provenance=_S,
            rules=[rule.ref],
            cardinality=CalcCardinality(min=per, max=per),
            multipliers=["risers"],
            support=f"По правилу {rule.rule.rule_key}@{rule.rule.version}: {rule.explanation}",
        )


def _drain_points(builder: Builder) -> None:
    if not builder.spec.drain_points:
        return
    observed = builder.result("demand.fixtures_observed")
    by_rooms = builder.result("demand.fixtures_by_rooms")
    found = observed or by_rooms
    if found is None:
        builder.issue(
            "drain_points",
            CalcUnresolvedKind.MISSING_INPUT,
            "Точки водоотведения",
            "таблицы приборов нет, правило по санузлам и кухням не применено",
            "таблица санитарных приборов П или утверждённое правило vk.k1.fixtures.by_rooms",
            structural=False,
        )
        return
    count = whole(found)
    builder.node(
        id="drain_points",
        semantic_type="DRAIN_POINTS",
        title="Точки водоотведения",
        provenance=_C,
        sources=[result_source(builder.context, found)],
        cardinality=CalcCardinality(min=count, max=count),
        support=f"Приборов {count}: "
        + ("по таблице приборов документации" if observed else "по утверждённому правилу"),
    )


def _vent(builder: Builder) -> None:
    if not builder.spec.drain_points:
        return
    item = builder.fact("vent")
    code = None if item is None else code_of(item)
    if item is None or code is None:
        return
    builder.node(
        id="vent",
        semantic_type="VENT_SYSTEM",
        title="Вентиляция стояков",
        provenance=_O,
        sources=[fact_source(item)],
        cardinality=CalcCardinality(min=1, max=1),
        support=f"Способ вентиляции стояков указан в документации: {code}",
    )


def _consumers(builder: Builder) -> None:
    named = [
        f"{title} {whole(found)}"
        for key, title in (
            ("demand.premises_total", "встроенных помещений"),
            ("demand.wet_rooms_total", "помещений с водой вне квартир"),
        )
        if (found := builder.result(key)) is not None and whole(found) > 0
    ]
    if named:
        builder.issue(
            "consumers.nonresidential",
            CalcUnresolvedKind.CHOICE,
            "Подключение потребителей вне квартир",
            "названо: " + ", ".join(named),
            "схема П: отдельная ветвь от магистрали или общие стояки — не выбирается",
            structural=False,
        )


def link(
    builder: Builder,
    source: CalcSystemNode | None,
    risers: CalcSystemNode | None,
    floors: CalcSystemNode | None,
) -> None:
    topology = builder.rule("topology")
    main = _main(builder, topology)
    if topology is None:
        builder.issue(
            "topology",
            CalcUnresolvedKind.MISSING_RULE,
            "Схема системы",
            "элементы системы известны, связи не утверждены",
            f"утверждённое правило схемы {builder.spec.topology_rule}",
            structural=True,
        )
    elif risers is not None and floors is not None:
        connections = _connections(builder, topology)
        _edges(builder, topology, source, main, connections)
    if risers is not None:
        _valves(builder)
    _drain_points(builder)
    _vent(builder)
    _consumers(builder)
    if builder.spec.source == "OUTLET":
        builder.issue(
            "outlets.route",
            CalcUnresolvedKind.ROUTE,
            "Длина выпусков",
            "выпуски названы" if source is not None else "выпуски не указаны",
            "трасса до колодцев — документ наружных сетей или обмер",
            structural=False,
        )
