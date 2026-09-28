"""Размерности правил: достаточно, чтобы «метры × давление» не прошли как длина.

Не символьная математика и не вычисление. Размерность единицы — вектор степеней базовых
величин из каталога единиц контура: длина, давление, расход, суточный объём, температура;
площадь — длина², счётчики безразмерны (метры × этажи — метры). Правило объявляет, из каких
множителей в каких степенях складывается каждый член выхода, и реестр сверяет векторы.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from app.contracts.calc.rules import CalcRuleDimensionCheck
from app.contracts.calc.units import CalcDimension, UnitError, unit_def

Vector = dict[str, int]

_BASE: Final[MappingProxyType[CalcDimension, Mapping[str, int]]] = MappingProxyType(
    {
        CalcDimension.LENGTH: {"L": 1},
        CalcDimension.AREA: {"L": 2},
        CalcDimension.COUNT: {},
        CalcDimension.PRESSURE: {"P": 1},
        CalcDimension.FLOW_RATE: {"Q": 1},
        CalcDimension.DAILY_VOLUME: {"V": 1},
        CalcDimension.TEMPERATURE: {"T": 1},
    }
)
_TITLES: Final = {
    "L": "длина",
    "P": "давление",
    "Q": "расход",
    "V": "суточный объём",
    "T": "температура",
}


class DimensionError(ValueError):
    """Размерность не сходится или единица неизвестна. Текст — для человека."""


def unit_vector(unit: str | None) -> Vector:
    """Вектор размерности единицы; пустая единица — безразмерно."""
    if unit is None:
        return {}
    try:
        return dict(_BASE[unit_def(unit).dimension])
    except UnitError as error:
        raise DimensionError(str(error)) from error


def describe(vector: Mapping[str, int]) -> str:
    parts = [
        _TITLES[base] if power == 1 else f"{_TITLES[base]}^{power}"
        for base, power in sorted(vector.items())
        if power
    ]
    return " × ".join(parts) or "безразмерно"


def _product(factors: list[tuple[Vector, int]]) -> Vector:
    total: Vector = {}
    for vector, exponent in factors:
        for base, power in vector.items():
            total[base] = total.get(base, 0) + power * exponent
    return {base: power for base, power in total.items() if power}


def check(check: CalcRuleDimensionCheck, units: Mapping[str, str | None]) -> list[str]:
    """Ошибки размерности одного выхода: каждый член суммы обязан иметь размерность выхода.

    `units` — единицы входов, параметров и выходов правила по их именам; отсутствие имени —
    ошибка, а не безразмерность.
    """
    if check.output not in units:
        return [f"проверка ссылается на неизвестный выход «{check.output}»"]
    problems: list[str] = []
    expected = unit_vector(units[check.output])
    for number, term in enumerate(check.terms, start=1):
        factors: list[tuple[Vector, int]] = []
        for factor in term.factors:
            if factor.name not in units:
                problems.append(f"член {number}: неизвестный множитель «{factor.name}»")
                break
            factors.append((unit_vector(units[factor.name]), factor.exponent))
        else:
            actual = _product(factors)
            if actual != expected:
                problems.append(
                    f"член {number} выхода «{check.output}»: {describe(actual)}, "
                    f"а выход — {describe(expected)}"
                )
    return problems
