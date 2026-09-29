"""Инженерные решения, которые нужны калькуляторам ВК стадии П (PROMPT 06).

Это не правила, а их заявки: что за решение, где используется, какой контракт у реализации и что
остаётся неопределённым без утверждённой версии. Числа (сколько квартир на стояк, шаг креплений,
запас) здесь не живут — их вносит инженер в версию правила со ссылкой на источник. Проверенного
нормативного источника в репозитории нет, поэтому ни одно решение не утверждено кодом: без
версии правила в реестре пространства решение — SOURCE_REQUIRED.

Вычислительные примитивы (счёт этажей, сумма высот, итог квартир) здесь не перечислены: это
арифметика, а не инженерное решение (`engine/primitives.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.contracts.calc.enums import CalcRuleType

B1, T3, T4, K1 = "В1", "Т3", "Т4", "К1"
WATER: Final = (B1, T3, T4)


@dataclass(frozen=True, slots=True)
class RuleTerm:
    name: str
    unit: str | None
    meaning: str
    quantity: str | None = None
    """Ключ величины — для входов-результатов шагов и выходов."""


@dataclass(frozen=True)
class VkRuleNeed:
    rule_key: str
    title: str
    """Какое инженерное решение."""
    systems: tuple[str, ...]
    layer: str
    """A — потребность, B — структура, C — топология, D — количества, T — тендер."""
    rule_types: tuple[CalcRuleType, ...]
    """Допустимые типы версии; первый — ожидаемый."""
    implementation_key: str | None
    """Реализация в коде; пусто — методика ещё не реализована."""
    formula: str
    inputs: tuple[RuleTerm, ...]
    parameters: tuple[RuleTerm, ...]
    outputs: tuple[RuleTerm, ...]
    used_in: str
    blocks: str
    """Что остаётся неопределённым без утверждённой версии."""
    affects: tuple[str, ...]
    """Позиции паспорта, которые от решения зависят."""
    gate: bool
    """Нужно для содержательного инженерного гейта."""
    example: str
    """Синтетический пример — арифметика, а не норма."""


_E, _N, _G, _M, _T = (
    CalcRuleType.ENGINEERING,
    CalcRuleType.NORMATIVE,
    CalcRuleType.GEOMETRY,
    CalcRuleType.MANUFACTURER,
    CalcRuleType.TENDER_ASSUMPTION,
)
_RISER_OUT = (
    RuleTerm("risers_min", "riser", "Стояков не меньше", "riser.count_min"),
    RuleTerm("risers_max", "riser", "Стояков не больше", "riser.count_max"),
)
_RISER_IN = (
    RuleTerm(
        "apartments_per_floor",
        "apartment",
        "Наибольшее число квартир на обслуживаемом этаже (примитив квартирографии)",
        "apartments.per_floor_max",
    ),
)
_RISER_PARAMS = (
    RuleTerm("per_riser_min", "apartment", "Квартир на один стояк — нижняя граница"),
    RuleTerm("per_riser_max", "apartment", "Квартир на один стояк — верхняя граница"),
)


def _risers(key: str, system: str) -> VkRuleNeed:
    return VkRuleNeed(
        rule_key=key,
        title=f"Число стояков {system} по квартирам на этаже",
        systems=(system,),
        layer="B",
        rule_types=(_E,),
        implementation_key="vk.risers.count_range.v1",
        formula="стояков = ⌈квартир на этаже / квартир на стояк⌉ для обеих границ",
        inputs=_RISER_IN,
        parameters=_RISER_PARAMS,
        outputs=_RISER_OUT,
        used_in="шаг structure_risers калькулятора — если стояки не указаны в П",
        blocks="число стояков, вертикальные трубы, проходки, арматура стояков, этажные подключения",
        affects=("pipe.riser", "pipe.connection", "penetration.slab", "valve.riser_shutoff"),
        gate=True,
        example="8 кв. на этаже, 2–3 кв. на стояк → 3–4 стояка (синтетика)",
    )


_ENDS = (
    RuleTerm("bottom_length", "m", "Участок стояка ниже уровня 1-го этажа — до магистрали"),
    RuleTerm("top_length", "m", "Участок выше уровня верхнего этажа — до верхнего подключения"),
)
_ENDS_OUT = (
    RuleTerm("bottom", "m", "Нижний участок на стояк", "riser.bottom_length"),
    RuleTerm("top", "m", "Верхний участок на стояк", "riser.top_length"),
)
_CONNECTION = (
    RuleTerm("per_connection_min", "m", "Длина одного этажного подключения — нижняя граница"),
    RuleTerm("per_connection_max", "m", "Длина одного этажного подключения — верхняя граница"),
)
_CONNECTION_OUT = (
    RuleTerm("length_min", "m", "Длина подключения не меньше", "connection.length_min"),
    RuleTerm("length_max", "m", "Длина подключения не больше", "connection.length_max"),
)
_INSULATION = (
    RuleTerm("risers_flag", None, "Изолировать стояки: 1 — да, 0 — нет"),
    RuleTerm("connections_flag", None, "Изолировать этажные подключения: 1 — да, 0 — нет"),
    RuleTerm("mains_flag", None, "Изолировать магистрали: 1 — да, 0 — нет"),
)
_INSULATION_OUT = (
    RuleTerm("risers", None, "Стояки изолируются", "insulation.risers"),
    RuleTerm("connections", None, "Подключения изолируются", "insulation.connections"),
    RuleTerm("mains", None, "Магистрали изолируются", "insulation.mains"),
)


def _insulation(key: str, systems: tuple[str, ...], title: str) -> VkRuleNeed:
    return VkRuleNeed(
        rule_key=key,
        title=title,
        systems=systems,
        layer="D",
        rule_types=(_N, _E, _M),
        implementation_key="vk.insulation.scope.v1",
        formula="изоляция участка = длина участка, если признак участка 1; иначе 0",
        inputs=(),
        parameters=_INSULATION,
        outputs=_INSULATION_OUT,
        used_in="шаг quantity_insulation калькулятора",
        blocks="длина изоляции — без правила изоляция не равна длине трубы",
        affects=("insulation.riser", "insulation.connection", "insulation.main"),
        gate=False,
        example="стояки и магистрали — да, подключения — нет (синтетика)",
    )


def _topology(key: str, systems: tuple[str, ...]) -> VkRuleNeed:
    return VkRuleNeed(
        rule_key=key,
        title="Схема: ввод → магистраль → стояки → этажные подключения",
        systems=systems,
        layer="C",
        rule_types=(_E, _G),
        implementation_key="vk.topology.per_riser_floor.v1",
        formula="подключений = стояков × обслуживаемых этажей × подключений на стояк и этаж",
        inputs=(),
        parameters=(RuleTerm("per_floor", None, "Подключений на стояк на этаже"),),
        outputs=(
            RuleTerm("connections", None, "Подключений на стояк и этаж", "topology.per_floor"),
        ),
        used_in="роль TOPOLOGY синтезатора",
        blocks="связи графа, этажные подключения, ответвления, магистраль как элемент схемы",
        affects=("pipe.connection", "connection.floor", "fitting.branch"),
        gate=True,
        example="1 подключение на стояк на этаже (синтетика)",
    )


VK_RULE_NEEDS: Final[tuple[VkRuleNeed, ...]] = (
    _risers("vk.b1.risers.count_range", B1),
    _risers("vk.t3.risers.count_range", T3),
    _risers("vk.t4.risers.count_range", T4),
    _risers("vk.k1.risers.count_range", K1),
    VkRuleNeed(
        rule_key="vk.water.riser.end_segments",
        title="Участки стояка водопровода ниже 1-го этажа и выше верхнего",
        systems=WATER,
        layer="D",
        rule_types=(_G, _E),
        implementation_key="vk.riser.end_segments.v1",
        formula="длина стояка = межэтажный пролёт + нижний участок + верхний участок",
        inputs=(),
        parameters=_ENDS,
        outputs=_ENDS_OUT,
        used_in="шаг quantity_end_segments калькулятора",
        blocks="полная длина стояка: без правила подтверждается только межэтажная часть",
        affects=("pipe.riser",),
        gate=True,
        example="1,5 м ниже 1-го этажа и 0,5 м выше верхнего (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.k1.riser.end_segments",
        title="Участки стояка К1 ниже 1-го этажа и вытяжная часть выше верхнего",
        systems=(K1,),
        layer="D",
        rule_types=(_G, _E),
        implementation_key="vk.riser.end_segments.v1",
        formula="длина стояка = межэтажный пролёт + нижний участок + вытяжная часть",
        inputs=(),
        parameters=_ENDS,
        outputs=_ENDS_OUT,
        used_in="шаг quantity_end_segments калькулятора",
        blocks="полная длина стояка К1, вытяжная часть через кровлю",
        affects=("pipe.riser",),
        gate=True,
        example="1,0 м до выпуска и 3,5 м до выхода над кровлей (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.water.connection.length_range",
        title="Длина этажного подключения водопровода",
        systems=(B1, T3),
        layer="D",
        rule_types=(_E, _G),
        implementation_key="vk.connection.length_range.v1",
        formula="длина подключений = число подключений × длина одного (диапазон)",
        inputs=(),
        parameters=_CONNECTION,
        outputs=_CONNECTION_OUT,
        used_in="шаг quantity_connection_length калькулятора",
        blocks="длина этажных подключений: без правила — «не определено»",
        affects=("pipe.connection",),
        gate=True,
        example="2,0–3,5 м на подключение (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.k1.connection.length_range",
        title="Длина этажного отвода канализации",
        systems=(K1,),
        layer="D",
        rule_types=(_E, _G),
        implementation_key="vk.connection.length_range.v1",
        formula="длина отводов = число подключений × длина одного (диапазон); уклоны не задаются",
        inputs=(),
        parameters=_CONNECTION,
        outputs=_CONNECTION_OUT,
        used_in="шаг quantity_connection_length калькулятора",
        blocks="длина поэтажных отводов К1",
        affects=("pipe.connection",),
        gate=True,
        example="1,5–3,0 м на отвод (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.water.zones.by_height",
        title="Зонирование по высоте обслуживаемой части",
        systems=(B1, T3),
        layer="B",
        rule_types=(_N, _E),
        implementation_key="vk.zones.by_height.v1",
        formula="зон = ⌈высота обслуживаемой части / наибольшая высота зоны⌉",
        inputs=(
            RuleTerm(
                "height",
                "m",
                "Межэтажный пролёт от 1-го до верхнего обслуживаемого этажа (примитив)",
                "riser.interfloor_length",
            ),
        ),
        parameters=(RuleTerm("zone_height_max", "m", "Наибольшая высота одной зоны"),),
        outputs=(RuleTerm("zones", "zone", "Число зон", "system.zones"),),
        used_in="шаг structure_zones калькулятора — если зоны не заданы проектом",
        blocks="число зон; без правила и без зон в П зонирование не определено",
        affects=(),
        gate=True,
        example="69 м / 40 м → 2 зоны (синтетика, не норма)",
    ),
    VkRuleNeed(
        rule_key="vk.k1.fixtures.by_rooms",
        title="Точки водоотведения по санузлам и кухням",
        systems=(K1,),
        layer="A",
        rule_types=(_E, _N),
        implementation_key="vk.fixtures.by_rooms.v1",
        formula="приборов = санузлов × приборов на санузел + кухонь × приборов на кухню",
        inputs=(
            RuleTerm("bathrooms", "bathroom", "Санузлов всего (примитив)", "rooms.bathrooms"),
            RuleTerm("kitchens", "kitchen", "Кухонь всего (примитив)", "rooms.kitchens"),
        ),
        parameters=(
            RuleTerm("per_bathroom", None, "Приборов на санузел"),
            RuleTerm("per_kitchen", None, "Приборов на кухню"),
        ),
        outputs=(RuleTerm("fixtures", "fixture", "Точек водоотведения", "fixtures.total"),),
        used_in="шаг demand_fixtures_by_rooms — если приборы не перечислены в П",
        blocks="число точек водоотведения при отсутствии таблицы приборов",
        affects=("connection.drain_point",),
        gate=False,
        example="10 с/у × 3 + 8 кух. × 1 = 38 (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.supports.spacing",
        title="Шаг креплений трубопроводов",
        systems=(B1, T3, T4, K1),
        layer="D",
        rule_types=(_N, _M, _E),
        implementation_key="vk.supports.spacing.v1",
        formula="креплений = ⌈длина участка / шаг⌉ отдельно для стояков и горизонтали",
        inputs=(),
        parameters=(
            RuleTerm("vertical_spacing", "m", "Шаг креплений стояков"),
            RuleTerm("horizontal_spacing", "m", "Шаг креплений горизонтальных участков"),
        ),
        outputs=(
            RuleTerm("vertical", "m", "Шаг на стояках", "support.vertical_spacing"),
            RuleTerm("horizontal", "m", "Шаг на горизонтали", "support.horizontal_spacing"),
        ),
        used_in="шаг quantity_supports калькулятора",
        blocks="число креплений — без правила «не определено»",
        affects=("support.riser", "support.horizontal"),
        gate=False,
        example="3 м на стояках, 2 м на горизонтали (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.fittings.per_meter",
        title="Резервный метод фитингов трассы (на метр)",
        systems=(B1, T3, T4, K1),
        layer="D",
        rule_types=(_E,),
        implementation_key="vk.fittings.per_meter.v1",
        formula="фитингов трассы = ⌈подтверждённая длина × фитингов на метр⌉ — помечается FALLBACK",
        inputs=(),
        parameters=(RuleTerm("rate", None, "Фитингов на метр трассы для стадии П"),),
        outputs=(RuleTerm("per_meter", None, "Фитингов на метр", "fitting.per_meter"),),
        used_in="шаг quantity_fittings калькулятора",
        blocks="фитинги трассы, которых нет в топологии (отводы, муфты)",
        affects=("fitting.route_fallback",),
        gate=False,
        example="0,5 фитинга на метр (синтетика)",
    ),
    _insulation("vk.cold.insulation.scope", (B1,), "Изоляция холодного водопровода"),
    _insulation("vk.hot.insulation.scope", (T3, T4), "Изоляция горячего водоснабжения"),
    _insulation("vk.k1.insulation.scope", (K1,), "Изоляция канализации"),
    VkRuleNeed(
        rule_key="vk.penetrations.treatment",
        title="Гильзы и огнезащита проходок через перекрытия",
        systems=(B1, T3, T4, K1),
        layer="D",
        rule_types=(_N, _E),
        implementation_key="vk.penetrations.treatment.v1",
        formula="гильз = проходок, если признак 1; огнезащиты — так же, отдельно",
        inputs=(),
        parameters=(
            RuleTerm("sleeve_flag", None, "Проходка в гильзе: 1 — да, 0 — нет"),
            RuleTerm("firestop_flag", None, "Огнезащита проходки: 1 — да, 0 — нет"),
        ),
        outputs=(
            RuleTerm("sleeve", None, "Гильзы нужны", "penetration.sleeve"),
            RuleTerm("firestop", None, "Огнезащита нужна", "penetration.firestop"),
        ),
        used_in="шаг quantity_penetrations калькулятора",
        blocks="гильзы и огнезащита; проходки считаются топологией и без правила",
        affects=("sleeve.slab", "firestop.slab"),
        gate=False,
        example="гильза — да, огнезащита — да (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.tender.riser_length_reserve",
        title="Тендерный резерв длины стояка",
        systems=(B1, T3, T4, K1),
        layer="T",
        rule_types=(_T,),
        implementation_key="vk.tender.length_reserve.v1",
        formula="резерв = стояков × резерв на стояк; хранится отдельно от базы",
        inputs=(
            RuleTerm("base", "m", "Межэтажный пролёт стояка (примитив)", "riser.interfloor_length"),
        ),
        parameters=(RuleTerm("reserve_length", "m", "Резерв длины на один стояк"),),
        outputs=(RuleTerm("value", "m", "Пролёт с резервом", "riser.interfloor_reserved"),),
        used_in="шаг допущения tender_riser_reserve — только TENDER_SAFE",
        blocks="ничего: без допущения TENDER_SAFE = EXPECTED",
        affects=("pipe.riser",),
        gate=False,
        example="+1 м на стояк на неучтённые отступы (синтетика, решение владельца)",
    ),
    _topology("vk.water.topology.scheme", (B1, T3)),
    _topology("vk.t4.topology.scheme", (T4,)),
    _topology("vk.k1.topology.scheme", (K1,)),
    VkRuleNeed(
        rule_key="vk.water.valves.riser_shutoff",
        title="Запорная арматура на стояках",
        systems=WATER,
        layer="C",
        rule_types=(_N, _E),
        implementation_key="vk.topology.per_riser.v1",
        formula="кранов = стояков × кранов на стояк — по узлам графа",
        inputs=(),
        parameters=(RuleTerm("per_riser", None, "Запорных элементов на стояк"),),
        outputs=(RuleTerm("count", None, "На стояк", "valve.per_riser"),),
        used_in="роль TOPOLOGY синтезатора — узлы арматуры у стояков",
        blocks="запорная арматура стояков",
        affects=("valve.riser_shutoff",),
        gate=False,
        example="1 кран у основания стояка (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.t4.valves.balancing",
        title="Балансировочная арматура циркуляционных стояков",
        systems=(T4,),
        layer="C",
        rule_types=(_E, _M),
        implementation_key="vk.topology.per_riser.v1",
        formula="балансировочных клапанов = циркуляционных стояков × клапанов на стояк",
        inputs=(),
        parameters=(RuleTerm("per_riser", None, "Балансировочных клапанов на стояк"),),
        outputs=(RuleTerm("count", None, "На стояк", "valve.balancing_per_riser"),),
        used_in="роль TOPOLOGY синтезатора Т4",
        blocks="балансировочная арматура Т4",
        affects=("valve.balancing",),
        gate=False,
        example="1 клапан на циркуляционный стояк (синтетика)",
    ),
    VkRuleNeed(
        rule_key="vk.water.demand.flow_check",
        title="Контрольный расчёт расходов по приборам",
        systems=(B1, T3),
        layer="A",
        rule_types=(_N,),
        implementation_key=None,
        formula="вероятностный метод по нормативному документу — не реализован",
        inputs=(),
        parameters=(),
        outputs=(),
        used_in="сверка расходов документа с независимым расчётом",
        blocks="контрольное значение расхода; расход документа используется как факт",
        affects=(),
        gate=False,
        example="—",
    ),
    VkRuleNeed(
        rule_key="vk.main.coarse_routing",
        title="Грубая трассировка магистрали",
        systems=(B1, T3, T4, K1),
        layer="D",
        rule_types=(_E, _G),
        implementation_key=None,
        formula="утверждённая методика по геометрии этажа — не реализована; «коридор × 0,8» "
        "старого портала не используется",
        inputs=(),
        parameters=(),
        outputs=(),
        used_in="длина магистрали, если её нет в документе или обмере",
        blocks="длина магистрали и зависящие от неё изоляция, крепления, фитинги трассы",
        affects=("pipe.main",),
        # На гейте длина магистрали берётся из документа или обмера (gate-06-engineer-review).
        gate=False,
        example="—",
    ),
)

NEEDS_BY_KEY: Final = {item.rule_key: item for item in VK_RULE_NEEDS}


def needs_for(system_code: str) -> tuple[VkRuleNeed, ...]:
    return tuple(item for item in VK_RULE_NEEDS if system_code in item.systems)
