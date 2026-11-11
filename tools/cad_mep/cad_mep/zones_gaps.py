"""Щели в проёмах между зоной МОП и соседней зоной: только замечания, контуры не меняются."""

from __future__ import annotations

from collections.abc import Callable

from shapely.geometry import Polygon
from shapely.ops import unary_union

from cad_mep import zones_const as zc
from cad_mep.zones_grow import Pocket


def _strip(pk: Pocket) -> Polygon:
    """Полоса вдоль проёма (от петли до кончика полотна) и GAP_HALF_MM по сторонам от линии."""
    (ax, ay), (bx, by) = pk.door.a, pk.door.b
    nx, ny = pk.normal
    h = zc.GAP_HALF_MM
    return Polygon(
        [
            (ax + nx * h, ay + ny * h),
            (bx + nx * h, by + ny * h),
            (bx - nx * h, by - ny * h),
            (ax - nx * h, ay - ny * h),
        ]
    )


def gap_notes(
    pockets: list[Pocket],
    polys: dict[int, Polygon],
    mop_ids: set[int],
    marks_of: Callable[[int], str],
) -> dict[int, list[str]]:
    """Замечания для зон МОП: щель в проёме между ней и соседней зоной (>= GAP_NOTE_M2).

    Щелью считается часть полосы проёма, не занятая ни одной из двух зон по сторонам двери.
    Закрывает ли её граница по полотну двери (правило 06, разд. 2) — решает человек.
    """
    out: dict[int, list[str]] = {}
    for pk in pockets:
        a, b = pk.sides
        if not (a and b and a != b and a in polys and b in polys):
            continue
        if a not in mop_ids and b not in mop_ids:
            continue
        gap = _strip(pk).difference(unary_union([polys[a], polys[b]])).area / 1e6
        if gap < zc.GAP_NOTE_M2:
            continue
        for sid, other in ((a, b), (b, a)):
            if sid in mop_ids:
                out.setdefault(sid, []).append(
                    f"щель в проёме до зоны {marks_of(other)}: {gap:.2f} м²"
                )
    return out
