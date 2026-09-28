"""Реализации правил ВК стадии П (PROMPT 06) — исполняются только утверждённой версией правила.

Здесь нет ни одного инженерного числа. Реализация — форма формулы: «стояков = ⌈квартир на этаже
/ квартир на стояк⌉», а сколько квартир на стояк, какой шаг креплений и какой запас — параметры
версии правила, которые задаёт и утверждает инженер со ссылкой на источник. Пока версии нет,
шаг калькулятора заблокирован, и результат не выдумывается.

Контрольные примеры — синтетические: они проверяют арифметику реализации, а не норму.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from app.contracts.calc.engine import CalcRoundingPolicy
from app.contracts.calc.enums import CalcRoundingMode
from app.services.calc.engine.handlers import (
    GoldenCase,
    HandlerContext,
    HandlerResult,
    HandlerRounding,
    HandlerSpec,
)
from app.services.calc.engine.numbers import apply_rounding, ru_number
from app.services.calc.engine.quantity import Quantity

_UP: Final = CalcRoundingPolicy(mode=CalcRoundingMode.CEILING, quantum="1")
_WHOLE: Final = "количество — целое: частное округляется вверх"


def _n(quantity: Quantity) -> str:
    return ru_number(quantity.value)


def _risers_range(context: HandlerContext) -> HandlerResult:
    apartments = context.inputs["apartments_per_floor"]
    low = context.parameters["per_riser_min"]
    high = context.parameters["per_riser_max"]
    risers_min, quotient_min = apartments.divided_rounded(high, _UP)
    risers_max, quotient_max = apartments.divided_rounded(low, _UP)
    return HandlerResult(
        outputs={"risers_min": risers_min, "risers_max": risers_max},
        explanation=(
            f"{_n(apartments)} кв. на этаже / {_n(high)} кв. на стояк = {ru_number(quotient_min)}"
            f" → {_n(risers_min)} ст.; {_n(apartments)} / {_n(low)} = {ru_number(quotient_max)}"
            f" → {_n(risers_max)} ст."
        ),
        roundings=(
            HandlerRounding("risers_min", quotient_min, risers_min.value, "riser", _UP, _WHOLE),
            HandlerRounding("risers_max", quotient_max, risers_max.value, "riser", _UP, _WHOLE),
        ),
    )


def _end_segments(context: HandlerContext) -> HandlerResult:
    bottom = context.parameters["bottom_length"]
    top = context.parameters["top_length"]
    return HandlerResult(
        outputs={"bottom": bottom, "top": top},
        explanation=(
            f"Участок стояка ниже 1-го этажа {_n(bottom)} м, выше верхнего этажа {_n(top)} м"
        ),
    )


def _connection_length(context: HandlerContext) -> HandlerResult:
    low = context.parameters["per_connection_min"]
    high = context.parameters["per_connection_max"]
    return HandlerResult(
        outputs={"length_min": low, "length_max": high},
        explanation=f"Длина одного этажного подключения {_n(low)}–{_n(high)} м",
    )


def _zones_by_height(context: HandlerContext) -> HandlerResult:
    height = context.inputs["height"]
    limit = context.parameters["zone_height_max"]
    zones, quotient = height.divided_rounded(limit, _UP)
    return HandlerResult(
        outputs={"zones": zones},
        explanation=(
            f"Высота обслуживаемой части {_n(height)} м / наибольшая высота зоны {_n(limit)} м = "
            f"{ru_number(quotient)} → {_n(zones)} зон."
        ),
        roundings=(HandlerRounding("zones", quotient, zones.value, "zone", _UP, _WHOLE),),
    )


def _fixtures_by_rooms(context: HandlerContext) -> HandlerResult:
    bathrooms = context.inputs["bathrooms"]
    kitchens = context.inputs["kitchens"]
    per_bathroom = context.parameters["per_bathroom"]
    per_kitchen = context.parameters["per_kitchen"]
    raw = bathrooms * per_bathroom + kitchens * per_kitchen
    rounded = apply_rounding(raw.value, _UP)
    roundings = (
        ()
        if rounded == raw.value
        else (HandlerRounding("fixtures", raw.value, rounded, "fixture", _UP, _WHOLE),)
    )
    return HandlerResult(
        outputs={"fixtures": Quantity(rounded, raw.dims)},
        explanation=(
            f"{_n(bathrooms)} с/у × {_n(per_bathroom)} приб. + {_n(kitchens)} кух. × "
            f"{_n(per_kitchen)} приб. = {ru_number(rounded)} приб."
        ),
        roundings=roundings,
    )


def _supports(context: HandlerContext) -> HandlerResult:
    vertical = context.parameters["vertical_spacing"]
    horizontal = context.parameters["horizontal_spacing"]
    return HandlerResult(
        outputs={"vertical": vertical, "horizontal": horizontal},
        explanation=f"Шаг креплений: стояки {_n(vertical)} м, горизонтальные участки "
        f"{_n(horizontal)} м",
    )


def _fittings_per_meter(context: HandlerContext) -> HandlerResult:
    rate = context.parameters["rate"]
    return HandlerResult(
        outputs={"per_meter": rate},
        explanation=f"Резервный метод: {_n(rate)} фитинга на метр трассы — не топология",
    )


def _flags(context: HandlerContext, names: dict[str, str], title: str) -> HandlerResult:
    outputs: dict[str, Quantity] = {}
    for parameter, output in names.items():
        value = context.parameters[parameter]
        if value.value not in (Decimal(0), Decimal(1)):
            raise ValueError(f"«{parameter}» — признак 0 или 1, а не {_n(value)}")
        outputs[output] = value
    shown = "; ".join(f"{output}: {'да' if outputs[output].value else 'нет'}" for output in outputs)
    return HandlerResult(outputs=outputs, explanation=f"{title}: {shown}")


_INSULATION: Final = {
    "risers_flag": "risers",
    "connections_flag": "connections",
    "mains_flag": "mains",
}
_PENETRATIONS: Final = {"sleeve_flag": "sleeve", "firestop_flag": "firestop"}


def _insulation(context: HandlerContext) -> HandlerResult:
    return _flags(context, _INSULATION, "Изолируются")


def _penetrations(context: HandlerContext) -> HandlerResult:
    return _flags(context, _PENETRATIONS, "Проходки через перекрытия")


def _length_reserve(context: HandlerContext) -> HandlerResult:
    base = context.inputs["base"]
    reserve = context.parameters["reserve_length"]
    value = base + reserve
    return HandlerResult(
        outputs={"value": value},
        explanation=f"{_n(base)} м + тендерный резерв {_n(reserve)} м = {_n(value)} м на стояк",
    )


def _per_riser_floor(context: HandlerContext) -> HandlerResult:
    count = context.parameters["per_floor"]
    return HandlerResult(
        outputs={"connections": count},
        explanation=f"Подключений на стояк на обслуживаемом этаже: {_n(count)}",
    )


def _per_riser(context: HandlerContext) -> HandlerResult:
    count = context.parameters["per_riser"]
    return HandlerResult(outputs={"count": count}, explanation=f"На каждый стояк: {_n(count)}")


VK_HANDLERS: Final = (
    HandlerSpec(
        implementation_key="vk.risers.count_range.v1",
        title="ВК: диапазон числа стояков по квартирам на этаже",
        inputs={"apartments_per_floor": "apartment"},
        parameters={"per_riser_min": "apartment", "per_riser_max": "apartment"},
        outputs={"risers_min": "riser", "risers_max": "riser"},
        compute=_risers_range,
        golden=(
            GoldenCase(
                {"apartments_per_floor": "8"},
                {"per_riser_min": "2", "per_riser_max": "3"},
                {"risers_min": "3", "risers_max": "4"},
            ),
            GoldenCase(
                {"apartments_per_floor": "6"},
                {"per_riser_min": "3", "per_riser_max": "3"},
                {"risers_min": "2", "risers_max": "2"},
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.riser.end_segments.v1",
        title="ВК: участки стояка ниже 1-го этажа и выше верхнего",
        inputs={},
        parameters={"bottom_length": "m", "top_length": "m"},
        outputs={"bottom": "m", "top": "m"},
        compute=_end_segments,
        golden=(
            GoldenCase(
                {}, {"bottom_length": "1.5", "top_length": "0.5"}, {"bottom": "1.5", "top": "0.5"}
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.connection.length_range.v1",
        title="ВК: диапазон длины этажного подключения",
        inputs={},
        parameters={"per_connection_min": "m", "per_connection_max": "m"},
        outputs={"length_min": "m", "length_max": "m"},
        compute=_connection_length,
        golden=(
            GoldenCase(
                {},
                {"per_connection_min": "2", "per_connection_max": "3.5"},
                {"length_min": "2", "length_max": "3.5"},
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.zones.by_height.v1",
        title="ВК: число зон по высоте обслуживаемой части",
        inputs={"height": "m"},
        parameters={"zone_height_max": "m"},
        outputs={"zones": "zone"},
        compute=_zones_by_height,
        golden=(
            GoldenCase({"height": "69"}, {"zone_height_max": "40"}, {"zones": "2"}),
            GoldenCase({"height": "40"}, {"zone_height_max": "40"}, {"zones": "1"}),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.fixtures.by_rooms.v1",
        title="ВК: точки водоотведения по санузлам и кухням",
        inputs={"bathrooms": "bathroom", "kitchens": "kitchen"},
        parameters={"per_bathroom": None, "per_kitchen": None},
        outputs={"fixtures": "fixture"},
        compute=_fixtures_by_rooms,
        golden=(
            GoldenCase(
                {"bathrooms": "10", "kitchens": "8"},
                {"per_bathroom": "3", "per_kitchen": "1"},
                {"fixtures": "38"},
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.supports.spacing.v1",
        title="ВК: шаг креплений трубопроводов",
        inputs={},
        parameters={"vertical_spacing": "m", "horizontal_spacing": "m"},
        outputs={"vertical": "m", "horizontal": "m"},
        compute=_supports,
        golden=(
            GoldenCase(
                {},
                {"vertical_spacing": "3", "horizontal_spacing": "2"},
                {"vertical": "3", "horizontal": "2"},
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.fittings.per_meter.v1",
        title="ВК: резервный метод фитингов — на метр трассы",
        inputs={},
        parameters={"rate": None},
        outputs={"per_meter": None},
        compute=_fittings_per_meter,
        golden=(GoldenCase({}, {"rate": "0.5"}, {"per_meter": "0.5"}),),
    ),
    HandlerSpec(
        implementation_key="vk.insulation.scope.v1",
        title="ВК: какие участки изолируются",
        inputs={},
        parameters=dict.fromkeys(_INSULATION),
        outputs=dict.fromkeys(_INSULATION.values()),
        compute=_insulation,
        golden=(
            GoldenCase(
                {},
                {"risers_flag": "1", "connections_flag": "0", "mains_flag": "1"},
                {"risers": "1", "connections": "0", "mains": "1"},
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.penetrations.treatment.v1",
        title="ВК: гильзы и огнезащита проходок через перекрытия",
        inputs={},
        parameters=dict.fromkeys(_PENETRATIONS),
        outputs=dict.fromkeys(_PENETRATIONS.values()),
        compute=_penetrations,
        golden=(
            GoldenCase(
                {}, {"sleeve_flag": "1", "firestop_flag": "0"}, {"sleeve": "1", "firestop": "0"}
            ),
        ),
    ),
    HandlerSpec(
        implementation_key="vk.tender.length_reserve.v1",
        title="ВК: тендерный резерв длины стояка",
        inputs={"base": "m"},
        parameters={"reserve_length": "m"},
        outputs={"value": "m"},
        compute=_length_reserve,
        golden=(GoldenCase({"base": "69"}, {"reserve_length": "1"}, {"value": "70"}),),
    ),
    HandlerSpec(
        implementation_key="vk.topology.per_riser_floor.v1",
        title="ВК: подключений на стояк на этаже",
        inputs={},
        parameters={"per_floor": None},
        outputs={"connections": None},
        compute=_per_riser_floor,
        golden=(GoldenCase({}, {"per_floor": "2"}, {"connections": "2"}),),
    ),
    HandlerSpec(
        implementation_key="vk.topology.per_riser.v1",
        title="ВК: элементов на каждый стояк",
        inputs={},
        parameters={"per_riser": None},
        outputs={"count": None},
        compute=_per_riser,
        golden=(GoldenCase({}, {"per_riser": "1"}, {"count": "1"}),),
    ),
)
