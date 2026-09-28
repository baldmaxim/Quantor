"""Описание системы ВК для рабочего калькулятора и синтезатора (PROMPT 06).

Четыре системы — четыре отдельных версионируемых калькулятора и синтезатора. Общие функции
(этажность, квартирография, вертикальная структура, повторяемость) — одни шаги-примитивы для
всех; различия — в правилах, источнике и в том, что система делает в проекте.

Назначение (`function`) — не вывод из обозначения: калькулятор Т3 считает подающий трубопровод
горячей воды и запускается, только если документация проекта так и называет Т3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

Source = Literal["INLET", "HOT_SOURCE", "OUTLET", "NONE"]


@dataclass(frozen=True)
class VkSystemSpec:
    code: str
    slug: str
    title: str
    function: str
    """Назначение по документации, которое калькулятор ожидает: значение `system.function`."""
    calculator_id: str
    synthesizer_id: str
    risers_rule: str
    end_segments_rule: str
    connection_rule: str | None
    zones_rule: str | None
    insulation_rule: str
    topology_rule: str
    riser_valves_rule: str | None
    balancing_rule: str | None
    drain_points: bool
    source: Source
    version: int = 1


B1: Final = VkSystemSpec(
    code="В1",
    slug="b1",
    title="Хозяйственно-питьевой водопровод",
    function="COLD_WATER",
    calculator_id="vk.b1.stage_p",
    synthesizer_id="vk.b1.structure",
    risers_rule="vk.b1.risers.count_range",
    end_segments_rule="vk.water.riser.end_segments",
    connection_rule="vk.water.connection.length_range",
    zones_rule="vk.water.zones.by_height",
    insulation_rule="vk.cold.insulation.scope",
    topology_rule="vk.water.topology.scheme",
    riser_valves_rule="vk.water.valves.riser_shutoff",
    balancing_rule=None,
    drain_points=False,
    source="INLET",
)
T3: Final = VkSystemSpec(
    code="Т3",
    slug="t3",
    title="Горячее водоснабжение, подающий",
    function="HOT_WATER_SUPPLY",
    calculator_id="vk.t3.stage_p",
    synthesizer_id="vk.t3.structure",
    risers_rule="vk.t3.risers.count_range",
    end_segments_rule="vk.water.riser.end_segments",
    connection_rule="vk.water.connection.length_range",
    zones_rule="vk.water.zones.by_height",
    insulation_rule="vk.hot.insulation.scope",
    topology_rule="vk.water.topology.scheme",
    riser_valves_rule="vk.water.valves.riser_shutoff",
    balancing_rule=None,
    drain_points=False,
    source="HOT_SOURCE",
)
T4: Final = VkSystemSpec(
    code="Т4",
    slug="t4",
    title="Горячее водоснабжение, циркуляционный",
    function="HOT_WATER_CIRCULATION",
    calculator_id="vk.t4.stage_p",
    synthesizer_id="vk.t4.structure",
    risers_rule="vk.t4.risers.count_range",
    end_segments_rule="vk.water.riser.end_segments",
    connection_rule=None,
    zones_rule=None,
    insulation_rule="vk.hot.insulation.scope",
    topology_rule="vk.t4.topology.scheme",
    riser_valves_rule="vk.water.valves.riser_shutoff",
    balancing_rule="vk.t4.valves.balancing",
    drain_points=False,
    source="NONE",
)
K1: Final = VkSystemSpec(
    code="К1",
    slug="k1",
    title="Бытовая канализация",
    function="DOMESTIC_SEWER",
    calculator_id="vk.k1.stage_p",
    synthesizer_id="vk.k1.structure",
    risers_rule="vk.k1.risers.count_range",
    end_segments_rule="vk.k1.riser.end_segments",
    connection_rule="vk.k1.connection.length_range",
    zones_rule=None,
    insulation_rule="vk.k1.insulation.scope",
    topology_rule="vk.k1.topology.scheme",
    riser_valves_rule=None,
    balancing_rule=None,
    drain_points=True,
    source="OUTLET",
)

VK_SPECS: Final = (B1, T3, T4, K1)
SPECS_BY_CODE: Final = {spec.code: spec for spec in VK_SPECS}
