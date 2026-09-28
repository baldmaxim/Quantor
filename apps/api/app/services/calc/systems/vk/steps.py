"""Шаги рабочих калькуляторов ВК стадии П (PROMPT 06): слои A–D отдельными шагами.

- A. Потребность — квартиры и приборы: примитивы по квартирографии, для К1 — точки
  водоотведения по таблице приборов или утверждённым правилом.
- B. Структура — этажи с квартирами, межэтажный пролёт, шахты (примитивы), число стояков и
  зоны (только утверждённым правилом).
- C. Топология — в синтезаторе (правило схемы, арматура по узлам).
- D. Количества — параметры утверждённых правил: участки стояка, длина подключений, шаг
  креплений, изоляция, проходки, резервный метод фитингов. Сами объёмы собирает слой паспорта
  из графа, а не этот калькулятор.

Калькулятор частичный: нет правила числа стояков — стояки не рассчитаны, а межэтажный пролёт и
квартирография посчитаны. Документальное значение (стояки, зоны на схеме) калькулятор не
пересчитывает: его берёт синтезатор как факт.
"""

from __future__ import annotations

from typing import Final

from app.contracts.calc.enums import (
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcResultCategory,
    CalcRuleType,
    CalcScenario,
)
from app.services.calc.engine.calculators import (
    AssumptionSpec,
    CalculatorDef,
    FactBinding,
    ResultDef,
    SeriesBinding,
    StepBinding,
    StepDef,
)
from app.services.calc.systems.vk.spec import VkSystemSpec

SCOPE_FIELDS: Final = ("building", "discipline", "system_code")
_PLACE: Final = ("building", "section")
_E, _N, _G, _M = (
    CalcRuleType.ENGINEERING,
    CalcRuleType.NORMATIVE,
    CalcRuleType.GEOMETRY,
    CalcRuleType.MANUFACTURER,
)
TENDER_RULE: Final = "vk.tender.riser_length_reserve"
SUPPORTS_RULE: Final = "vk.supports.spacing"
FITTINGS_RULE: Final = "vk.fittings.per_meter"
PENETRATIONS_RULE: Final = "vk.penetrations.treatment"
FIXTURES_RULE: Final = "vk.k1.fixtures.by_rooms"


def _floors(fact_type: str) -> SeriesBinding:
    return SeriesBinding(fact_type, _PLACE, "floor")


def _rule(
    key: str,
    title: str,
    rule_key: str,
    types: frozenset[CalcRuleType],
    outputs: tuple[str, ...],
    **steps: StepBinding,
) -> StepDef:
    return StepDef(
        step_key=key,
        title=title,
        outputs=outputs,
        rule_key=rule_key,
        allowed_rule_types=types,
        steps=steps,
    )


def _shared() -> list[StepDef]:
    """Общие функции: этажность, квартирография, вертикальная структура, потребители вне квартир."""
    return [
        StepDef(
            step_key="structure_floors",
            title="Этажи с квартирами и итог квартир",
            outputs=("top_floor", "served_floors", "apartments_total", "apartments_per_floor_max"),
            primitive="primitive.floor_structure.v1",
            facts={"floors": FactBinding("building.floors_above_ground", ("building",))},
            series={"apartments": _floors("floor.apartments_count")},
        ),
        StepDef(
            step_key="structure_vertical",
            title="Межэтажный пролёт стояка",
            outputs=("interfloor_length", "slab_crossings"),
            primitive="primitive.vertical_span.v1",
            steps={"top_floor": StepBinding("structure_floors", "top_floor")},
            series={"heights": _floors("floor.height"), "elevations": _floors("floor.elevation")},
        ),
        StepDef(
            step_key="demand_apartments_check",
            title="Сверка итога квартир документа с квартирографией",
            outputs=("discrepancy",),
            primitive="primitive.apartments_check.v1",
            facts={"documented": FactBinding("building.apartments_total", ("building",))},
            steps={"calculated": StepBinding("structure_floors", "apartments_total")},
        ),
        StepDef(
            step_key="structure_shafts",
            title="Шахты ВК на этаже",
            outputs=("shafts_max",),
            primitive="primitive.shafts_max.v1",
            series={"shafts": _floors("floor.shafts_count")},
        ),
        StepDef(
            step_key="demand_premises",
            title="Встроенные помещения",
            outputs=("total",),
            primitive="primitive.floor_sum_premises.v1",
            series={"values": _floors("floor.commercial_units_count")},
        ),
        StepDef(
            step_key="demand_wet_rooms",
            title="Помещения с водой вне квартир",
            outputs=("total",),
            primitive="primitive.floor_sum_room.v1",
            series={"values": _floors("floor.nonresidential_wet_rooms_count")},
        ),
    ]


