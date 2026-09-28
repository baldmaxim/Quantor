"""Штучные позиции и позиции, зависящие от длин: по топологии графа, по узлам, по правилам.

- Топология: ответвление на каждое присоединение подключения к стояку, оконечный элемент на
  каждый стояк, проходка на каждое пересечённое перекрытие, переход — только если диаметры
  участков из документа различаются. Тип фитинга по материалу не выдумывается.
- Резервный метод фитингов трассы — только утверждённым правилом, помечен FALLBACK.
- Арматура — по узлам графа, которые синтезатор создал утверждённым правилом; «N кранов на
  этаж» не применяется.
- Изоляция, крепления, гильзы и огнезащита — только утверждённым правилом; без него позиция
  «не определено».
"""

from __future__ import annotations

from decimal import Decimal

from app.contracts.calc.enums import CalcQuantityCategory, CalcQuantityDerivation
from app.services.calc.systems.vk.volume_base import (
    VolumeContext,
    attr_range,
    times,
)
from app.services.calc.systems.vk.volumes_pipes import Segment

_C = CalcQuantityCategory
_D = CalcQuantityDerivation
_NOT_TYPED = "тип по материалу не определён"


def blocked_row(
    context: VolumeContext,
    suffix: str,
    category: CalcQuantityCategory,
    item_type: str,
    title: str,
    unit: str,
    blocked_by: list[str],
    why: str,
) -> None:
    context.add(
        suffix,
        category,
        item_type,
        title,
        value=None,
        unit=unit,
        derivation=_D.NOT_DETERMINED,
        blocked_by=blocked_by,
        explanation=why,
    )


def topology_fittings(context: VolumeContext, riser: Segment, connection: Segment) -> None:
    branches = context.count("riser_branches")
    if branches is None:
        blocked_row(
            context,
            "fitting.branch",
            _C.FITTING,
            "BRANCH_TEE",
            "Ответвления на присоединении подключений",
            "piece",
            connection.blocked_by or ["topology"],
            "схема подключений не определена",
        )
    else:
        context.add(
            "fitting.branch",
            _C.FITTING,
            "BRANCH_TEE",
            "Ответвления (тройники) на присоединении подключений",
            value=branches,
            unit="piece",
            derivation=_D.TOPOLOGY,
            attributes={"тип": _NOT_TYPED, "основание": "узел присоединения в графе"},
            element_ids=["riser_branches"],
            rule_refs=context.element_rules("floor_connections"),
            explanation=f"по одному на каждое присоединение: {context.text(branches, 'шт.')}",
        )
    if riser.count is None:
        blocked_row(
            context,
            "fitting.riser_end",
            _C.FITTING,
            "RISER_TERMINATION",
            "Оконечные элементы стояков",
            "piece",
            riser.blocked_by,
            "число стояков не определено",
        )
    else:
        context.add(
            "fitting.riser_end",
            _C.FITTING,
            "RISER_TERMINATION",
            "Оконечные элементы стояков",
            value=riser.count,
            unit="piece",
            derivation=_D.TOPOLOGY,
            attributes={"тип": "зависит от системы и материала — не определён"},
            element_ids=["risers"],
            explanation=f"по одному на верхний конец стояка: {context.text(riser.count, 'шт.')}",
        )
    main_size = context.attribute("main", "diameter")
    riser_size = context.attribute("risers", "diameter")
    if riser.count is None or main_size is None or riser_size is None:
        blocked_row(
            context,
            "fitting.transition",
            _C.FITTING,
            "TRANSITION",
            "Переходы диаметров",
            "piece",
            ["fact:system.main_diameter", "fact:system.riser_diameter"],
            "диаметры магистрали и стояков по документу не известны — переходы не выводятся",
        )
    else:
        same = attr_range(main_size) == attr_range(riser_size)
        zero = (Decimal(0), Decimal(0))
        context.add(
            "fitting.transition",
            _C.FITTING,
            "TRANSITION",
            "Переходы магистраль — стояк",
            value=zero if same else riser.count,
            unit="piece",
            derivation=_D.TOPOLOGY,
            attributes={"тип": _NOT_TYPED},
            element_ids=["main", "risers"],
            explanation="диаметры одинаковы — переходов нет"
            if same
            else f"диаметры различаются: по одному на стояк, {context.text(riser.count, 'шт.')}",
        )


def valves(context: VolumeContext) -> None:
    for node_id, suffix, item_type, title, rule_key in (
        (
            "riser_valves",
            "valve.riser_shutoff",
            "SHUTOFF_VALVE",
            "Запорная арматура стояков",
            context.spec.riser_valves_rule,
        ),
        (
            "balancing_valves",
            "valve.balancing",
            "BALANCING_VALVE",
            "Балансировочная арматура",
            context.spec.balancing_rule,
        ),
    ):
        if rule_key is None:
            continue
        count = context.count(node_id)
        if count is None:
            blocked_row(
                context,
                suffix,
                _C.VALVE,
                item_type,
                title,
                "piece",
                context.issue_keys(f"valves.{node_id}", "risers.count") or [f"valves.{node_id}"],
                "узлов арматуры в графе нет",
            )
            continue
        context.add(
            suffix,
            _C.VALVE,
            item_type,
            title,
            value=count,
            unit="piece",
            derivation=_D.TOPOLOGY,
            attributes={"тип": "по правилу узла; модель не определяется"},
            element_ids=[node_id],
            rule_refs=context.element_rules(node_id),
            explanation=f"по узлам графа: {context.text(count, 'шт.')}",
        )


