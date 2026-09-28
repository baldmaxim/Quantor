"""Позиции по утверждённым правилам слоя D: изоляция, крепления, резервный метод фитингов.

Без утверждённого правила позиция «не определено»: изоляция не равна всей длине трубы, шаг
креплений не берётся из старого портала, коэффициент фитингов на метр — только резервный метод,
помеченный FALLBACK и не выдающий себя за топологию.
"""

from __future__ import annotations

from decimal import Decimal

from app.contracts.calc.enums import CalcQuantityCategory, CalcQuantityDerivation
from app.services.calc.engine.numbers import ru_number
from app.services.calc.systems.vk.volume_base import (
    Range,
    VolumeContext,
    ceil_div,
    plus,
    times,
)
from app.services.calc.systems.vk.volumes_items import blocked_row
from app.services.calc.systems.vk.volumes_pipes import Segment

_C = CalcQuantityCategory
_D = CalcQuantityDerivation
_NOT_TYPED = "тип по материалу не определён"
_FLAG_RESULTS = {
    "riser": "quantity.insulate_risers",
    "connection": "quantity.insulate_connections",
    "main": "quantity.insulate_mains",
}


def fallback_fittings(context: VolumeContext, known_length: Range | None, complete: bool) -> None:
    rate = context.value("quantity.fittings_per_meter")
    if rate is None:
        blocked_row(
            context,
            "fitting.route_fallback",
            _C.FITTING,
            "ROUTE_FITTINGS",
            "Фитинги трассы (отводы, муфты)",
            "piece",
            context.step_block("quantity_fittings"),
            "топологией не выводятся; резервного метода не утверждено",
        )
        return
    if known_length is None:
        blocked_row(
            context,
            "fitting.route_fallback",
            _C.FITTING,
            "ROUTE_FITTINGS",
            "Фитинги трассы (отводы, муфты)",
            "piece",
            ["pipe.total"],
            "длина трубопроводов не определена",
        )
        return
    value = ceil_div(times(known_length, (rate, rate)), Decimal(1))
    context.add(
        "fitting.route_fallback",
        _C.FITTING,
        "ROUTE_FITTINGS",
        "Фитинги трассы (отводы, муфты)",
        value=value,
        unit="piece",
        derivation=_D.FALLBACK,
        completeness=context.completeness(value, partial=not complete),
        attributes={"метод": "резервный — на метр трассы, не топология", "тип": _NOT_TYPED},
        result_keys=["quantity.fittings_per_meter"],
        rule_refs=context.rule_ref("quantity.fittings_per_meter"),
        blocked_by=[] if complete else ["pipe.total"],
        notice="Резервный метод по утверждённому правилу — не выведено из топологии",
        explanation=f"{context.text(known_length, 'м')} × {ru_number(rate)} на метр, округление "
        f"вверх = {context.text(value, 'шт.')}",
    )


def insulation(context: VolumeContext, segments: dict[str, Segment]) -> None:
    flags = {key: context.value(result) for key, result in _FLAG_RESULTS.items()}
    if all(value is None for value in flags.values()):
        blocked_row(
            context,
            "insulation.pipes",
            _C.INSULATION,
            "PIPE_INSULATION",
            "Изоляция трубопроводов",
            "m",
            context.step_block("quantity_insulation"),
            "какие участки изолируются — нет документа или утверждённого правила; "
            "изоляция не равна всей длине трубы",
        )
        return
    for key, flag in flags.items():
        segment = segments.get(key)
        if flag != 1 or segment is None:
            continue
        context.add(
            f"insulation.{key}",
            _C.INSULATION,
            "PIPE_INSULATION",
            f"Изоляция: {segment.title.lower()}",
            value=segment.value,
            unit="m",
            derivation=_D.RULE,
            completeness=context.completeness(segment.value, partial=not segment.complete),
            size=segment.size,
            element_ids=segment.element_ids,
            result_keys=[_FLAG_RESULTS[key]],
            rule_refs=context.rule_ref(_FLAG_RESULTS[key]),
            blocked_by=segment.blocked_by,
            explanation="длина участка по правилу изоляции"
            + ("" if segment.value is None else f": {context.text(segment.value, 'м')}"),
        )


def supports(context: VolumeContext, riser: Segment, horizontal: list[Segment]) -> None:
    vertical_step = context.value("quantity.support_vertical")
    horizontal_step = context.value("quantity.support_horizontal")
    if vertical_step is None or horizontal_step is None:
        for suffix, title in (
            ("support.riser", "Крепления стояков"),
            ("support.horizontal", "Крепления горизонтальных участков"),
        ):
            blocked_row(
                context,
                suffix,
                _C.SUPPORT,
                "PIPE_SUPPORT",
                title,
                "piece",
                context.step_block("quantity_supports"),
                "шаг креплений не утверждён — крепления не генерируются",
            )
        return
    refs = context.rule_ref("quantity.support_vertical")
    if riser.count is None or riser.per_instance is None:
        blocked_row(
            context,
            "support.riser",
            _C.SUPPORT,
            "PIPE_SUPPORT",
            "Крепления стояков",
            "piece",
            riser.blocked_by,
            "длина стояков не определена",
        )
    else:
        value = times(riser.count, ceil_div(riser.per_instance, vertical_step))
        context.add(
            "support.riser",
            _C.SUPPORT,
            "PIPE_SUPPORT",
            "Крепления стояков",
            value=value,
            unit="piece",
            derivation=_D.RULE,
            completeness=context.completeness(value, partial=not riser.complete),
            element_ids=["risers"],
            result_keys=["quantity.support_vertical"],
            rule_refs=refs,
            blocked_by=riser.blocked_by,
            explanation=f"⌈{context.text(riser.per_instance, 'м')} / {ru_number(vertical_step)} м⌉ "
            f"× {context.text(riser.count, 'ст.')} = {context.text(value, 'шт.')}",
        )
    total: Range | None = None
    blocked: list[str] = []
    for segment in horizontal:
        if segment.count is None or segment.per_instance is None:
            blocked += segment.blocked_by
            continue
        part = times(segment.count, ceil_div(segment.per_instance, horizontal_step))
        total = part if total is None else plus(total, part)
    context.add(
        "support.horizontal",
        _C.SUPPORT,
        "PIPE_SUPPORT",
        "Крепления горизонтальных участков",
        value=total,
        unit="piece",
        derivation=_D.RULE,
        completeness=context.completeness(total, partial=bool(blocked)),
        element_ids=[item.element_ids[0] for item in horizontal if item.element_ids],
        result_keys=["quantity.support_horizontal"],
        rule_refs=refs,
        blocked_by=blocked,
        explanation="не определено"
        if total is None
        else f"по шагу {ru_number(horizontal_step)} м: {context.text(total, 'шт.')}"
        + ("; часть участков не определена" if blocked else ""),
    )
