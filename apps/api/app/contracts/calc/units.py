"""Каталог единиц расчётного контура.

Единица несёт размерность и масштаб к канонической единице своей размерности. Перевод —
только явной функцией `to_canonical`: неявное «число без единицы» старого портала давало
«компл.», умноженные на квадратные метры.

Счётчики типизированы: квартира, этаж, стояк — разные сущности одной размерности. Перевести
этажи в квартиры нельзя, и это ловит двойное умножение до того, как оно попадёт в количество.

Перевод только умножает на точные десятичные множители. Если перевод дал бы бесконечную
дробь (м³/ч в л/с), он отклоняется: округление добавило бы значению точность, которой у
источника нет.
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
    PRESSURE = "PRESSURE"
    FLOW_RATE = "FLOW_RATE"
    DAILY_VOLUME = "DAILY_VOLUME"
    TEMPERATURE = "TEMPERATURE"


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


def _unit(code: str, title: str, dimension: CalcDimension, factor: str) -> CalcUnitDef:
    return CalcUnitDef(code, title, dimension, Decimal(factor))


UNITS: Final[MappingProxyType[str, CalcUnitDef]] = MappingProxyType(
    {
        unit.code: unit
        for unit in (
            _length("m", "м", "1"),
            _length("cm", "см", "0.01"),
            _length("mm", "мм", "0.001"),
            CalcUnitDef("m2", "м²", CalcDimension.AREA, Decimal(1)),
            # Давление: канонически кПа — остальные переводятся в неё умножением.
            _unit("kPa", "кПа", CalcDimension.PRESSURE, "1"),
            _unit("MPa", "МПа", CalcDimension.PRESSURE, "1000"),
            _unit("bar", "бар", CalcDimension.PRESSURE, "100"),
            _unit("m_h2o", "м вод. ст.", CalcDimension.PRESSURE, "9.80665"),
            # Расход: канонически м³/ч; 1 л/с = 3,6 м³/ч точно.
            _unit("m3_h", "м³/ч", CalcDimension.FLOW_RATE, "1"),
            _unit("l_s", "л/с", CalcDimension.FLOW_RATE, "3.6"),
            # Суточный объём — не расход: м³/сут не переводятся в м³/ч делением на 24.
            _unit("m3_day", "м³/сут", CalcDimension.DAILY_VOLUME, "1"),
            _unit("l_day", "л/сут", CalcDimension.DAILY_VOLUME, "0.001"),
            _unit("degC", "°C", CalcDimension.TEMPERATURE, "1"),
            _count("floor", "эт."),
            _count("section", "секц."),
            _count("apartment", "кв."),
            _count("bathroom", "с/у"),
            _count("kitchen", "кух."),
            _count("riser", "ст."),
            _count("person", "чел."),
            _count("inlet", "ввод"),
            _count("outlet", "вып."),
            _count("zone", "зона"),
            _count("shaft", "шахта"),
            _count("premises", "встр. пом."),
            _count("room", "пом."),
            _count("meter", "узел учёта"),
            _count("fixture", "приб."),
        )
    }
)

CANONICAL_UNIT: Final[MappingProxyType[CalcDimension, str]] = MappingProxyType(
    {
        CalcDimension.LENGTH: "m",
        CalcDimension.AREA: "m2",
        CalcDimension.PRESSURE: "kPa",
        CalcDimension.FLOW_RATE: "m3_h",
        CalcDimension.DAILY_VOLUME: "m3_day",
        CalcDimension.TEMPERATURE: "degC",
    }
)

# Точность, которую держит контракт числа: девять знаков после запятой.
_EXACT: Final = Decimal("1e-9")


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
    result = value * unit_def(source).factor / unit_def(target).factor
    if result != result.quantize(_EXACT):
        raise UnitError(
            f"Перевод «{source}» в «{target}» дал бы бесконечную дробь — укажите значение в "
            f"«{unit_def(target).title}»"
        )
    return result
