"""Рост областей помещений на тонком растре и карманы откосов входных дверей."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon

from cad_mep import zones_const as zc
from cad_mep.dxfin import Door
from cad_mep.raster import BoolArr, Grid, label, raster_polys
from cad_mep.zones_raster import Field, Window


def grow(fld: Field, limit_mm: float) -> int:
    """Области растут от стартовых масок на свободные клетки одновременно (геодезически).

    Возвращает число сделанных шагов (шаг — одна клетка тонкого растра).
    """
    g = fld.g
    width = g.shape[1]
    flat = g.reshape(-1)
    free = g == 0
    near_free = np.zeros_like(free)
    near_free[1:] |= free[:-1]
    near_free[:-1] |= free[1:]
    near_free[:, 1:] |= free[:, :-1]
    near_free[:, :-1] |= free[:, 1:]
    front = np.flatnonzero(((g > 0) & near_free).ravel())
    del free, near_free
    dirs = [1, -1, width, -width]
    steps = 0
    for it in range(int(limit_mm / fld.f)):
        cand_parts = []
        label_parts = []
        for d in dirs[it % 4 :] + dirs[: it % 4]:
            nbr = front + d
            ok = flat[nbr] == 0
            cand_parts.append(nbr[ok])
            label_parts.append(flat[front[ok]])
        cand = np.concatenate(cand_parts)
        if len(cand) == 0:
            break
        flat[cand] = np.concatenate(label_parts)
        front = np.unique(cand)
        steps += 1
    return steps


@dataclass
class Pocket:
    """Проём входной двери: зона откоса, помещения по сторонам и квартиры этих сторон."""

    door: Door
    win: Window
    zone: BoolArr
    sides: list[int]  # метка области с каждой стороны (0 — нет)
    apts: list[int | None]
    normal: tuple[float, float]


def collect_pockets(
    fld: Field, doors: list[Door], label_apt: Callable[[int], int | None]
) -> list[Pocket]:
    """Зона проёма и стороны каждой двери; только двери, у которых одна из сторон в квартире."""
    f = fld.f
    gi = fld.gi
    out: list[Pocket] = []
    for d in doors:
        (ax, ay), (bx, by) = d.a, d.b
        length = math.hypot(bx - ax, by - ay) or 1.0
        ux, uy = (bx - ax) / length, (by - ay) / length
        nx, ny = -uy, ux
        ext, half = zc.DOOR_POCKET_EXT_MM, zc.DOOR_POCKET_HALF_MM
        pts = [
            (ax - ux * ext + nx * half, ay - uy * ext + ny * half),
            (bx + ux * ext + nx * half, by + uy * ext + ny * half),
            (bx + ux * ext - nx * half, by + uy * ext - ny * half),
            (ax - ux * ext - nx * half, ay - uy * ext - ny * half),
        ]
        wx0 = int(min(p[0] for p in pts) // f) - 2
        wx1 = int(max(p[0] for p in pts) // f) + 3
        wy0 = int(min(p[1] for p in pts) // f) - 2
        wy1 = int(max(p[1] for p in pts) // f) + 3
        shifted = Polygon([(x - wx0 * f, y - wy0 * f) for x, y in pts])
        zone = raster_polys(Grid(f, wx1 - wx0, wy1 - wy0), [shifted])
        mx, my = d.mid
        sides: list[int] = []
        for sgn in (1, -1):
            got = 0
            for dist in range(
                zc.DOOR_POCKET_SIDE_MIN_MM, zc.DOOR_POCKET_SIDE_MAX_MM, zc.DOOR_POCKET_SIDE_STEP_MM
            ):
                ix, iy = int((mx + sgn * nx * dist) // f), int((my + sgn * ny * dist) // f)
                if 0 <= iy < fld.ny and 0 <= ix < fld.nx and gi[iy, ix] > 0:
                    got = int(gi[iy, ix])
                    break
            sides.append(got)
        apts = [label_apt(v) if v else None for v in sides]
        if any(a is not None for a in apts):
            out.append(Pocket(d, (wx0, wy0, wx1, wy1), zone, sides, apts, (nx, ny)))
    return out


def assign_pockets(fld: Field, pockets: list[Pocket]) -> int:
    """Свободные карманы откоса у входной двери, не достигнутые ростом, — стороне квартиры.

    Возвращает число отданных карманов.
    """
    f = fld.f
    given = 0
    for pk in pockets:
        wx0, wy0, _wx1, _wy1 = pk.win
        door = pk.door
        cx, cy = int(door.mid[0] // f), int(door.mid[1] // f)
        r = int(zc.DOOR_POCKET_WINDOW_MM / f)
        ax0, ay0 = max(cx - r, 0), max(cy - r, 0)
        sub = fld.gi[ay0 : min(cy + r, fld.ny), ax0 : min(cx + r, fld.nx)]
        free = sub == 0
        lab_, n = label(free)
        if n == 0:
            continue
        zone = np.zeros(sub.shape, dtype=np.bool_)
        by0, bx0 = wy0 - ay0, wx0 - ax0
        ys0, xs0 = max(by0, 0), max(bx0, 0)
        ye, xe = (
            min(by0 + pk.zone.shape[0], sub.shape[0]),
            min(bx0 + pk.zone.shape[1], sub.shape[1]),
        )
        if ye <= ys0 or xe <= xs0:
            continue
        zone[ys0:ye, xs0:xe] = pk.zone[ys0 - by0 : ye - by0, xs0 - bx0 : xe - bx0]
        nx, ny = pk.normal
        for i in np.unique(lab_[zone & free]):
            if i == 0:
                continue
            comp = lab_ == i
            if comp[0].any() or comp[-1].any() or comp[:, 0].any() or comp[:, -1].any():
                continue  # выходит за окно — не карман
            if comp.sum() * f * f / 1e6 > zc.DOOR_POCKET_MAX_M2:
                continue
            yy, xx = np.nonzero(comp)
            gx, gy = (xx.mean() + ax0 + 0.5) * f, (yy.mean() + ay0 + 0.5) * f
            side = 0 if ((gx - door.mid[0]) * nx + (gy - door.mid[1]) * ny) > 0 else 1
            if pk.apts[side] is None or not pk.sides[side]:
                continue
            sub[comp] = pk.sides[side]
            given += 1
    return given
