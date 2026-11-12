"""Двери шахт лифтов: разрывы стен у лифтового холла получают высоту из «Вопросов к документации».

Движок CAD не пишет высоту безымянных разрывов (`kind = "gap"`): в объёме конструкций они не
учтены (`opening_no_data`), в 3D этажа пропущены (`door_height_missing`). Разрыв - дверь шахты
лифта, если с одной стороны от него лежит зона типа `lift_hall`, а с другой нет никакой зоны
помещения (квартиры или МОП): за дверью шахты - шахта, её зоной не размечают. Высоту даёт
принятый ответ вопроса `LIFT_DOOR_HEIGHT` (`document` - `observed`, ввод человека - `manual`);
собственная высота разрыва из walls.json сильнее ответа. Функция чистая и применяется один раз
до расчёта: объём конструкций, 3D этажа и ВОР получают одни и те же разрывы с высотой.
Модель чисел не выдаёт.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from app.contracts.cad_constructions import WallsDocument, WallsOpening
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services.cad_constructions import (
    PartitionContext,
    PartitionZone,
    _in_ring,
    _point_segment_distance,
)

LIFT_HALL_TYPE: Final = "lift_hall"
# Отступ от грани стены, на котором проверяется, что лежит по сторонам разрыва, и допуск касания
# контура лифтового холла: контуры зон идут по внутренним граням стен, неточно.
LIFT_SIDE_REACH_MM: Final = 150.0

WARNING_LIFT_DOOR_HEIGHT_UNKNOWN: Final = "lift_door_height_unknown"
MESSAGE_LIFT_DOOR_HEIGHT_UNKNOWN: Final = (
    "Высота проёма двери шахты лифта не подтверждена в «Вопросах к документации»: разрывы у "
    "лифтового холла остаются без высоты"
)


@dataclass(frozen=True, slots=True)
class LiftOpenings:
    """Документ с проставленной высотой лифтовых разрывов и предупреждения `(код, текст)`."""

    document: WallsDocument
    warnings: list[tuple[str, str]] = field(default_factory=list)
    lift_gap_ids: frozenset[str] = frozenset()


def _near_ring(point: tuple[float, float], ring: Sequence[Sequence[float]], reach: float) -> bool:
    """Точка внутри кольца или не дальше `reach` от его контура."""
    if len(ring) < 3:
        return False
    shell = [list(p) for p in ring]
    if _in_ring(point, shell):
        return True
    n = len(shell)
    return any(
        _point_segment_distance(
            point,
            (shell[i][0], shell[i][1]),
            (shell[(i + 1) % n][0], shell[(i + 1) % n][1]),
        )
        <= reach
        for i in range(n)
    )


def _in_any_room(point: tuple[float, float], zones: Sequence[PartitionZone]) -> bool:
    return any(len(zone.shell) >= 3 and _in_ring(point, zone.shell) for zone in zones)


def is_lift_door_gap(
    opening: WallsOpening, direction: Sequence[float] | None, zones: Sequence[PartitionZone]
) -> bool:
    """Разрыв - дверь шахты лифта: лифтовый холл с одной стороны, никакой зоны с другой."""
    if opening.kind != "gap" or direction is None or len(direction) < 2 or len(opening.center) < 2:
        return False
    dx, dy = float(direction[0]), float(direction[1])
    length = math.hypot(dx, dy)
    if length == 0.0:
        return False
    nx, ny = -dy / length, dx / length
    offset = (opening.thickness_mm or 0.0) / 2 + LIFT_SIDE_REACH_MM
    cx, cy = float(opening.center[0]), float(opening.center[1])
    sides = ((cx + nx * offset, cy + ny * offset), (cx - nx * offset, cy - ny * offset))
    halls = [zone for zone in zones if zone.room_type == LIFT_HALL_TYPE]
    if not halls:
        return False
    for hall_side, other_side in (sides, sides[::-1]):
        if any(_near_ring(hall_side, zone.shell, LIFT_SIDE_REACH_MM) for zone in halls) and (
            not _in_any_room(other_side, zones)
        ):
            return True
    return False


def apply_lift_door_heights(
    document: WallsDocument, extras: WallsFloorExtras, partition: PartitionContext | None
) -> LiftOpenings:
    """Лифтовые разрывы получают высоту: своя из walls.json, иначе принятый ответ проекта.

    Без зон листа лифтовых разрывов нет - документ возвращается как есть. Предупреждение
    `lift_door_height_unknown` - лифтовые разрывы найдены, а высоты у них нет.
    """
    if partition is None or not partition.zones:
        return LiftOpenings(document)
    direction_by_id = {item.id: item.direction for item in extras.openings}
    lift_ids = frozenset(
        opening.id
        for opening in document.openings
        if is_lift_door_gap(opening, direction_by_id.get(opening.id), partition.zones)
    )
    if not lift_ids:
        return LiftOpenings(document)
    answer = partition.lift_door_height
    openings: list[WallsOpening] = []
    unknown = False
    for opening in document.openings:
        if opening.id not in lift_ids or opening.opening_height_mm is not None:
            openings.append(opening)
            continue
        if answer is None:
            unknown = True
            openings.append(opening)
            continue
        openings.append(
            opening.model_copy(
                update={
                    "opening_height_mm": answer.height_mm,
                    "opening_height_status": answer.source,
                }
            )
        )
    warnings = (
        [(WARNING_LIFT_DOOR_HEIGHT_UNKNOWN, MESSAGE_LIFT_DOOR_HEIGHT_UNKNOWN)] if unknown else []
    )
    return LiftOpenings(document.model_copy(update={"openings": openings}), warnings, lift_ids)
