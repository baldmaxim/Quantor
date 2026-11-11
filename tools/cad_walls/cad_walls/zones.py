"""Зоны помещений листа (необязательный вход): контуры квартир и МОП в мм DXF для контура плиты.

Файл — список `[{"kind": "...", "shell": [[x, y], ...]}]`. Берутся только `room_apartment` и
`room_mop`; зоны дверей и прочее пропускаются. Повреждённый контур — ошибка входа, а не молчаливый
пропуск: плита от него зависит.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Polygon

from cad_walls.errors import WallsError

ZONE_KINDS = ("room_apartment", "room_mop")
MIN_ZONE_POINTS = 3


def _bad(message: str) -> WallsError:
    return WallsError("zones_invalid", message)


def _ring(raw: object, index: int) -> list[tuple[float, float]]:
    if not isinstance(raw, list) or len(raw) < MIN_ZONE_POINTS:
        raise _bad(f"зона {index}: контур короче трёх точек")
    ring: list[tuple[float, float]] = []
    for point in raw:
        if (
            not isinstance(point, list | tuple)
            or len(point) != 2
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in point)
        ):
            raise _bad(f"зона {index}: точка контура не пара чисел")
        ring.append((float(point[0]), float(point[1])))
    return ring


def read_zones(path: Path) -> list[Polygon]:
    """Полигоны зон помещений; пустой результат допустим."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _bad(f"не читается файл зон: {exc}") from exc
    if not isinstance(raw, list):
        raise _bad("файл зон: ожидался список")
    out: list[Polygon] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise _bad(f"зона {index}: ожидался объект")
        if item.get("kind") not in ZONE_KINDS:
            continue
        poly = Polygon(_ring(item.get("shell"), index))
        if not poly.is_valid:
            poly = poly.buffer(0)
        if isinstance(poly, Polygon) and not poly.is_empty:
            out.append(poly)
    return out
