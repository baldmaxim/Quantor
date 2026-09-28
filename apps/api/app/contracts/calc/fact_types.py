"""Реестр типов фактов.

Живёт в коде, как реестр флагов: тип факта — свойство продукта, а не настройка. Свободная
строка «что угодно с числом» вернула бы хаос старого портала, где «высота» означала то
высоту стояка, то высоту здания.

Тип задаёт: вид значения, каноническую единицу, какие поля места обязательны и допустимы,
допуск сравнения (в его пределах два источника согласны, за ним — конфликт) и можно ли
хранить такой факт из ВОР Заказчика. Последнее — белый список качественных фактов:
количества и решения ВОР в реестр не принимаются вовсе (ADR-0030).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from app.contracts.calc.enums import CalcValueKind
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.units import UnitError, to_canonical, unit_def
from app.contracts.calc.values import (
    CalcBooleanValue,
    CalcCountValue,
    CalcEnumValue,
    CalcFactValue,
    CalcNumberValue,
    CalcRangeValue,
    CalcTextValue,
    clean_text,
    decimal_text,
    parse_decimal,
)

FACT_TYPES_VERSION: Final = "calc.fact_types.v1"

_BUILDING = frozenset({"building"})
_FLOOR = frozenset({"building", "floor"})
_FLOOR_ALLOWED = frozenset({"building", "section", "floor"})
_ROOM = frozenset({"building", "room"})
_ROOM_ALLOWED = frozenset({"building", "section", "floor", "room"})
_SYSTEM = frozenset({"discipline", "system_code"})
_SYSTEM_ALLOWED = frozenset({"building", "section", "discipline", "system_code"})


@dataclass(frozen=True, slots=True)
class CalcEnumOptionDef:
    value: str
    title: str


@dataclass(frozen=True, slots=True)
class CalcFactTypeDef:
    key: str
    title: str
    description: str
    value_kind: CalcValueKind
    required_subject: frozenset[str]
    allowed_subject: frozenset[str]
    unit: str | None = None
    """Каноническая единица для чисел, счётчиков и диапазонов."""
    options: tuple[CalcEnumOptionDef, ...] = field(default=())
    abs_tolerance: Decimal = Decimal(0)
    rel_tolerance: Decimal = Decimal(0)
    min_value: Decimal | None = Decimal(0)
    customer_vor_admissible: bool = False
    """Качественный факт, который можно хранить из ВОР Заказчика — для сверки, не для расчёта."""


def _count(key: str, title: str, description: str, unit: str, subject: str) -> CalcFactTypeDef:
    required, allowed = _SUBJECTS[subject]
    return CalcFactTypeDef(
        key, title, description, CalcValueKind.COUNT, required, allowed, unit=unit
    )


_SUBJECTS: Final[dict[str, tuple[frozenset[str], frozenset[str]]]] = {
    "building": (_BUILDING, _BUILDING),
    "floor": (_FLOOR, _FLOOR_ALLOWED),
    "room": (_ROOM, _ROOM_ALLOWED),
    "system": (_SYSTEM, _SYSTEM_ALLOWED),
}

_FLOOR_FUNCTIONS = (
    CalcEnumOptionDef("RESIDENTIAL", "жилой"),
    CalcEnumOptionDef("COMMERCIAL", "коммерческий"),
    CalcEnumOptionDef("PUBLIC", "общественный"),
    CalcEnumOptionDef("TECHNICAL", "технический"),
    CalcEnumOptionDef("PARKING", "паркинг"),
    CalcEnumOptionDef("MIXED", "смешанный"),
)

REGISTRY: Final[MappingProxyType[str, CalcFactTypeDef]] = MappingProxyType(
    {
        definition.key: definition
        for definition in (
            _count(
                "building.floors_above_ground",
                "Этажей надземной части",
                "Число надземных этажей корпуса, включая технические.",
                "floor",
                "building",
            ),
            _count(
                "building.floors_below_ground",
                "Этажей подземной части",
                "Число подземных этажей корпуса.",
                "floor",
                "building",
            ),
            _count(
                "building.sections_count",
                "Секций в корпусе",
                "Число секций корпуса.",
                "section",
                "building",
            ),
            _count(
                "building.apartments_total",
                "Квартир в корпусе",
                "Итог квартир по корпусу, как его сообщает источник.",
                "apartment",
                "building",
            ),
            CalcFactTypeDef(
                "building.height",
                "Высота здания",
                "Высота корпуса по источнику. Что именно измерено — до кровли, парапета или "
                "верхнего перекрытия — записывается в свидетельстве: смысл «высоты» в "
                "квартирографиях не определён.",
                CalcValueKind.NUMBER,
                _BUILDING,
                _BUILDING,
                unit="m",
                abs_tolerance=Decimal("0.01"),
            ),
            _count(
                "floor.apartments_count",
                "Квартир на этаже",
                "Число квартир на этаже или на каждом этаже группы («2..24»), включая 1-й этаж.",
                "apartment",
                "floor",
            ),
            _count(
                "floor.bathrooms_count",
                "Санузлов на этаже",
                "Число санузлов на этаже.",
                "bathroom",
                "floor",
            ),
            _count(
                "floor.kitchens_count",
                "Кухонь на этаже",
                "Число кухонь на этаже.",
                "kitchen",
                "floor",
            ),
            CalcFactTypeDef(
                "floor.height",
                "Высота этажа",
                "Высота этажа от пола до пола.",
                CalcValueKind.NUMBER,
                _FLOOR,
                _FLOOR_ALLOWED,
                unit="m",
                abs_tolerance=Decimal("0.01"),
            ),
            CalcFactTypeDef(
                "floor.function",
                "Назначение этажа",
                "Жилой, коммерческий, технический и т. д.",
                CalcValueKind.ENUM,
                _FLOOR,
                _FLOOR_ALLOWED,
                options=_FLOOR_FUNCTIONS,
                min_value=None,
            ),
            CalcFactTypeDef(
                "floor.corridor_length",
                "Длина коридора МОП",
                "Длина поэтажного коридора мест общего пользования.",
                CalcValueKind.NUMBER,
                _FLOOR,
                _FLOOR_ALLOWED,
                unit="m",
                abs_tolerance=Decimal("0.05"),
                rel_tolerance=Decimal("0.01"),
            ),
            CalcFactTypeDef(
                "room.area",
                "Площадь помещения",
                "Площадь помещения или квартиры.",
                CalcValueKind.NUMBER,
                _ROOM,
                _ROOM_ALLOWED,
                unit="m2",
                abs_tolerance=Decimal("0.1"),
                rel_tolerance=Decimal("0.01"),
            ),
            CalcFactTypeDef(
                "room.purpose",
                "Назначение помещения",
                "Назначение по экспликации: «санузел», «кухня-столовая», «ПУИ».",
                CalcValueKind.TEXT,
                _ROOM,
                _ROOM_ALLOWED,
                min_value=None,
            ),
            CalcFactTypeDef(
                "system.present",
                "Система предусмотрена",
                "Есть ли система в проекте.",
                CalcValueKind.BOOLEAN,
                _SYSTEM,
                _SYSTEM_ALLOWED,
                min_value=None,
                customer_vor_admissible=True,
            ),
            CalcFactTypeDef(
                "system.pipe_material",
                "Материал трубопроводов",
                "Материал трубопроводов системы: «сталь оцинкованная», «PE-X», «PP-R».",
                CalcValueKind.TEXT,
                _SYSTEM,
                _SYSTEM_ALLOWED,
                min_value=None,
                customer_vor_admissible=True,
            ),
            CalcFactTypeDef(
                "system.equipment_type",
                "Тип оборудования",
                "Тип основного оборудования системы.",
                CalcValueKind.TEXT,
                _SYSTEM,
                _SYSTEM_ALLOWED,
                min_value=None,
                customer_vor_admissible=True,
            ),
            _count(
                "system.risers_count",
                "Стояков в системе",
                "Число стояков системы, как его сообщает источник.",
                "riser",
                "system",
            ),
        )
    }
)


class FactValueError(ValueError):
    """Значение не подходит типу факта. Текст — для пользователя."""


class FactUnitError(FactValueError):
    """Единица не совместима с единицей типа факта."""


def fact_type_def(key: str) -> CalcFactTypeDef | None:
    return REGISTRY.get(key)


def check_subject(definition: CalcFactTypeDef, subject: CalcFactSubject) -> str | None:
    """Пусто — место подходит; иначе — объяснение, что не так."""
    present = subject.present_fields()
    missing = definition.required_subject - present
    if missing:
        return "не указано: " + ", ".join(sorted(missing))
    extra = present - definition.allowed_subject
    if extra:
        return "лишнее для этого типа: " + ", ".join(sorted(extra))
    return None


def _canonical_number(definition: CalcFactTypeDef, text: str, unit: str) -> str:
    target = definition.unit
    if target is None:
        raise FactValueError("у типа факта нет единицы")
    try:
        value = to_canonical(parse_decimal(text), unit, target)
    except UnitError as error:
        raise FactUnitError(str(error)) from error
    if definition.min_value is not None and value < definition.min_value:
        raise FactValueError("значение меньше допустимого")
    return decimal_text(value)


def canonicalize(definition: CalcFactTypeDef, value: CalcFactValue) -> CalcFactValue:
    """Каноническая форма значения для этого типа факта. Несовместимое — ошибка, а не 0."""
    if value.kind != definition.value_kind.value:
        raise FactValueError(
            f"тип «{definition.key}» ожидает значение вида {definition.value_kind.value}"
        )
    match value:
        case CalcNumberValue():
            return CalcNumberValue(
                value=_canonical_number(definition, value.value, value.unit),
                unit=definition.unit or value.unit,
            )
        case CalcCountValue():
            unit = value.unit or definition.unit
            if unit != definition.unit:
                try:
                    unit_def(unit or "")
                except UnitError as error:
                    raise FactUnitError(str(error)) from error
                raise FactUnitError(
                    f"тип «{definition.key}» считает «{definition.unit}», а не «{unit}»"
                )
            return CalcCountValue(value=value.value, unit=definition.unit)
        case CalcRangeValue():
            low = (
                None if value.low is None else _canonical_number(definition, value.low, value.unit)
            )
            high = (
                None
                if value.high is None
                else _canonical_number(definition, value.high, value.unit)
            )
            return CalcRangeValue(low=low, high=high, unit=definition.unit or value.unit)
        case CalcEnumValue():
            allowed = {option.value for option in definition.options}
            if value.value not in allowed:
                raise FactValueError("значение не из списка: " + ", ".join(sorted(allowed)))
            return value
        case CalcTextValue():
            text = clean_text(value.value)
            if not text:
                raise FactValueError("текст не может быть пустым")
            return CalcTextValue(value=text)
        case CalcBooleanValue():
            return value


def canonical_number(value: CalcFactValue) -> Decimal | None:
    """Число для хранения в числовой колонке: у чисел и счётчиков."""
    match value:
        case CalcNumberValue():
            return parse_decimal(value.value)
        case CalcCountValue():
            return Decimal(value.value)
        case _:
            return None


def _close(definition: CalcFactTypeDef, a: Decimal, b: Decimal) -> bool:
    tolerance = max(definition.abs_tolerance, definition.rel_tolerance * max(abs(a), abs(b)))
    return abs(a - b) <= tolerance


def _optional_close(definition: CalcFactTypeDef, a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return _close(definition, parse_decimal(a), parse_decimal(b))


def values_agree(definition: CalcFactTypeDef, a: CalcFactValue, b: CalcFactValue) -> bool:
    """Согласны ли два канонических значения в пределах допуска типа."""
    match a, b:
        case CalcNumberValue(), CalcNumberValue():
            return _close(definition, parse_decimal(a.value), parse_decimal(b.value))
        case CalcCountValue(), CalcCountValue():
            return a.value == b.value
        case CalcRangeValue(), CalcRangeValue():
            return _optional_close(definition, a.low, b.low) and _optional_close(
                definition, a.high, b.high
            )
        case CalcTextValue(), CalcTextValue():
            return a.value.casefold() == b.value.casefold()
        case _:
            return a == b


def fact_key(fact_type: str, subject: CalcFactSubject) -> str:
    return f"{fact_type}@{subject.key()}"
