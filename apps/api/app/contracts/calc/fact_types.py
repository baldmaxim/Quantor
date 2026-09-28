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

FACT_TYPES_VERSION: Final = "calc.fact_types.v2"

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
    qualifier_options: tuple[CalcEnumOptionDef, ...] = field(default=())
    """Перечень квалификаторов: если он есть, квалификатор обязателен и берётся из него."""


def _count(
    key: str,
    title: str,
    description: str,
    unit: str,
    subject: str,
    qualifiers: tuple[CalcEnumOptionDef, ...] = (),
) -> CalcFactTypeDef:
    required, allowed = _SUBJECTS[subject]
    return CalcFactTypeDef(
        key,
        title,
        description,
        CalcValueKind.COUNT,
        required,
        allowed,
        unit=unit,
        qualifier_options=qualifiers,
    )


def _number(
    key: str,
    title: str,
    description: str,
    unit: str,
    subject: str,
    *,
    abs_tolerance: str = "0",
    rel_tolerance: str = "0",
    signed: bool = False,
) -> CalcFactTypeDef:
    required, allowed = _SUBJECTS[subject]
    return CalcFactTypeDef(
        key,
        title,
        description,
        CalcValueKind.NUMBER,
        required,
        allowed,
        unit=unit,
        abs_tolerance=Decimal(abs_tolerance),
        rel_tolerance=Decimal(rel_tolerance),
        min_value=None if signed else Decimal(0),
    )


def _enum(
    key: str, title: str, description: str, subject: str, options: tuple[CalcEnumOptionDef, ...]
) -> CalcFactTypeDef:
    required, allowed = _SUBJECTS[subject]
    return CalcFactTypeDef(
        key,
        title,
        description,
        CalcValueKind.ENUM,
        required,
        allowed,
        options=options,
        min_value=None,
    )


def _flag(key: str, title: str, description: str, subject: str) -> CalcFactTypeDef:
    required, allowed = _SUBJECTS[subject]
    return CalcFactTypeDef(
        key, title, description, CalcValueKind.BOOLEAN, required, allowed, min_value=None
    )


def _text(
    key: str, title: str, description: str, subject: str, *, vor: bool = False
) -> CalcFactTypeDef:
    required, allowed = _SUBJECTS[subject]
    return CalcFactTypeDef(
        key,
        title,
        description,
        CalcValueKind.TEXT,
        required,
        allowed,
        min_value=None,
        customer_vor_admissible=vor,
    )


def _options(*pairs: tuple[str, str]) -> tuple[CalcEnumOptionDef, ...]:
    return tuple(CalcEnumOptionDef(value, title) for value, title in pairs)


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

APARTMENT_TYPES: Final = _options(
    ("STUDIO", "студия"),
    ("R1", "1-комнатная"),
    ("R2", "2-комнатная"),
    ("R3", "3-комнатная"),
    ("R4_PLUS", "4-комнатная и более"),
)