def penetrations(context: VolumeContext, riser: Segment) -> None:
    crossings = context.attribute("risers", "slab_crossings")
    value = (
        None
        if riser.count is None or crossings is None
        else times(riser.count, attr_range(crossings))
    )
    if value is None:
        blocked_row(
            context,
            "penetration.slab",
            _C.SLEEVE,
            "PENETRATION",
            "Проходки через перекрытия",
            "piece",
            riser.blocked_by,
            "число стояков или перекрытий не определено",
        )
    else:
        context.add(
            "penetration.slab",
            _C.SLEEVE,
            "PENETRATION",
            "Проходки стояков через перекрытия",
            value=value,
            unit="piece",
            derivation=_D.TOPOLOGY,
            attributes={"перекрытия": "между 1-м и верхним этажом с квартирами"},
            element_ids=["risers"],
            result_keys=["structure.slab_crossings"],
            explanation=f"{context.text(riser.count or (Decimal(0),) * 2, 'ст.')} × "
            f"{context.text(attr_range(crossings) if crossings else (Decimal(0),) * 2, 'перекр.')} "
            f"= {context.text(value, 'шт.')}",
        )
    for flag, suffix, item_type, title in (
        ("quantity.sleeve", "sleeve.slab", "SLEEVE", "Гильзы в перекрытиях"),
        ("quantity.firestop", "firestop.slab", "FIRESTOP", "Огнезащита проходок"),
    ):
        needed = context.value(flag)
        if needed is None:
            blocked_row(
                context,
                suffix,
                _C.SLEEVE,
                item_type,
                title,
                "piece",
                context.step_block("quantity_penetrations"),
                "конструкция проходки не определена: нет документа или правила",
            )
        elif needed == 1 and value is not None:
            context.add(
                suffix,
                _C.SLEEVE,
                item_type,
                title,
                value=value,
                unit="piece",
                derivation=_D.RULE,
                result_keys=[flag],
                rule_refs=context.rule_ref(flag),
                element_ids=["risers"],
                explanation=f"на каждую проходку по правилу: {context.text(value, 'шт.')}",
            )
        elif needed == 1:
            blocked_row(
                context,
                suffix,
                _C.SLEEVE,
                item_type,
                title,
                "piece",
                riser.blocked_by,
                "проходки не определены",
            )


def equipment_and_connections(context: VolumeContext, connection: Segment) -> None:
    if context.spec.source == "INLET":
        pump = context.node("pump_station")
        if pump is not None:
            context.add(
                "equipment.pump_station",
                _C.EQUIPMENT,
                "PUMP_STATION",
                "Насосная установка",
                value=(Decimal(1), Decimal(1)),
                unit="set",
                derivation=_D.OBSERVED,
                attributes={
                    "производитель": "не определён",
                    "модель": "не определена",
                    "производительность": "не определена",
                },
                element_ids=["pump_station"],
                explanation="предусмотрена документацией",
            )
        elif context.issue_keys("pump_station"):
            blocked_row(
                context,
                "equipment.pump_station",
                _C.EQUIPMENT,
                "PUMP_STATION",
                "Насосная установка",
                "set",
                ["pump_station"],
                "в документации не сказано, нужна ли",
            )
        meters = context.count("meters")
        if meters is not None:
            context.add(
                "equipment.meter_units",
                _C.EQUIPMENT,
                "METER_UNIT",
                "Узлы учёта воды",
                value=meters,
                unit="piece",
                derivation=_D.OBSERVED,
                attributes={"модель": "не определена"},
                element_ids=["meters"],
                explanation=f"по документации: {context.text(meters, 'шт.')}",
            )
    if connection.count is None:
        blocked_row(
            context,
            "connection.floor",
            _C.CONNECTION,
            "FLOOR_CONNECTION",
            "Этажные подключения",
            "piece",
            connection.blocked_by,
            "схема не определена",
        )
    else:
        context.add(
            "connection.floor",
            _C.CONNECTION,
            "FLOOR_CONNECTION",
            "Этажные подключения",
            value=connection.count,
            unit="piece",
            derivation=_D.TOPOLOGY,
            element_ids=["floor_connections"],
            rule_refs=context.element_rules("floor_connections"),
            explanation=f"стояки × этажи с квартирами × подключений на стояк и этаж = "
            f"{context.text(connection.count, 'шт.')}",
        )
    if context.spec.drain_points:
        points = context.count("drain_points")
        if points is None:
            blocked_row(
                context,
                "connection.drain_point",
                _C.CONNECTION,
                "DRAIN_POINT",
                "Точки водоотведения (приборы)",
                "piece",
                context.issue_keys("drain_points") or ["drain_points"],
                "таблицы приборов нет, правило не применено",
            )
        else:
            context.add(
                "connection.drain_point",
                _C.CONNECTION,
                "DRAIN_POINT",
                "Точки водоотведения (приборы)",
                value=points,
                unit="piece",
                derivation=_D.CALCULATED,
                element_ids=["drain_points"],
                result_keys=["demand.fixtures_observed", "demand.fixtures_by_rooms"],
                rule_refs=context.rule_ref("demand.fixtures_by_rooms"),
                explanation=f"приборов: {context.text(points, 'шт.')}",
            )
