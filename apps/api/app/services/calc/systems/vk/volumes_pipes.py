"""Трубопроводы ВК: стояки, этажные подключения, магистраль, выпуски и итог.

Длина неизвестна — «не определено», а не ноль и не «коридор × 0,8». Итог по трубам — сумма
определённых составляющих: если хотя бы одна неизвестна, итог — подтверждаемая часть (PARTIAL),
а неизвестное показано составляющей, не спрятано. Диаметр — только из документа.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.contracts.calc.enums import (
    CalcCompleteness,
    CalcQuantityCategory,
    CalcQuantityDerivation,
)
from app.contracts.calc.passport import CalcQuantityReserve
from app.contracts.calc.rules import TENDER_NOTICE
from app.services.calc.engine.numbers import ru_number
from app.services.calc.systems.vk.volume_base import (
    Range,
    VolumeContext,
    attr_range,
    plus,
    times,
)

_PIPE = CalcQuantityCategory.PIPE
_ZERO: Range = (Decimal(0), Decimal(0))


@dataclass
class Segment:
    """Участок трубы для итога и зависящих позиций: изоляции, креплений, фитингов трассы."""

    key: str
    title: str
    value: Range | None
    """Подтверждаемая длина: у частичного — только подтверждённая часть, без резерва."""
    complete: bool
    size: str | None
    blocked_by: list[str]
    count: Range | None = None
    per_instance: Range | None = None
    reserve: Range | None = None
    element_ids: list[str] = field(default_factory=list)


def _size(context: VolumeContext, element_id: str) -> str | None:
    diameter = context.attribute(element_id, "diameter")
    if diameter is None or diameter.value is None:
        return None
    return f"{ru_number(attr_range(diameter)[0])} мм"


def _reserve(context: VolumeContext, count: Range | None) -> tuple[Range | None, str | None]:
    record = context.reserve_per_riser()
    if record is None or count is None:
        return None, None
    delta = Decimal(record.delta)
    return times(count, (delta, delta)), record.rule_key


def risers(context: VolumeContext) -> Segment:
    count = context.count("risers")
    interfloor = context.attribute("risers", "interfloor_length")
    bottom = context.attribute("risers", "bottom_length")
    top = context.attribute("risers", "top_length")
    per_confirmed = (
        attr_range(interfloor)
        if interfloor is not None
        else None
        if context.value("structure.interfloor_length") is None
        else (context.value("structure.interfloor_length") or Decimal(0),) * 2
    )
    ends = None if bottom is None or top is None else plus(attr_range(bottom), attr_range(top))
    blocked: list[str] = []
    if count is None:
        blocked += context.issue_keys("risers.count", "floors") or ["risers.count"]
    if per_confirmed is None:
        blocked += context.step_block("structure_vertical")
    if ends is None:
        blocked += context.step_block("quantity_end_segments")
    per_riser = None if per_confirmed is None else plus(per_confirmed, ends or _ZERO)
    base = None if count is None or per_riser is None else times(count, per_riser)
    partial = base is not None and ends is None
    reserve, reserve_rule = _reserve(context, count)
    value = base if reserve is None or base is None else plus(base, reserve)
    size = _size(context, "risers")
    record = context.reserve_per_riser()
    context.add(
        "pipe.riser",
        _PIPE,
        "RISER_PIPE",
        "Трубы стояков",
        value=value,
        unit="m",
        derivation=CalcQuantityDerivation.CALCULATED,
        completeness=context.completeness(value, partial=partial),
        function="VERTICAL",
        size=size,
        material=context.inputs.material,
        attributes={"участок": "стояки", "диаметр": size or "не определён"},
        element_ids=["risers"],
        result_keys=[
            "structure.interfloor_length",
            *(["quantity.end_bottom", "quantity.end_top"] if ends is not None else []),
        ],
        rule_refs=context.element_rules("risers") + context.rule_ref("quantity.end_bottom"),
        blocked_by=blocked,
        components=[
            context.component(
                "interfloor",
                "Межэтажная часть на стояк",
                per_confirmed,
                "m",
                "от 1-го до верхнего этажа с квартирами — по отметкам или высотам",
            ),
            context.component(
                "ends",
                "Ниже 1-го и выше верхнего этажа на стояк",
                ends,
                "m",
                None if ends is not None else "не определено: нет утверждённого правила",
            ),
            context.component("count", "Стояков", count, "riser"),
        ],
        base=base if reserve is not None else None,
        reserve=None
        if reserve is None or record is None
        else CalcQuantityReserve(
            rule_key=record.rule_key or "",
            version=record.version or 0,
            amount=context.amount(reserve),
            unit="m",
            reason=record.reason,
            impact=record.impact,
        ),
        notice=TENDER_NOTICE if reserve is not None else None,
        assumptions=[] if reserve_rule is None else [f"{reserve_rule}: резерв длины на стояк"],
        explanation=(
            "Число стояков или межэтажная часть не определены"
            if value is None
            else ("Подтверждаемая часть: " if partial else "")
            + f"{context.text(count or _ZERO, 'ст.')} × {context.text(per_riser or _ZERO, 'м')}"
            + ("" if reserve is None else f" + резерв {context.text(reserve, 'м')}")
            + f" = {context.text(value, 'м')}"
        ),
    )
    return Segment(
        key="riser",
        title="Стояки",
        value=base,
        complete=base is not None and not partial,
        size=size,
        blocked_by=blocked,
        count=count,
        per_instance=per_riser,
        reserve=reserve,
        element_ids=["risers"],
    )


def connections(context: VolumeContext) -> Segment:
    count = context.count("floor_connections")
    length = context.attribute("floor_connections", "length")
    blocked: list[str] = []
    if count is None:
        blocked += context.structure_blockers() or ["topology"]
    elif length is None:
        blocked += context.issue_keys("connections.length") or context.step_block(
            "quantity_connection_length"
        )
    per = None if length is None else attr_range(length)
    value = None if count is None or per is None else times(count, per)
    context.add(
        "pipe.connection",
        _PIPE,
        "CONNECTION_PIPE",
        "Трубы этажных подключений",
        value=value,
        unit="m",
        derivation=CalcQuantityDerivation.CALCULATED,
        function="FLOOR_CONNECTION",
        material=context.inputs.material,
        attributes={"участок": "этажные подключения", "диаметр": "не определён"},
        element_ids=["floor_connections"],
        result_keys=["quantity.connection_length_min", "quantity.connection_length_max"],
        rule_refs=context.element_rules("floor_connections")
        + context.rule_ref("quantity.connection_length_min"),
        blocked_by=blocked,
        components=[
            context.component("count", "Подключений", count, "piece"),
            context.component("length", "Длина одного подключения", per, "m"),
        ],
        explanation="не определено"
        if value is None
        else f"{context.text(count or _ZERO, 'подкл.')} × {context.text(per or _ZERO, 'м')} = "
        f"{context.text(value, 'м')}",
    )
    return Segment(
        key="connection",
        title="Этажные подключения",
        value=value,
        complete=value is not None,
        size=None,
        blocked_by=blocked,
        count=count,
        per_instance=per,
        element_ids=["floor_connections"],
    )


def main(context: VolumeContext) -> Segment:
    length = context.attribute("main", "length")
    value = None if length is None else attr_range(length)
    size = _size(context, "main")
    blocked = [] if value is not None else context.issue_keys("main.route") or ["main.route"]
    context.add(
        "pipe.main",
        _PIPE,
        "MAIN_PIPE",
        "Трубы магистрали",
        value=value,
        unit="m",
        derivation=CalcQuantityDerivation.OBSERVED,
        function="MAIN",
        size=size,
        material=context.inputs.material,
        attributes={"участок": "магистраль", "диаметр": size or "не определён"},
        element_ids=["main"],
        blocked_by=blocked,
        explanation="трасса не определена — длина не выдумывается"
        if value is None
        else f"по документу или обмеру: {context.text(value, 'м')}",
    )
    return Segment(
        key="main",
        title="Магистраль",
        value=value,
        complete=value is not None,
        size=size,
        blocked_by=blocked,
        per_instance=value,
        count=None if value is None else (Decimal(1), Decimal(1)),
        element_ids=["main"],
    )


def outlets(context: VolumeContext) -> Segment | None:
    if context.spec.source != "OUTLET":
        return None
    blocked = context.issue_keys("outlets.route") or ["outlets.route"]
    context.add(
        "pipe.outlet",
        _PIPE,
        "OUTLET_PIPE",
        "Трубы выпусков",
        value=None,
        unit="m",
        derivation=CalcQuantityDerivation.NOT_DETERMINED,
        function="OUTLET",
        material=context.inputs.material,
        element_ids=["source"],
        blocked_by=blocked,
        explanation="длина выпусков до колодцев на стадии П не определяется",
    )
    return Segment("outlet", "Выпуски", None, False, None, blocked, element_ids=["source"])


def total(context: VolumeContext, segments: list[Segment]) -> None:
    known = [item for item in segments if item.value is not None]
    value: Range | None = None
    for item in known:
        value = item.value if value is None else plus(value, item.value or _ZERO)
    reserve = next((item.reserve for item in segments if item.reserve is not None), None)
    complete = all(item.complete for item in segments)
    completeness = (
        CalcCompleteness.BLOCKED
        if value is None
        else CalcCompleteness.PARTIAL
        if not complete
        else CalcCompleteness.UNRESOLVED_BREAKDOWN
        if any(item.size is None for item in segments)
        else context.completeness(value)
    )
    shown = value if reserve is None or value is None else plus(value, reserve)
    context.add(
        "pipe.total",
        _PIPE,
        "PIPE_TOTAL",
        "Трубопроводы системы — итог",
        value=shown,
        unit="m",
        derivation=CalcQuantityDerivation.AGGREGATE,
        completeness=completeness,
        function="TOTAL",
        material=context.inputs.material,
        attributes={
            "разбивка по диаметрам": "определена"
            if all(item.size for item in segments)
            else "не определена"
        },
        element_ids=[element for item in segments for element in item.element_ids],
        blocked_by=[key for item in segments for key in item.blocked_by],
        components=[
            context.component(
                item.key,
                item.title,
                item.value,
                "m",
                None if item.complete else "не определено полностью",
            )
            for item in segments
        ],
        base=value if reserve is not None else None,
        aggregate=True,
        explanation=(
            "Ни одна составляющая не определена"
            if value is None
            else (
                f"Подтверждаемая часть: {context.text(value, 'м')}. Полная длина пока не определена"
                if not complete
                else f"Сумма составляющих: {context.text(shown or value, 'м')}"
            )
        ),
    )
