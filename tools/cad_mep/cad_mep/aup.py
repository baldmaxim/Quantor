"""Ветка АУП по внеквартирным помещениям: трасса до дальних точек и покрытие площади."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np
import shapely

from cad_mep.labels import ExplRow
from cad_mep.params import Params
from cad_mep.raster import BoolArr, label, nearest_true
from cad_mep.rooms import Model
from cad_mep.route import DIRS, RouteGrid, node_path, spt


@dataclass(frozen=True)
class Region:
    """Помещения МОП одной связной области, по которым идёт ветка."""

    comp: int
    rooms: list[str]
    names: list[str]
    area_m2: float  # по экспликации
    mask: BoolArr  # клетки сетки трассировки


def _flood(inside: BoolArr, start: tuple[int, int], cells: int) -> BoolArr:
    """Ближайшие к start клетки области (по пути внутри неё) — не больше cells штук."""
    out: BoolArr = np.zeros(inside.shape, dtype=np.bool_)
    out[start] = True
    queue = deque([start])
    left = cells - 1
    while queue and left > 0:
        iy, ix = queue.popleft()
        for dy, dx in DIRS:
            ny, nx = iy + dy, ix + dx
            if (
                left > 0
                and 0 <= ny < inside.shape[0]
                and 0 <= nx < inside.shape[1]
                and inside[ny, nx]
                and not out[ny, nx]
            ):
                out[ny, nx] = True
                queue.append((ny, nx))
                left -= 1
    return out


def _territory(
    rg: RouteGrid, inside: BoolArr, at: tuple[float, float], cells: int, clear: float, tol: float
) -> BoolArr:
    """Клетки помещения вокруг его марки — в пределах площади из экспликации.

    Область на плане может включать чужие пространства (лифтовые шахты без дверных блоков).
    Помещение — часть области, которая остаётся связной с маркой, если отойти от стен на t:
    t растёт от clear, пока площадь части не уложится в площадь экспликации с допуском tol —
    так отсекаются пространства за проёмами. Не уложилась — ближайшие к марке клетки на эту площадь.
    """
    step = rg.step
    ys, xs = np.nonzero(inside)
    k = int(np.argmin(np.hypot((xs + 0.5) * step - at[0], (ys + 0.5) * step - at[1])))
    home = (int(ys[k]), int(xs[k]))  # клетка области, ближайшая к марке
    limit = cells * (1 + tol)
    t = clear
    while True:
        core = inside & (rg.d >= t)
        if not core.any():
            return _flood(inside, home, cells)
        parts, _count = label(core)
        cy, cx = np.nonzero(core)
        j = int(np.argmin(np.hypot(cy - home[0], cx - home[1])))
        r = math.ceil(t / step)
        part: BoolArr = parts == parts[cy[j], cx[j]]
        room: BoolArr = inside & (nearest_true(part, r).dist <= r)
        if room[home] and int(room.sum()) <= limit:
            return room
        t += step


def regions(rg: RouteGrid, m: Model, expl: dict[str, ExplRow], params: Params) -> list[Region]:
    """Помещения МОП для ветки АУП: название начинается со слова из aup_room_words."""
    words = params.texts("aup_room_words")
    clear = params.num("aup_end_clearance_mm")
    tol = params.num("room_area_match_tol")
    cell_m2 = rg.step * rg.step / 1e6
    out: list[Region] = []
    for cid in sorted(c.id for c in m.comps.values() if c.kind == "mop"):
        inside: BoolArr = rg.comp_of == cid
        mask: BoolArr = np.zeros(inside.shape, dtype=np.bool_)
        rows: dict[str, ExplRow] = {}
        for rl in m.comps[cid].room_labels:
            row = expl.get(rl.room_id)
            if (
                row is None
                or rl.room_id in rows
                or not inside.any()
                or not any(row.name.lower().startswith(w) for w in words)
            ):
                continue
            rows[rl.room_id] = row
            cells = math.ceil(row.area_m2 / cell_m2)
            mask |= _territory(rg, inside, rl.word.c, cells, clear, tol)
        if rows:
            ids = sorted(rows)
            area = round(sum(r.area_m2 for r in rows.values()), 2)
            out.append(Region(cid, ids, [rows[i].name for i in ids], area, mask))
    return out


def _mark(rg: RouteGrid, line: BoolArr, cells: list[int]) -> None:
    ij = (rg.xy[cells] // rg.step).astype(np.int64)
    line[ij[:, 1], ij[:, 0]] = True


def _far(rg: RouteGrid, line: BoolArr, room: BoolArr, radius: float) -> BoolArr:
    """Клетки помещения дальше radius от ветки."""
    r = math.ceil(radius / rg.step)
    out: BoolArr = room & (nearest_true(line, r).dist * rg.step > radius)
    return out


def extend(rg: RouteGrid, source: int, areas: list[Region], params: Params) -> list[list[int]]:
    """Пути ветки от узла шахты: пока в помещении есть точка дальше радиуса — путь до самой дальней.

    Каждый путь начинается на уже построенной ветке, так что вместе они образуют дерево.
    """
    radius = params.num("aup_cover_radius_mm")
    clear = params.num("aup_end_clearance_mm")
    line: BoolArr = np.zeros(rg.pas.shape, dtype=np.bool_)
    tree = {source}
    _mark(rg, line, [source])
    paths: list[list[int]] = []
    for area in areas:
        room = area.mask & (rg.d >= clear)
        while True:
            ys, xs = np.nonzero(_far(rg, line, room, radius))
            if len(ys) == 0:
                break
            ly, lx = np.nonzero(line)
            built = shapely.multipoints(np.c_[lx, ly].astype(np.float64))
            gap = shapely.distance(built, shapely.points(np.c_[xs, ys].astype(np.float64)))
            k = int(np.lexsort((xs, ys, -gap))[0])  # самая дальняя; при равенстве — по порядку
            target = int(rg.idx[ys[k], xs[k]])
            path = node_path(spt(rg, sorted(tree), [target]), target)
            if not path:
                break  # помещение недостижимо от шахты: покрытие покажет это
            tree.update(path)
            _mark(rg, line, path)
            paths.append(path)
    return paths


def coverage(
    rg: RouteGrid, areas: list[Region], paths: list[list[int]], params: Params
) -> list[dict[str, object]]:
    """Доля площади каждого помещения не дальше aup_cover_radius_mm от ветки."""
    radius = params.num("aup_cover_radius_mm")
    line: BoolArr = np.zeros(rg.pas.shape, dtype=np.bool_)
    for path in paths:
        _mark(rg, line, path)
    out: list[dict[str, object]] = []
    for area in areas:
        total = int(area.mask.sum())
        far = int(_far(rg, line, area.mask, radius).sum()) if line.any() else total
        out.append(
            {
                "comp": area.comp,
                "rooms": list(area.rooms),
                "names": list(area.names),
                "area_m2": area.area_m2,
                "covered_share": round(1 - far / total, 3) if total else 0.0,
                "radius_mm": radius,
            }
        )
    return out
