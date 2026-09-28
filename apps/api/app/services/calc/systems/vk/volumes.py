"""Слой D: ожидаемые количества системы ВК из графа и результатов расчёта (PROMPT 06).

Позиции собираются только из того, что уже определено: узлов и связей графа (с кратностью и
повторяемостью), атрибутов на экземпляр и результатов утверждённых правил. Ни одного
инженерного числа слой не вводит. Порядок позиций детерминирован — ключи стабильны для сверки
с ВОР Заказчика в PROMPT 09, но самой сверки здесь нет.
"""

from __future__ import annotations

from app.contracts.calc.passport import CalcExpectedQuantityBody
from app.services.calc.systems.vk import volumes_items as items
from app.services.calc.systems.vk import volumes_pipes as pipes
from app.services.calc.systems.vk import volumes_rules as by_rules
from app.services.calc.systems.vk.volume_base import VolumeContext, VolumeInputs


def generate(inputs: VolumeInputs) -> list[CalcExpectedQuantityBody]:
    context = VolumeContext(inputs)
    riser = pipes.risers(context)
    connection = pipes.connections(context)
    main = pipes.main(context)
    outlet = pipes.outlets(context)
    segments = [riser, connection, main] + ([] if outlet is None else [outlet])
    pipes.total(context, segments)
    known = [item for item in segments if item.value is not None]
    length = None
    for item in known:
        length = (
            item.value
            if length is None or item.value is None
            else (
                length[0] + item.value[0],
                length[1] + item.value[1],
            )
        )
    items.topology_fittings(context, riser, connection)
    by_rules.fallback_fittings(context, length, all(item.complete for item in segments))
    items.valves(context)
    items.penetrations(context, riser)
    by_rules.insulation(context, {item.key: item for item in segments})
    by_rules.supports(context, riser, [connection, main])
    items.equipment_and_connections(context, connection)
    return context.rows
