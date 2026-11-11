"""Плита перекрытия как конструкция листа: вход расчёта из walls.json и решений по отверстиям.

Модуль только читает `WallsFloorExtras` и ключи отверстий из `cad_floor3d`; величины считает
`cad_constructions.compute_sheet`. Отверстие включено, если решения человека нет или оно
`enabled=true` (то же правило, что в 3D-виде этажа, ADR-0039).
"""

from __future__ import annotations

from collections.abc import Mapping

from app.contracts.cad_floor3d import WallsFloorExtras
from app.services.cad_constructions import SLAB_ID, SlabInput
from app.services.cad_floor3d import hole_keys


def slab_input(extras: WallsFloorExtras, decisions: Mapping[str, bool]) -> SlabInput | None:
    """Плита листа с включёнными отверстиями; в файле нет плиты (старый файл, нет стен) — `None`.

    Идентификатор плиты в разборе не читается (`id` из walls.json игнорируется): адрес плиты в
    параметрах конструкций всегда `slab`.
    """
    slab = extras.slab
    if slab is None:
        return None
    keys = hole_keys(extras)
    holes = [
        (hole.shell, hole.area_mm2)
        for key, hole in zip(keys, extras.slab_holes, strict=True)
        if decisions.get(key) is not False
    ]
    return SlabInput(id=SLAB_ID, shell=slab.shell, area_mm2=slab.area_mm2, holes=holes)