def _drain_points(spec: VkSystemSpec) -> list[StepDef]:
    if not spec.drain_points:
        return []
    floors = FactBinding("building.floors_above_ground", ("building",))
    return [
        StepDef(
            step_key="demand_fixtures_observed",
            title="Санитарные приборы по таблице",
            outputs=("total",),
            primitive="primitive.fixtures_total.v1",
            series={
                "fixtures": SeriesBinding("building.fixtures_count", ("building",), "qualifier")
            },
        ),
        StepDef(
            step_key="demand_bathrooms",
            title="Санузлы по этажам",
            outputs=("total",),
            primitive="primitive.floor_total_bathroom.v1",
            facts={"floors": floors},
            series={"values": _floors("floor.bathrooms_count")},
        ),
        StepDef(
            step_key="demand_kitchens",
            title="Кухни по этажам",
            outputs=("total",),
            primitive="primitive.floor_total_kitchen.v1",
            facts={"floors": floors},
            series={"values": _floors("floor.kitchens_count")},
        ),
        _rule(
            "demand_fixtures_by_rooms",
            "Точки водоотведения по санузлам и кухням",
            FIXTURES_RULE,
            frozenset({_E, _N}),
            ("fixtures",),
            bathrooms=StepBinding("demand_bathrooms", "total"),
            kitchens=StepBinding("demand_kitchens", "total"),
        ),
    ]


def _structure(spec: VkSystemSpec) -> list[StepDef]:
    steps = [
        _rule(
            "structure_risers",
            "Диапазон числа стояков",
            spec.risers_rule,
            frozenset({_E}),
            ("risers_min", "risers_max"),
            apartments_per_floor=StepBinding("structure_floors", "apartments_per_floor_max"),
        )
    ]
    if spec.zones_rule is not None:
        steps.append(
            _rule(
                "structure_zones",
                "Число зон по высоте",
                spec.zones_rule,
                frozenset({_N, _E}),
                ("zones",),
                height=StepBinding("structure_vertical", "interfloor_length"),
            )
        )
    return steps


def _quantities(spec: VkSystemSpec) -> list[StepDef]:
    steps = [
        _rule(
            "quantity_end_segments",
            "Участки стояка ниже 1-го и выше верхнего этажа",
            spec.end_segments_rule,
            frozenset({_G, _E}),
            ("bottom", "top"),
        ),
        _rule(
            "quantity_supports",
            "Шаг креплений",
            SUPPORTS_RULE,
            frozenset({_N, _M, _E}),
            ("vertical", "horizontal"),
        ),
        _rule(
            "quantity_fittings",
            "Резервный метод фитингов трассы",
            FITTINGS_RULE,
            frozenset({_E}),
            ("per_meter",),
        ),
        _rule(
            "quantity_insulation",
            "Какие участки изолируются",
            spec.insulation_rule,
            frozenset({_N, _E, _M}),
            ("risers", "connections", "mains"),
        ),
        _rule(
            "quantity_penetrations",
            "Гильзы и огнезащита проходок",
            PENETRATIONS_RULE,
            frozenset({_N, _E}),
            ("sleeve", "firestop"),
        ),
        StepDef(
            step_key="tender_riser_reserve",
            title="Тендерный резерв длины стояка",
            outputs=("value",),
            rule_key=TENDER_RULE,
            allowed_rule_types=frozenset({CalcRuleType.TENDER_ASSUMPTION}),
            steps={"base": StepBinding("structure_vertical", "interfloor_length")},
            assumption=AssumptionSpec(base_input="base"),
        ),
    ]
    if spec.connection_rule is not None:
        steps.insert(
            1,
            _rule(
                "quantity_connection_length",
                "Длина этажного подключения",
                spec.connection_rule,
                frozenset({_E, _G}),
                ("length_min", "length_max"),
            ),
        )
    return steps


