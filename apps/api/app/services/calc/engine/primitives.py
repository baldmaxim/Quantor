"""Вычислительные примитивы — арифметика по фактам без версии правила (PROMPT 06).

Счёт, сумма, разность, максимум, обход этажей. Это не инженерные решения, поэтому у примитива
нет ни правила, ни параметров: константу в примитив не спрятать, коэффициент и запас — только
утверждённым правилом. «Сколько квартир на стояк» примитивом не выразить.

Реестр отдельный от реализаций правил: версия правила не может сослаться на примитив, а
примитив — выдать себя за норматив. В цепочке расчёта шаг-примитив так и называется.

Этажи — коды мест фактов: «12», «-1», «2..24». Набор по этажам должен покрывать нужные этажи
ровно один раз: пробел или перекрытие — `InsufficientInputError`, шаг не определён, а не
«примерно так». Отсутствие значения не превращается в ноль никогда. Порядок членов набора не
значим: примитив упорядочивает этажи сам.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from app.contracts.calc.fact_types import FIXTURE_TYPES
from app.services.calc.engine.handlers import (
    GoldenCase,
    HandlerContext,
    HandlerResult,
    HandlerSpec,
    InsufficientInputError,
    SeriesMember,
    build_registry,
)
from app.services.calc.engine.numbers import ru_number
from app.services.calc.engine.quantity import Quantity

PRIMITIVE_PREFIX: Final = "primitive."
_FIXTURE_TITLES: Final = {item.value: item.title for item in FIXTURE_TYPES}


def floor_range(code: str) -> tuple[int, int]:
    """Код этажа → первый и последний этаж: «2..24» → (2, 24), «-1» → (-1, -1)."""
    if ".." in code:
        low, high = code.split("..", 1)
        return int(low), int(high)
    return int(code), int(code)


def floors_text(floors: Iterable[int]) -> str:
    """«1, 5–7, 25»: подряд идущие этажи сжаты в диапазон."""
    ordered = sorted(set(floors))
    parts: list[str] = []
    start = previous = None
    for floor in ordered:
        if start is None or previous is None:
            start = previous = floor
        elif floor == previous + 1:
            previous = floor
        else:
            parts.append(str(start) if start == previous else f"{start}–{previous}")
            start = previous = floor
    if start is not None and previous is not None:
        parts.append(str(start) if start == previous else f"{start}–{previous}")
    return ", ".join(parts)


def _whole(quantity: Quantity, what: str) -> int:
    value = quantity.value
    if value != value.to_integral_value():
        raise InsufficientInputError(f"{what}: {ru_number(value)} — не целое")
    return int(value)


def _by_floor(members: tuple[SeriesMember, ...], what: str) -> dict[int, Decimal]:
    """Значение каждого названного этажа. Этаж, названный дважды, — перекрытие."""
    values: dict[int, Decimal] = {}
    twice: set[int] = set()
    for member in members:
        low, high = floor_range(member.member)
        for floor in range(low, high + 1):
            if floor in values:
                twice.add(floor)
            values[floor] = member.value.value
    if twice:
        raise InsufficientInputError(f"{what}: этажи названы дважды — {floors_text(twice)}")
    return values


def _cover(values: dict[int, Decimal], low: int, high: int, what: str) -> dict[int, Decimal]:
    missing = [floor for floor in range(low, high + 1) if floor not in values]
    if missing:
        raise InsufficientInputError(f"{what}: нет значения для этажей {floors_text(missing)}")
    return {floor: values[floor] for floor in range(low, high + 1)}


def _groups(values: dict[int, Decimal], unit: str) -> str:
    """«эт. 1 — 0 кв.; эт. 2–24 — 6 кв.»: соседние этажи с одним значением — одной группой."""
    parts: list[str] = []
    run: list[int] = []
    for floor in sorted(values):
        if run and (floor != run[-1] + 1 or values[floor] != values[run[-1]]):
            parts.append(f"эт. {floors_text(run)} — {ru_number(values[run[-1]])} {unit}")
            run = []
        run.append(floor)
    if run:
        parts.append(f"эт. {floors_text(run)} — {ru_number(values[run[-1]])} {unit}")
    return "; ".join(parts)


# ------------------------------------------------------------------------ этажная структура


def _floor_structure(context: HandlerContext) -> HandlerResult:
    floors = _whole(context.inputs["floors"], "этажность")
    if floors < 1:
        raise InsufficientInputError("этажность меньше одного этажа")
    named = _by_floor(context.series["apartments"], "квартирография")
    above = sorted(floor for floor in named if floor > floors)
    if above:
        raise InsufficientInputError(
            f"квартирография называет этажи {floors_text(above)}, а надземных этажей {floors}"
        )
    per_floor = _cover(named, 1, floors, "квартирография")
    served = [floor for floor, count in per_floor.items() if count > 0]
    if not served:
        raise InsufficientInputError("ни на одном надземном этаже нет квартир")
    top = max(served)
    total = sum(per_floor.values(), Decimal(0))
    widest = max(per_floor.values())
    return HandlerResult(
        outputs={
            "top_floor": Quantity.of(Decimal(top), "floor"),
            "served_floors": Quantity.of(Decimal(len(served)), "floor"),
            "apartments_total": Quantity.of(total, "apartment"),
            "apartments_per_floor_max": Quantity.of(widest, "apartment"),
        },
        explanation=(
            f"Надземных этажей {floors}; квартирография: {_groups(per_floor, 'кв.')}; "
            f"этажи с квартирами: {floors_text(served)} ({len(served)} эт.), верхний — {top}-й; "
            f"квартир {ru_number(total)}, на этаже не больше {ru_number(widest)}"
        ),
    )


def _vertical_span(context: HandlerContext) -> HandlerResult:
    top = _whole(context.inputs["top_floor"], "верхний этаж")
    elevations = {
        floor_range(item.member)[0]: item.value.value
        for item in context.series["elevations"]
        if floor_range(item.member)[0] == floor_range(item.member)[1]
    }
    if top <= 1:
        length = Decimal(0)
        text = "Верхний обслуживаемый этаж — первый: межэтажного участка нет"
    elif 1 in elevations and top in elevations:
        length = elevations[top] - elevations[1]
        if length <= 0:
            raise InsufficientInputError(
                f"отметка {top}-го этажа не выше отметки 1-го: {ru_number(elevations[top])} м"
            )
        text = (
            f"Отметка {top}-го этажа {ru_number(elevations[top])} м − отметка 1-го этажа "
            f"{ru_number(elevations[1])} м = {ru_number(length)} м"
        )
    else:
        heights = _cover(
            _by_floor(context.series["heights"], "высоты этажей"), 1, top - 1, "высоты этажей"
        )
        length = sum(heights.values(), Decimal(0))
        text = (
            f"Отметок 1-го и {top}-го этажей нет; сумма высот этажей 1–{top - 1}: "
            f"{_groups(heights, 'м')} = {ru_number(length)} м"
        )
    return HandlerResult(
        outputs={
            "interfloor_length": Quantity.of(length, "m"),
            "slab_crossings": Quantity.of(Decimal(max(top - 1, 0)), "slab"),
        },
        explanation=(
            f"{text}. Перекрытий между 1-м и {top}-м этажом: {max(top - 1, 0)}. Участки ниже "
            "1-го этажа и выше верхнего здесь не считаются"
        ),
    )


def _floor_total(what: str, unit: str, unit_title: str) -> HandlerSpec:
    def compute(context: HandlerContext) -> HandlerResult:
        floors = _whole(context.inputs["floors"], "этажность")
        named = _by_floor(context.series["values"], what)
        per_floor = _cover(named, 1, floors, what)
        total = sum(per_floor.values(), Decimal(0))
        return HandlerResult(
            outputs={"total": Quantity.of(total, unit)},
            explanation=f"{what.capitalize()}: {_groups(per_floor, unit_title)}; всего "
            f"{ru_number(total)} {unit_title}",
        )

    return HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}floor_total_{unit}.v1",
        title=f"Примитив: сумма по этажам — {what}",
        inputs={"floors": "floor"},
        parameters={},
        outputs={"total": unit},
        series={"values": unit},
        compute=compute,
        golden=(
            GoldenCase({"floors": "3"}, {}, {"total": "4"}, {"values": {"1": "0", "2..3": "2"}}),
            GoldenCase({"floors": "3"}, {}, {}, {"values": {"2..3": "2"}}),
        ),
    )


def _floor_sum(what: str, unit: str, unit_title: str) -> HandlerSpec:
    """Сумма названного по этажам — без требования покрытия: неназванный этаж не учтён, а не 0.

    Нужна только для сведений о потребителях вне квартир: «встроенных помещений названо 4».
    """

    def compute(context: HandlerContext) -> HandlerResult:
        named = _by_floor(context.series["values"], what)
        if not named:
            raise InsufficientInputError(f"{what} на этажах не названы")
        total = sum(named.values(), Decimal(0))
        return HandlerResult(
            outputs={"total": Quantity.of(total, unit)},
            explanation=f"{what.capitalize()} названы: {_groups(named, unit_title)}; всего "
            f"{ru_number(total)} {unit_title}. Неназванные этажи не учтены — это не ноль",
        )

    return HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}floor_sum_{unit}.v1",
        title=f"Примитив: сумма названного по этажам — {what}",
        inputs={},
        parameters={},
        outputs={"total": unit},
        series={"values": unit},
        compute=compute,
        golden=(
            GoldenCase({}, {}, {"total": "4"}, {"values": {"1": "2", "2..3": "1"}}),
            GoldenCase({}, {}, {}, {"values": {}}),
        ),
    )


def _apartments_check(context: HandlerContext) -> HandlerResult:
    documented = context.inputs["documented"]
    calculated = context.inputs["calculated"]
    difference = documented - calculated
    return HandlerResult(
        outputs={"discrepancy": difference},
        explanation=(
            f"В документе {ru_number(documented.value)} кв., по квартирографии этажей "
            f"{ru_number(calculated.value)} кв.: расхождение {ru_number(difference.value)} кв."
        ),
    )


def _fixtures_total(context: HandlerContext) -> HandlerResult:
    members = sorted(context.series["fixtures"], key=lambda item: item.member)
    if not members:
        raise InsufficientInputError("санитарные приборы по видам не названы")
    total = sum((item.value.value for item in members), Decimal(0))
    listed = "; ".join(
        f"{_FIXTURE_TITLES.get(item.member, item.member)} — {ru_number(item.value.value)}"
        for item in members
    )
    return HandlerResult(
        outputs={"total": Quantity.of(total, "fixture")},
        explanation=f"Приборы по документации: {listed}; всего {ru_number(total)} приб.",
    )


def _shafts_max(context: HandlerContext) -> HandlerResult:
    named = _by_floor(context.series["shafts"], "шахты")
    if not named:
        raise InsufficientInputError("шахты ВК на этажах не названы")
    widest = max(named.values())
    return HandlerResult(
        outputs={"shafts_max": Quantity.of(widest, "shaft")},
        explanation=f"Шахты и ниши ВК: {_groups(named, 'шт.')}; на этаже не больше "
        f"{ru_number(widest)}",
    )


PRIMITIVE_SPECS: Final = (
    HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}floor_structure.v1",
        title="Примитив: этажи с квартирами, верхний этаж, итог квартир",
        inputs={"floors": "floor"},
        parameters={},
        outputs={
            "top_floor": "floor",
            "served_floors": "floor",
            "apartments_total": "apartment",
            "apartments_per_floor_max": "apartment",
        },
        series={"apartments": "apartment"},
        compute=_floor_structure,
        golden=(
            GoldenCase(
                {"floors": "4"},
                {},
                {
                    "top_floor": "4",
                    "served_floors": "3",
                    "apartments_total": "18",
                    "apartments_per_floor_max": "6",
                },
                {"apartments": {"1": "0", "2..4": "6"}},
            ),
            GoldenCase({"floors": "4"}, {}, {}, {"apartments": {"2..4": "6"}}),
            GoldenCase({"floors": "3"}, {}, {}, {"apartments": {"1..3": "4", "3": "2"}}),
        ),
    ),
    HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}vertical_span.v1",
        title="Примитив: межэтажный пролёт стояка по отметкам или высотам",
        inputs={"top_floor": "floor"},
        parameters={},
        outputs={"interfloor_length": "m", "slab_crossings": "slab"},
        series={"heights": "m", "elevations": "m"},
        compute=_vertical_span,
        golden=(
            GoldenCase(
                {"top_floor": "4"},
                {},
                {"interfloor_length": "10.2", "slab_crossings": "3"},
                {"heights": {"1": "4.2", "2..3": "3"}, "elevations": {}},
            ),
            GoldenCase(
                {"top_floor": "4"},
                {},
                {"interfloor_length": "10.35", "slab_crossings": "3"},
                {"heights": {"1": "4.2"}, "elevations": {"1": "0", "4": "10.35"}},
            ),
            GoldenCase(
                {"top_floor": "4"},
                {},
                {},
                {"heights": {"1": "4.2", "3": "3"}, "elevations": {}},
            ),
        ),
    ),
    _floor_total("санузлы", "bathroom", "с/у"),
    _floor_total("кухни", "kitchen", "кух."),
    _floor_sum("встроенные помещения", "premises", "встр. пом."),
    _floor_sum("помещения с водой вне квартир", "room", "пом."),
    HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}apartments_check.v1",
        title="Примитив: расхождение итога квартир документа и квартирографии",
        inputs={"documented": "apartment", "calculated": "apartment"},
        parameters={},
        outputs={"discrepancy": "apartment"},
        compute=_apartments_check,
        golden=(
            GoldenCase({"documented": "138", "calculated": "138"}, {}, {"discrepancy": "0"}),
            GoldenCase({"documented": "140", "calculated": "138"}, {}, {"discrepancy": "2"}),
        ),
    ),
    HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}fixtures_total.v1",
        title="Примитив: итог санитарных приборов по видам",
        inputs={},
        parameters={},
        outputs={"total": "fixture"},
        series={"fixtures": "fixture"},
        compute=_fixtures_total,
        golden=(
            GoldenCase({}, {}, {"total": "150"}, {"fixtures": {"WC": "100", "BATHTUB": "50"}}),
            GoldenCase({}, {}, {}, {"fixtures": {}}),
        ),
    ),
    HandlerSpec(
        implementation_key=f"{PRIMITIVE_PREFIX}shafts_max.v1",
        title="Примитив: наибольшее число шахт ВК на этаже",
        inputs={},
        parameters={},
        outputs={"shafts_max": "shaft"},
        series={"shafts": "shaft"},
        compute=_shafts_max,
        golden=(GoldenCase({}, {}, {"shafts_max": "3"}, {"shafts": {"1": "2", "2..24": "3"}}),),
    ),
)


def _registry(specs: Iterable[HandlerSpec]) -> MappingProxyType[str, HandlerSpec]:
    specs = tuple(specs)
    for spec in specs:
        if not spec.implementation_key.startswith(PRIMITIVE_PREFIX):
            raise ValueError(f"примитив {spec.implementation_key} без префикса {PRIMITIVE_PREFIX}")
        if spec.parameters:
            raise ValueError(f"у примитива {spec.implementation_key} не бывает параметров")
    return build_registry(specs)


PRIMITIVES: Final[MappingProxyType[str, HandlerSpec]] = _registry(PRIMITIVE_SPECS)
