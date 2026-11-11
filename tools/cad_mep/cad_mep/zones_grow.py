"""Рост областей помещений на тонком растре и карманы откосов входных дверей."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from shapely.geometry import Polygon

from cad_mep import zones_const as zc
from cad_mep.dxfin import Door
from cad_mep.raster import BoolArr, Grid, IntArr, label, nearest_true, raster_polys
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
    """Проём двери: зона откоса, помещения по сторонам и признак «размечается зоной» сторон."""

    door: Door
    win: Window
    zone: BoolArr
    sides: list[int]  # метка области с каждой стороны (0 — нет)
    zoned: list[bool]
    normal: tuple[float, float]


def collect_pockets(
    fld: Field, doors: list[Door], label_zoned: Callable[[int], bool]
) -> list[Pocket]:
    """Зона проёма и стороны каждой двери; только двери, у которых одна из сторон — зона.

    Зона — помещение квартиры или МОП: проём между двумя МОП и между МОП и квартирой делится так же,
    как проём входной двери квартиры."""
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
        zoned = [bool(v) and label_zoned(v) for v in sides]
        if any(zoned):
            out.append(Pocket(d, (wx0, wy0, wx1, wy1), zone, sides, zoned, (nx, ny)))
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
            if not pk.zoned[side] or not pk.sides[side]:
                continue
            sub[comp] = pk.sides[side]
            given += 1
    return given


@dataclass(frozen=True)
class Absorbed:
    """Присоединённый к зоне карман: метка зоны, площадь (с мягкими клетками), центр в мм."""

    zone: int
    area_m2: float
    centre: tuple[float, float]


def _dilate4(m: BoolArr) -> BoolArr:
    """Расширение маски на клетку по 4-связности."""
    out = m.copy()
    out[1:] |= m[:-1]
    out[:-1] |= m[1:]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    return out


def _soft_dist(start: BoolArr, soft: BoolArr, limit: int) -> IntArr:
    """Расстояние от start по мягким клеткам: 1 — соседняя, 0 — не достигнута за limit клеток."""
    dist: IntArr = np.zeros(start.shape, dtype=np.int32)
    seen = start.copy()
    front = start
    for step in range(1, limit + 1):
        new = _dilate4(front) & soft & ~seen
        if not new.any():
            break
        dist[new] = step
        seen |= new
        front = new
    return dist


def absorb_residual(fld: Field) -> list[Absorbed]:
    """Мелкие непокрытые карманы, отделённые от зоны только тонкими штрихами, — этой зоне.

    Граница зоны проходит по граням заливок стен, а не по тонким обводкам: «твёрдое» — заливки,
    «мягкое» — тёмные штрихи без заливки. Свободный карман (4-связная область клеток без метки)
    площадью не больше RESIDUAL_MAX_M2 присоединяется к зоне, с которой у него самый длинный
    контакт (клетки зоны, достижимые через не более RESIDUAL_SOFT_CELLS мягких клеток), если
    контакт не короче RESIDUAL_CONTACT_MIN_MM и он не ближе RESIDUAL_EXTERIOR_MM к наружной
    области (свободные клетки, 4-связные с краем растра; оконные проёмы фасада). Вместе с
    карманом зоне отходят мягкие клетки на путях контакта; заливки не трогаются.
    Решения принимаются по снимку исходной разметки, порядок — по возрастанию
    метки кармана, при равном контакте берётся меньшая метка зоны.
    """
    f = fld.f
    gi = fld.gi
    ny, nx = gi.shape
    lab, n = label(gi == 0)
    if n == 0:
        return []
    counts = np.bincount(lab.ravel(), minlength=n + 1)
    small = counts <= int(zc.RESIDUAL_MAX_M2 * 1e6 / (f * f))
    small[0] = False
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    outer_ids = np.zeros(n + 1, dtype=np.bool_)  # наружная область — по снимку до присоединений
    outer_ids[edge] = True
    outer_ids[0] = False
    small &= ~outer_ids
    outer: BoolArr = outer_ids[lab]
    ext_cells = int(zc.RESIDUAL_EXTERIOR_MM / f)
    flat = lab.ravel()
    cells = np.flatnonzero(small[flat])
    if len(cells) == 0:
        return []
    cells = cells[np.argsort(flat[cells], kind="stable")]
    groups = np.split(cells, np.flatnonzero(np.diff(flat[cells])) + 1)
    zones0 = gi.copy()
    soft_all = (gi < 0) & ~fld.fill
    reach = zc.RESIDUAL_SOFT_CELLS
    pad = reach + 1
    min_cells = zc.RESIDUAL_CONTACT_MIN_MM / f
    out: list[Absorbed] = []
    for grp in groups:
        ys, xs = np.divmod(grp, nx)
        y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, ny)
        x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, nx)
        comp: BoolArr = np.zeros((y1 - y0, x1 - x0), dtype=np.bool_)
        comp[ys - y0, xs - x0] = True
        soft = soft_all[y0:y1, x0:x1] & (gi[y0:y1, x0:x1] < 0)
        near = zones0[y0:y1, x0:x1]
        from_comp = _soft_dist(comp, soft, reach)
        touched = _dilate4(comp | (from_comp > 0)) & (near > 0)
        if not touched.any():
            continue
        ids, contact = np.unique(near[touched], return_counts=True)
        pick = int(np.argmax(contact))  # равный контакт — меньшая метка зоны (ids по возрастанию)
        if contact[pick] < min_cells:
            continue
        best = int(ids[pick])
        ey0, ey1 = max(int(ys.min()) - ext_cells - 1, 0), min(int(ys.max()) + ext_cells + 2, ny)
        ex0, ex1 = max(int(xs.min()) - ext_cells - 1, 0), min(int(xs.max()) + ext_cells + 2, nx)
        ext_win = outer[ey0:ey1, ex0:ex1]
        if ext_win.any():
            dist = nearest_true(ext_win, ext_cells).dist
            if float(dist[ys - ey0, xs - ex0].min()) * f < zc.RESIDUAL_EXTERIOR_MM:
                continue
        to_zone = _soft_dist(near == best, soft, reach)
        between = (from_comp > 0) & (to_zone > 0) & (from_comp + to_zone - 1 <= reach)
        take = comp | between
        sub = gi[y0:y1, x0:x1]
        sub[take] = best
        out.append(
            Absorbed(
                best,
                float(take.sum()) * f * f / 1e6,
                ((float(xs.mean()) + 0.5) * f, (float(ys.mean()) + 0.5) * f),
            )
        )
    return out


def absorb_enclosed(fld: Field, zones: set[int]) -> list[Absorbed]:
    """Просветы внутри зоны: свободная область, ограждённая тонкими штрихами и одной зоной.

    Просвет — связная (4-связность) группа свободных клеток и мягких клеток (тёмные штрихи без
    заливки), площадью свободных клеток до ENCLOSED_MAX_M2. Его границы с областями — только
    клетки одной зоны. Присоединяется зоне, если он нигде не примыкает к заливке (рамка отметки
    уровня или подписи, отдельно стоящая колонна: зона не держит отверстий) либо зона примыкает
    к нему с противоположных сторон (контакт охватывает не меньше ENCLOSED_SPAN_RATIO размаха
    просвета по обеим осям: полоса коридора между двумя выносными линиями размеров, режущими его
    насквозь). Шахта или ниша, открытая к зоне одним краем (проём, дверь лифта), остаётся.
    Присоединяются свободные и мягкие клетки группы; заливки не трогаются. Только зонам из `zones`
    (метки областей МОП): квартирные зоны этим шагом не меняются.
    """
    f = fld.f
    gi = fld.gi
    ny, nx = gi.shape
    free = gi == 0
    soft = (gi < 0) & ~fld.fill
    lab, n = label(free | soft)
    if n == 0:
        return []
    free_counts = np.bincount(lab[free].ravel(), minlength=n + 1)
    cand = (free_counts > 0) & (free_counts <= int(zc.ENCLOSED_MAX_M2 * 1e6 / (f * f)))
    cand[0] = False
    flat = lab.ravel()
    cells = np.flatnonzero(cand[flat])
    if len(cells) == 0:
        return []
    cells = cells[np.argsort(flat[cells], kind="stable")]
    groups = np.split(cells, np.flatnonzero(np.diff(flat[cells])) + 1)
    out: list[Absorbed] = []
    for grp in groups:
        ys, xs = np.divmod(grp, nx)
        y0, y1 = max(int(ys.min()) - 1, 0), min(int(ys.max()) + 2, ny)
        x0, x1 = max(int(xs.min()) - 1, 0), min(int(xs.max()) + 2, nx)
        comp: BoolArr = np.zeros((y1 - y0, x1 - x0), dtype=np.bool_)
        comp[ys - y0, xs - x0] = True
        sub = gi[y0:y1, x0:x1]
        ring = _dilate4(comp) & ~comp
        ids = np.unique(sub[ring & (sub > 0)])
        if len(ids) != 1 or int(ids[0]) not in zones:
            continue
        touches_fill = bool((ring & fld.fill[y0:y1, x0:x1]).any())
        if touches_fill:
            cy, cx = np.nonzero(ring & (sub > 0))
            span_y, span_x = int(cy.max() - cy.min()) + 1, int(cx.max() - cx.min()) + 1
            width, height = int(xs.max() - xs.min()) + 1, int(ys.max() - ys.min()) + 1
            if span_x < zc.ENCLOSED_SPAN_RATIO * width or span_y < zc.ENCLOSED_SPAN_RATIO * height:
                continue
        sub[comp] = int(ids[0])
        out.append(
            Absorbed(
                int(ids[0]),
                float(comp.sum()) * f * f / 1e6,
                ((float(xs.mean()) + 0.5) * f, (float(ys.mean()) + 0.5) * f),
            )
        )
    return out


def residual_notes(absorbed: list[Absorbed]) -> dict[int, str]:
    """Замечание на каждую зону, к которой присоединены карманы."""
    acc: dict[int, list[float]] = {}
    for a in absorbed:
        acc.setdefault(a.zone, []).append(a.area_m2)
    return {
        z: f"дорощено до заливок: {len(v)} карманов, {sum(v):.2f} м²"
        for z, v in sorted(acc.items())
    }


def enclosed_notes(absorbed: list[Absorbed]) -> dict[int, str]:
    """Замечание на каждую зону, к которой присоединены просветы."""
    acc: dict[int, list[float]] = {}
    for a in absorbed:
        acc.setdefault(a.zone, []).append(a.area_m2)
    return {
        z: f"закрыто просветов внутри зоны: {len(v)}, {sum(v):.2f} м²"
        for z, v in sorted(acc.items())
    }