_I, _EN = CalcResultCategory.INTERMEDIATE, CalcResultCategory.ENGINEERING
RESULTS: Final[tuple[tuple[str, str, str, str, CalcResultCategory], ...]] = (
    ("structure.top_floor", "Верхний этаж с квартирами", "structure_floors", "top_floor", _EN),
    ("structure.served_floors", "Этажей с квартирами", "structure_floors", "served_floors", _EN),
    (
        "structure.apartments_total",
        "Квартир по квартирографии",
        "structure_floors",
        "apartments_total",
        _EN,
    ),
    (
        "structure.apartments_per_floor_max",
        "Квартир на этаже, наибольшее",
        "structure_floors",
        "apartments_per_floor_max",
        _I,
    ),
    (
        "structure.interfloor_length",
        "Межэтажный пролёт стояка",
        "structure_vertical",
        "interfloor_length",
        _EN,
    ),
    (
        "structure.slab_crossings",
        "Перекрытий на стояк между 1-м и верхним этажом",
        "structure_vertical",
        "slab_crossings",
        _EN,
    ),
    (
        "check.apartments_discrepancy",
        "Расхождение итога квартир",
        "demand_apartments_check",
        "discrepancy",
        _I,
    ),
    ("structure.shafts_max", "Шахт ВК на этаже, наибольшее", "structure_shafts", "shafts_max", _I),
    ("demand.premises_total", "Встроенных помещений названо", "demand_premises", "total", _I),
    (
        "demand.wet_rooms_total",
        "Помещений с водой вне квартир названо",
        "demand_wet_rooms",
        "total",
        _I,
    ),
    ("structure.risers_min", "Стояков не меньше", "structure_risers", "risers_min", _EN),
    ("structure.risers_max", "Стояков не больше", "structure_risers", "risers_max", _EN),
    ("structure.zones", "Зон по высоте", "structure_zones", "zones", _EN),
    ("demand.fixtures_observed", "Приборов по таблице", "demand_fixtures_observed", "total", _EN),
    (
        "demand.fixtures_by_rooms",
        "Точек водоотведения по правилу",
        "demand_fixtures_by_rooms",
        "fixtures",
        _EN,
    ),
    (
        "quantity.end_bottom",
        "Участок стояка ниже 1-го этажа",
        "quantity_end_segments",
        "bottom",
        _I,
    ),
    ("quantity.end_top", "Участок стояка выше верхнего этажа", "quantity_end_segments", "top", _I),
    (
        "quantity.connection_length_min",
        "Длина подключения не меньше",
        "quantity_connection_length",
        "length_min",
        _I,
    ),
    (
        "quantity.connection_length_max",
        "Длина подключения не больше",
        "quantity_connection_length",
        "length_max",
        _I,
    ),
    ("quantity.support_vertical", "Шаг креплений стояков", "quantity_supports", "vertical", _I),
    (
        "quantity.support_horizontal",
        "Шаг креплений горизонтали",
        "quantity_supports",
        "horizontal",
        _I,
    ),
    (
        "quantity.fittings_per_meter",
        "Фитингов трассы на метр",
        "quantity_fittings",
        "per_meter",
        _I,
    ),
    ("quantity.insulate_risers", "Изоляция стояков", "quantity_insulation", "risers", _I),
    (
        "quantity.insulate_connections",
        "Изоляция подключений",
        "quantity_insulation",
        "connections",
        _I,
    ),
    ("quantity.insulate_mains", "Изоляция магистралей", "quantity_insulation", "mains", _I),
    ("quantity.sleeve", "Гильзы проходок", "quantity_penetrations", "sleeve", _I),
    ("quantity.firestop", "Огнезащита проходок", "quantity_penetrations", "firestop", _I),
    (
        "tender.interfloor_reserved",
        "Пролёт стояка с тендерным резервом",
        "tender_riser_reserve",
        "value",
        _I,
    ),
)


def calculator_for(spec: VkSystemSpec) -> CalculatorDef:
    steps = (*_shared(), *_drain_points(spec), *_structure(spec), *_quantities(spec))
    present = {step.step_key for step in steps}
    return CalculatorDef(
        calculator_id=spec.calculator_id,
        version=spec.version,
        title=f"{spec.code} стадии П — {spec.title.lower()}",
        kind=CalcCalculatorKind.PRODUCTION,
        discipline=CalcDiscipline.VK,
        systems=(spec.code,),
        stage=CalcDocumentStage.P,
        scenarios=frozenset(CalcScenario),
        scope_fields=SCOPE_FIELDS,
        steps=steps,
        results=tuple(
            ResultDef(result_key=key, title=title, step_key=step, output=output, category=category)
            for key, title, step, output, category in RESULTS
            if step in present
        ),
        partial=True,
    )
