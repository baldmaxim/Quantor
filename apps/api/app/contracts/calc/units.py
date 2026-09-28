"""Каталог единиц расчётного контура.

Единица несёт размерность и масштаб к канонической единице своей размерности. Перевод —
только явной функцией `to_canonical`: неявное «число без единицы» старого портала давало
«компл.», умноженные на квадратные метры.

Счётчики типизированы: квартира, этаж, стояк — разные сущности одной размерности. Перевести
этажи в квартиры нельзя, и это ловит двойное умножение до того, как оно попадёт в количество.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class CalcDimension(StrEnum):
    LENGTH = "LENGTH"
    AREA = "AREA"
    COUNT = "COUNT"


@dataclass(frozen=True, slots=True)
class CalcUnitDef:
    code: str
    title: str
    dimension: CalcDimension
    factor: Decimal
    """Множитель к канонической единице размерности: мм → м это 0,001."""
    counted: str | None = None
    """Что считается — только у счётчиков. Счётчики разных сущностей не переводятся друг в друга."""


def _length(code: str, title: str, factor: str) -> CalcUnitDef:
    return CalcUnitDef(code, title, CalcDimension.LENGTH, Decimal(factor))


def _count(code: str, title: str) -> CalcUnitDef:
    return CalcUnitDef(code, title, CalcDimension.COUNT, Decimal(1), counted=code)


UNITS: Final[MappingProxyType[str, CalcUnitDef]] = MappingProxyType(
    {
        unit.code: unit
        for unit in (
            _length("m", "м", "1"),
            _length("cm", "см", "0.01"),
            _length("mm", "мм", "0.001"),
            CalcUnitDef("m2", "м²", CalcDimension.AREA, Decimal(1)),
            _count("floor", "эт."),
            _count("section", "секц."),
            _count("apartment", "кв."),
            _count("bathroom", "с/у"),
            _count("kitchen", "кух."),
            _count("riser", "ст."),
        )
    }
)

CANONICAL_UNIT: Final[MappingProxyType[CalcDimension, str]] = MappingProxyType(
    {CalcDimension.LENGTH: "m", CalcDimension.AREA: "m2"}
)


class UnitError(ValueError):
    """Единица неизвестна или не совместима с требуемой."""


def unit_def(code: str) -> CalcUnitDef:
    try:
        return UNITS[code]
    except KeyError as error:
        raise UnitError(f"Неизвестная единица «{code}»") from error


def compatible(source: str, target: str) -> bool:
    """Можно ли перевести значение из одной единицы в другую."""
    a, b = unit_def(source), unit_def(target)
    if a.dimension is not b.dimension:
        return False
    return a.dimension is not CalcDimension.COUNT or a.counted == b.counted


def to_canonical(value: Decimal, source: str, target: str) -> Decimal:
    """Переводит значение из единицы `source` в единицу `target` той же размерности."""
    if not compatible(source, target):
        raise UnitError(f"Единицу «{source}» нельзя перевести в «{target}»")
    return value * unit_def(source).factor / unit_def(target).factor
