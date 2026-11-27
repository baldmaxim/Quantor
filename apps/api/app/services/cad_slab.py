"""Плита перекрытия как конструкция листа: вход расчёта из walls.json и решений по отверстиям.

Модуль только читает `WallsFloorExtras` и ключи отверстий из `cad_floor3d`; величины считает
`cad_constructions.compute_sheet`. Отверстие включено, если решения человека нет или оно
`enabled=true` (то же правило, что в 3D-виде этажа, ADR-0039).

У листа из двух корпусов плита состоит из нескольких частей (cad_walls v1.27): по конструкции на
часть, площадь каждой - своя; итог по листу - сумма частей.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.contracts.cad_floor3d import WallsFloorExtras
from app.services.cad_constructions import SLAB_ID, SlabInput, slab_ids, slab_main_index
from app.services.cad_facade_windows import point_in_ring
from app.services.cad_floor3d import hole_keys, ring_centroid

Ring = list[list[float]]
Hole = tuple[Ring, float]


def slab_inputs(extras: WallsFloorExtras, decisions: Mapping[str, bool]) -> list[SlabInput]:
    """Части плиты листа с включёнными отверстиями; в файле нет плиты (старый файл) — пусто.

    Идентификатор плиты в разборе не читается (`id` из walls.json игнорируется): адрес основной
    (самой большой) части в параметрах конструкций всегда `slab`, остальных - `slab-N` по позиции
    части в `parts`. Основная часть идёт первой. Отверстие относится к части, внутри которой его
    центроид; не попало ни в одну - к основной. Файл без `parts` - одна плита на весь контур.
    """
    slab = extras.slab
    if slab is None:
        return []
    keys = hole_keys(extras)
    holes: list[Hole] = [
        (hole.shell, hole.area_mm2)
        for key, hole in zip(keys, extras.slab_holes, strict=True)
        if decisions.get(key) is not False
    ]
    if len(slab.parts) <= 1:
        return [SlabInput(id=SLAB_ID, shell=slab.shell, area_mm2=slab.area_mm2, holes=holes)]
    ids = slab_ids(slab)
    main = slab_main_index(slab)
    by_part: list[list[Hole]] = [[] for _ in slab.parts]
    for hole in holes:
        cx, cy = ring_centroid(hole[0])
        owner = next(
            (i for i, part in enumerate(slab.parts) if point_in_ring(cx, cy, part.shell)), main
        )
        by_part[owner].append(hole)
    order = [main, *(i for i in range(len(slab.parts)) if i != main)]
    return [
        SlabInput(
            id=ids[i],
            shell=slab.parts[i].shell,
            area_mm2=slab.parts[i].area_mm2,
            holes=by_part[i],
        )
        for i in order
    ]