FIXTURE_TYPES: Final = _options(
    ("WASHBASIN", "умывальник"),
    ("KITCHEN_SINK", "мойка"),
    ("WC", "унитаз"),
    ("BATHTUB", "ванна"),
    ("SHOWER", "душ"),
    ("BIDET", "биде"),
    ("WASHING_MACHINE", "стиральная машина"),
    ("DISHWASHER", "посудомоечная машина"),
    ("CLEANING_SINK", "раковина или трап ПУИ"),
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
            # ---- PROMPT 02: исходные данные ВК стадии П --------------------------------
            _number(
                "building.elevation_zero_abs",
                "Абсолютная отметка ±0,000",
                "Абсолютная отметка уровня чистого пола первого этажа, как её пишет проект.",
                "m",
                "building",
                abs_tolerance="0.005",
                signed=True,
            ),
            _enum(
                "building.basement_type",
                "Подземная часть",
                "Что под первым этажом: там идут магистрали и выпуски.",
                "building",
                _options(
                    ("NONE", "нет"),
                    ("TECHNICAL_UNDERGROUND", "техподполье"),
                    ("BASEMENT", "подвал"),
                    ("UNDERGROUND_PARKING", "подземный паркинг"),
                ),
            ),
            _enum(
                "building.top_technical_space",
                "Верхнее техническое пространство",
                "Технический этаж или чердак: верхняя разводка и кольцевание Т3/Т4.",
                "building",
                _options(
                    ("NONE", "нет"),
                    ("TECHNICAL_FLOOR", "технический этаж"),
                    ("ATTIC", "технический чердак"),
                ),
            ),
            _enum(
                "building.roof_type",
                "Тип кровли",
                "Через кровлю выводится вытяжная часть канализационных стояков.",
                "building",
                _options(("FLAT", "плоская"), ("PITCHED", "скатная")),
            ),
            _count(
                "building.residents_count",
                "Жителей в корпусе",
                "Расчётное число жителей, как его сообщает проект.",
                "person",
                "building",
            ),
            _count(
                "building.apartments_by_type",
                "Квартир по типам",
                "Число квартир корпуса одного типа; тип — квалификатор.",
                "apartment",
                "building",
                APARTMENT_TYPES,
            ),
            _count(
                "building.fixtures_count",
                "Санитарных приборов по видам",
                "Число приборов одного вида по корпусу; вид — квалификатор.",
                "fixture",
                "building",
                FIXTURE_TYPES,
            ),
            _number(
                "floor.elevation",
                "Отметка этажа",
                "Отметка чистого пола этажа относительно ±0,000, как в названии плана.",
                "m",
                "floor",
                abs_tolerance="0.005",
                signed=True,
            ),
            _count(
                "floor.shafts_count",
                "Шахт и ниш ВК на этаже",
                "Вертикальные шахты и ниши для стояков и поэтажных узлов.",
                "shaft",
                "floor",
            ),
            _count(
                "floor.nonresidential_wet_rooms_count",
                "Помещений с водой вне квартир",
                "ПУИ, санузлы персонала и общественных зон, душевые, моечные на этаже.",
                "room",
                "floor",
            ),
            _count(
                "floor.commercial_units_count",
                "Встроенных помещений на этаже",
                "Коммерческие и общественные помещения со своими подключениями.",
                "premises",
                "floor",
            ),
            _number(
                "system.inlet_pressure",
                "Гарантированный напор на вводе",
                "Напор в точке подключения по ТУ; «м» в тексте напора — метры водяного столба.",
                "kPa",
                "system",
                rel_tolerance="0.01",
            ),
            _count(
                "system.inlets_count",
                "Вводов",
                "Число вводов системы.",
                "inlet",
                "system",
            ),
            _number(
                "system.inlet_diameter",
                "Диаметр ввода",
                "Диаметр ввода, если его задают ТУ или проект.",
                "mm",
                "system",
            ),
            _count(
                "system.zones_count",
                "Зон по давлению",
                "Число зон системы по давлению.",
                "zone",
                "system",
            ),
            _flag(
                "system.pump_station_present",
                "Насосная установка",
                "Предусмотрена ли насосная установка повышения давления.",
                "system",
            ),
            _count(
                "system.water_meter_units_count",
                "Узлов учёта",
                "Узлы учёта воды: общий на вводе и поквартирные.",
                "meter",
                "system",
            ),
            _number(
                "system.flow_daily",
                "Суточный расход",
                "Расход системы за сутки по пояснительной записке — для сверки с расчётом.",
                "m3_day",
                "system",
                rel_tolerance="0.01",
            ),
            _number(
                "system.flow_hourly_max",
                "Максимальный часовой расход",
                "Максимальный часовой расход по пояснительной записке — для сверки.",
                "m3_h",
                "system",
                rel_tolerance="0.01",
            ),
            _number(
                "system.flow_second_max",
                "Максимальный секундный расход",
                "Максимальный секундный расход по пояснительной записке — для сверки.",
                "l_s",
                "system",
                rel_tolerance="0.01",
            ),
            _number(
                "system.supply_temperature",
                "Температура горячей воды",
                "Температура в подающем трубопроводе горячего водоснабжения.",
                "degC",
                "system",
                abs_tolerance="1",
            ),
            _enum(
                "system.hot_water_source",
                "Источник горячей воды",
                "Откуда приходит горячая вода: там начинаются Т3 и Т4.",
                "system",
                _options(
                    ("ITP", "ИТП"),
                    ("CTP", "ЦТП"),
                    ("BOILER_ROOM", "котельная"),
                    ("INDIVIDUAL_HEATERS", "индивидуальные водонагреватели"),
                    ("OTHER", "иное"),
                ),
            ),
            _flag(
                "system.towel_dryers_on_hot_water",
                "Полотенцесушители от ГВС",
                "Полотенцесушители присоединены к стоякам горячей воды.",
                "system",
            ),
            _count(
                "system.outlets_count",
                "Выпусков",
                "Число выпусков системы в наружную сеть.",
                "outlet",
                "system",
            ),
            _number(
                "system.outlet_diameter",
                "Диаметр выпуска",
                "Диаметр выпуска, если его задаёт проект.",
                "mm",
                "system",
            ),
            _number(
                "system.outlet_elevation",
                "Отметка лотка выпуска",
                "Отметка лотка выпуска относительно ±0,000.",
                "m",
                "system",
                abs_tolerance="0.005",
                signed=True,
            ),
            _enum(
                "system.vent_scheme",
                "Вентиляция стояков",
                "Как вентилируются канализационные стояки.",
                "system",
                _options(
                    ("VENTED_STACKS", "вытяжная часть через кровлю"),
                    ("AIR_ADMITTANCE_VALVES", "вентиляционные клапаны"),
                    ("MIXED", "смешанная"),
                ),
            ),
            _number(
                "system.main_diameter",
                "Диаметр магистрали",
                "Диаметр магистрали по схеме проекта, если он указан.",
                "mm",
                "system",
            ),
            _number(
                "system.riser_diameter",
                "Диаметр стояков",
                "Диаметр стояков по схеме проекта, если он указан.",
                "mm",
                "system",
            ),
            _text(
                "system.required_manufacturer",
                "Заданный производитель",
                "Производитель или марка, заданные бренд-листом или требованиями Заказчика.",
                "system",
                vor=True,
            ),
            _text(
                "system.customer_requirements",
                "Требования Заказчика",
                "Технические требования и ограничения Заказчика к системе.",
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
    present = subject.present_fields() - {"qualifier"}
    missing = definition.required_subject - present
    if missing:
        return "не указано: " + ", ".join(sorted(missing))
    extra = present - definition.allowed_subject
    if extra:
        return "лишнее для этого типа: " + ", ".join(sorted(extra))
    allowed = [option.value for option in definition.qualifier_options]
    if not allowed:
        return None if subject.qualifier is None else "у этого типа нет квалификатора"
    if subject.qualifier not in allowed:
        return "квалификатор — одно из: " + ", ".join(allowed)
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
