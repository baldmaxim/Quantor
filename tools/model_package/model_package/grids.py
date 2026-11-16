"""Сведение осей в grids.json (раздел 5).

Повторяющиеся по этажам и файлам сетки сводятся по паре `(tag, dir)`: остаётся первая ось,
расхождение концов больше 10 мм (с учётом перестановки концов) - предупреждение.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from .ifc_source import RawAxis

GRID_TOLERANCE_MM = 10.0


def _gap(a: RawAxis, b: RawAxis) -> float:
    direct = max(math.dist(a.p0, b.p0), math.dist(a.p1, b.p1))
    swapped = max(math.dist(a.p0, b.p1), math.dist(a.p1, b.p0))
    return min(direct, swapped)


def merge_axes(axes: Iterable[RawAxis]) -> tuple[list[dict[str, object]], list[str]]:
    """Сведённые оси (порядок первого появления) и предупреждения о расхождениях."""
    kept: dict[tuple[str, str], RawAxis] = {}
    worst: dict[tuple[str, str], float] = {}
    empty = 0
    for axis in axes:
        if not axis.tag:
            empty += 1
            continue
        pair = (axis.tag, axis.dir)
        if pair not in kept:
            kept[pair] = axis
            continue
        gap = _gap(kept[pair], axis)
        if gap > GRID_TOLERANCE_MM:
            worst[pair] = max(worst.get(pair, 0.0), gap)
    warnings = [
        f"ось {tag} ({d}): концы расходятся между сетками до {gap:.0f} мм"
        for (tag, d), gap in worst.items()
    ]
    if empty:
        warnings.append(f"{empty} осей без подписи пропущено")
    rows: list[dict[str, object]] = [
        {"tag": a.tag, "dir": a.dir, "p0": list(a.p0), "p1": list(a.p1)} for a in kept.values()
    ]
    return rows, warnings
