"""Величина с размерностью для арифметики обработчиков.

Обработчик получает входы в канонических единицах своей размерности (м, кПа, м³/ч) или в
счётчиках (этажи, стояки — безразмерны) и считает величинами: произведение складывает векторы
размерностей, сумма требует одинаковых. Результат переводится в единицу выхода только если
размерность совпала: «м × кПа» длиной не станет.

Каталог единиц и векторы размерностей — общие с реестром правил (`units.py`,
`rules/dimensions.py`), второго каталога нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from app.contracts.calc.engine import CalcRoundingPolicy
from app.contracts.calc.units import CANONICAL_UNIT, CalcDimension, UnitError, unit_def
from app.services.calc.engine.numbers import ENGINE_CONTEXT, divide_rounded
from app.services.calc.rules.dimensions import describe, unit_vector

Vector = tuple[tuple[str, int], ...]


class UnitMismatchError(ValueError):
    """Размерности не сходятся — ошибка обработчика или привязки, а не данных."""


def is_working_unit(unit: str | None) -> bool:
    """Единица, в которой обработчик получает и отдаёт величины: каноническая или счётчик."""
    if unit is None:
        return True
    try:
        definition = unit_def(unit)
    except UnitError:
        return False
    if definition.dimension is CalcDimension.COUNT:
        return True
    return CANONICAL_UNIT.get(definition.dimension) == unit


def _vector(unit: str | None) -> Vector:
    return tuple(sorted(unit_vector(unit).items()))


def _combine(a: Vector, b: Vector, sign: int) -> Vector:
    merged = dict(a)
    for base, power in b:
        merged[base] = merged.get(base, 0) + sign * power
    return tuple(sorted((base, power) for base, power in merged.items() if power != 0))


@dataclass(frozen=True, slots=True)
class Quantity:
    value: Decimal
    dims: Vector

    @classmethod
    def of(cls, value: Decimal, unit: str | None) -> Quantity:
        if not is_working_unit(unit):
            raise UnitMismatchError(f"обработчик работает в канонических единицах, а не в «{unit}»")
        return cls(value, _vector(unit))

    def __mul__(self, other: Quantity) -> Quantity:
        with localcontext(ENGINE_CONTEXT):
            return Quantity(self.value * other.value, _combine(self.dims, other.dims, 1))

    def __truediv__(self, other: Quantity) -> Quantity:
        # Деление с бесконечной дробью — исключение контекста: округляют только явно.
        with localcontext(ENGINE_CONTEXT):
            return Quantity(self.value / other.value, _combine(self.dims, other.dims, -1))

    def divided_rounded(
        self, other: Quantity, policy: CalcRoundingPolicy
    ) -> tuple[Quantity, Decimal]:
        """Деление с явным округлением: результат и частное до округления — для записи в шаг."""
        quotient, rounded = divide_rounded(self.value, other.value, policy)
        return Quantity(rounded, _combine(self.dims, other.dims, -1)), quotient

    def __add__(self, other: Quantity) -> Quantity:
        self._same(other, "сложить")
        with localcontext(ENGINE_CONTEXT):
            return Quantity(self.value + other.value, self.dims)

    def __sub__(self, other: Quantity) -> Quantity:
        self._same(other, "вычесть")
        with localcontext(ENGINE_CONTEXT):
            return Quantity(self.value - other.value, self.dims)

    def _same(self, other: Quantity, action: str) -> None:
        if self.dims != other.dims:
            raise UnitMismatchError(
                f"нельзя {action} {describe(dict(self.dims))} и {describe(dict(other.dims))}"
            )

    def in_unit(self, unit: str | None) -> Decimal:
        """Значение в единице выхода — только при совпадении размерности."""
        if not is_working_unit(unit):
            raise UnitMismatchError(f"выход обработчика — в канонической единице, а не «{unit}»")
        if self.dims != _vector(unit):
            raise UnitMismatchError(
                f"получено {describe(dict(self.dims))}, а выход — {describe(dict(_vector(unit)))}"
            )
        return self.value
