"""Части графа ВК: основания элементов, атрибуты, чтение фактов и результатов. Чистые функции."""

from __future__ import annotations

from decimal import Decimal

from app.contracts.calc.engine import CalcResultRead, CalcSnapshotItem
from app.contracts.calc.enums import CalcQuantityBasis
from app.contracts.calc.synthesis import CalcElementSource, CalcQuantityAttr
from app.contracts.calc.values import (
    CalcBooleanValue,
    CalcCountValue,
    CalcEnumValue,
    CalcNumberValue,
    CalcTextValue,
)
from app.services.calc.engine.numbers import exact_text, parse_exact
from app.services.calc.synthesis.definitions import SynthesisContext


def fact_source(item: CalcSnapshotItem) -> CalcElementSource:
    value = item.value
    number: str | None = None
    unit: str | None = None
    if isinstance(value, CalcCountValue):
        number, unit = str(value.value), value.unit
    elif isinstance(value, CalcNumberValue):
        number, unit = value.value, value.unit
    return CalcElementSource(
        kind="FACT", key=item.fact_key, fact_id=item.fact_id, value=number, unit=unit
    )


def result_source(context: SynthesisContext, result: CalcResultRead) -> CalcElementSource:
    return CalcElementSource(
        kind="CALCULATION_RESULT",
        key=result.result_key,
        run_id=context.calculation_run_id,
        value=result.value,
        unit=result.unit,
    )


def count_of(item: CalcSnapshotItem) -> int | None:
    return item.value.value if isinstance(item.value, CalcCountValue) else None


def number_of(item: CalcSnapshotItem) -> Decimal | None:
    value = item.value
    if isinstance(value, CalcNumberValue):
        return parse_exact(value.value)
    if isinstance(value, CalcCountValue):
        return Decimal(value.value)
    return None


def code_of(item: CalcSnapshotItem) -> str | None:
    return item.value.value if isinstance(item.value, CalcEnumValue) else None


def flag_of(item: CalcSnapshotItem) -> bool | None:
    return item.value.value if isinstance(item.value, CalcBooleanValue) else None


def text_of(item: CalcSnapshotItem) -> str | None:
    return item.value.value if isinstance(item.value, CalcTextValue) else None


def whole(result: CalcResultRead) -> int:
    value = parse_exact(result.value)
    if value != value.to_integral_value():
        raise ValueError(f"результат {result.result_key} = {result.value} — не целое")
    return int(value)


def attr(
    name: str,
    result: CalcResultRead,
    basis: CalcQuantityBasis = CalcQuantityBasis.PER_INSTANCE,
    note: str | None = None,
) -> CalcQuantityAttr:
    return CalcQuantityAttr(name=name, value=result.value, unit=result.unit, basis=basis, note=note)


def attr_range(
    name: str, low: CalcResultRead, high: CalcResultRead, note: str | None = None
) -> CalcQuantityAttr:
    if low.value == high.value:
        return attr(name, low, note=note)
    return CalcQuantityAttr(
        name=name,
        low=low.value,
        high=high.value,
        unit=low.unit,
        basis=CalcQuantityBasis.PER_INSTANCE,
        note=note,
    )


def attr_value(
    name: str, value: Decimal, unit: str | None, basis: CalcQuantityBasis, note: str | None = None
) -> CalcQuantityAttr:
    return CalcQuantityAttr(name=name, value=exact_text(value), unit=unit, basis=basis, note=note)


def decimal_of(value: Decimal) -> int:
    """Целое из выхода правила: «1» подключение, «2» крана."""
    if value != value.to_integral_value():
        raise ValueError(f"{value} — не целое")
    return int(value)
