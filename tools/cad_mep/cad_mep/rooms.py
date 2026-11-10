"""Помещения, шахты, МОП, квартиры (шаги 2–3 ТЗ прототипа)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

from cad_mep.dxfin import Door
from cad_mep.labels import Labels, RoomLabel, ShaftLabel
from cad_mep.params import Params
from cad_mep.raster import (
    BoolArr,
    FloatArr,
    Grid,
    IntArr,
    closing,
    comp_stats,
    dist_to_background,
    label,
    lookup_mask,
    make_grid,
    nearest_true,
    raster_polys,
)


@dataclass
class Comp:
    id: int
    area_m2: float
    centroid: tuple[float, float]
    bbox: tuple[float, float, float, float]
    room_labels: list[RoomLabel] = field(default_factory=list)
    shaft_labels: list[ShaftLabel] = field(default_factory=list)
    kind: str = "unlabeled"  # room | mop | shaft | unlabeled | tiny
    apt: int | None = None  # индекс квартиры (по графу дверей)


@dataclass
class Shaft:
    id: str
    comp: int | None
    systems: list[str]
    label_pt: tuple[float, float]
    centroid: tuple[float, float]
    contour: Polygon | None
    area_m2: float
    contour_status: str  # found | not_found
    place: str = ""  # mop | apartment | unknown
    mop_exit: tuple[float, float] | None = None  # клетка МОП у шахты
    apt: int | None = None


@dataclass
class Apartment:
    idx: int
    number: str
    section: str
    k: int | None
    comps: list[int]
    entry_door: Door | None = None
    entry_mop_comp: int | None = None
    entry_apt_comp: int | None = None
    entry_note: str = ""
    detached: list[list[int]] = field(default_factory=list)  # группы помещений без двери


@dataclass
class DoorLink:
    door: Door
    a: int | None
    b: int | None


@dataclass
class Model:
    gr: Grid
    walls: BoolArr
    foot: BoolArr
    lab: IntArr
    comps: dict[int, Comp]
    shafts: list[Shaft]
    apts: dict[int, Apartment]
    door_links: list[DoorLink]
    hull: Polygon
    edist: FloatArr  # расстояние до внешнего контура здания, мм
    notes: list[str] = field(default_factory=list)
    virtual_openings: list[dict[str, object]] = field(default_factory=list)


def build_hull(
    wall_polys: list[Polygon], bbox: tuple[float, float, float, float], pad: float
) -> Polygon:
    """Контур здания — выпуклая оболочка заливок стен внутри рамки плана (без марок разрезов)."""
    x0, y0, x1, y1 = bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad
    inb = [
        p
        for p in wall_polys
        if p.bounds[0] > x0 and p.bounds[2] < x1 and p.bounds[1] > y0 and p.bounds[3] < y1
    ]
    if not inb:
        return Polygon()
    hull = unary_union(inb).convex_hull
    if not isinstance(hull, Polygon):
        return Polygon()
    return hull


def build(
    wall_polys: list[Polygon],
    labels: Labels,
    doors: list[Door],
    bbox: tuple[float, float, float, float],
    extent: tuple[float, float],
    params: Params,
) -> Model:
    step = params.num("grid_room_mm")
    gr = make_grid(step, extent[0], extent[1])
    hull = build_hull(wall_polys, bbox, params.num("plan_bbox_pad_mm"))
    facade = params.num("facade_band_mm")
    foot = raster_polys(gr, [hull])
    r_edge = int(np.ceil((facade + params.num("device_offset_mm")) / step)) + 3
    edist = dist_to_background(foot, r_edge) * step
    inner = foot & (edist > facade)
    walls = raster_polys(gr, wall_polys)
    barriers = raster_polys(gr, [d.barrier(params.num("door_pad_mm")) for d in doors])
    closed = closing(walls | barriers)
    free = inner & ~closed
    lab, n = label(free)
    st = comp_stats(lab, n)
    areas = st.counts * step * step / 1e6
    comps: dict[int, Comp] = {}
    comp_min = params.num("comp_min_area_m2")
    for i in range(1, n + 1):
        if areas[i - 1] <= comp_min:
            continue
        comps[i] = Comp(
            i,
            float(areas[i - 1]),
            ((float(st.cx[i - 1]) + 0.5) * step, (float(st.cy[i - 1]) + 0.5) * step),
            (
                float(st.x0[i - 1]) * step,
                float(st.y0[i - 1]) * step,
                (float(st.x1[i - 1]) + 1) * step,
                (float(st.y1[i - 1]) + 1) * step,
            ),
        )
    snap = params.num("room_label_snap_mm")
    near = nearest_true(lab > 0, int(np.ceil(snap / step)))

    def comp_at(x: float, y: float) -> int | None:
        iy, ix = gr.ij(x, y)
        if not gr.inside(iy, ix):
            return None
        if lab[iy, ix]:
            return int(lab[iy, ix])
        if near.dist[iy, ix] * step <= snap:
            return int(lab[near.iy[iy, ix], near.ix[iy, ix]])
        return None

    for rl in labels.rooms:
        hit = comp_at(*rl.word.c)
        if hit in comps:
            comps[hit].room_labels.append(rl)
    shafts = _link_shafts(labels, comps, lab, gr, params)
    for c in comps.values():
        if c.room_labels:
            c.kind = "mop" if any(r.mop for r in c.room_labels) else "room"
        elif c.shaft_labels:
            c.kind = "shaft"
        elif c.area_m2 < params.num("min_room_area_m2"):
            c.kind = "tiny"
    return Model(gr, walls, foot, lab, comps, shafts, {}, [], hull, edist)


def _link_shafts(
    labels: Labels, comps: dict[int, Comp], lab: IntArr, gr: Grid, params: Params
) -> list[Shaft]:
    """Подпись шахты -> ближайший малый замкнутый контур."""
    step = gr.step
    max_area = params.num("shaft_max_area_m2")
    r = int(params.num("shaft_label_snap_mm") // step)
    shafts: list[Shaft] = []
    for k, sl in enumerate(labels.shafts):
        x, y = sl.word.c
        iy, ix = gr.ij(x, y)
        cid: int | None = None
        if gr.inside(iy, ix):
            here = int(lab[iy, ix])
            if here and here in comps and comps[here].area_m2 <= max_area:
                cid = here
            else:
                y0, x0 = max(iy - r, 0), max(ix - r, 0)
                win = lab[y0 : iy + r + 1, x0 : ix + r + 1]
                best: int | None = None
                bd = 1e18
                for cc in np.unique(win).tolist():
                    if cc == 0 or cc not in comps or comps[cc].area_m2 > max_area:
                        continue
                    ys, xs = np.nonzero(win == cc)
                    d = float(np.min(np.hypot(xs + x0 - ix, ys + y0 - iy))) * step
                    if d < bd:
                        best, bd = int(cc), d
                cid = best
        if cid is not None:
            ys, xs = np.nonzero(lab == cid)
            pts = [
                (xs.min() * step, ys.min() * step),
                (xs.max() * step + step, ys.min() * step),
                (xs.max() * step + step, ys.max() * step + step),
                (xs.min() * step, ys.max() * step + step),
            ]
            cont = Polygon([(float(a), float(b)) for a, b in pts])
            shafts.append(
                Shaft(
                    f"S{k:02d}",
                    cid,
                    sl.systems,
                    sl.word.c,
                    comps[cid].centroid,
                    cont,
                    comps[cid].area_m2,
                    "found",
                )
            )
            comps[cid].shaft_labels.append(sl)
        else:
            shafts.append(
                Shaft(f"S{k:02d}", None, sl.systems, sl.word.c, sl.word.c, None, 0.0, "not_found")
            )
    return shafts


def door_links(m: Model, doors: list[Door]) -> list[DoorLink]:
    """Каждая дверь: помещения по обе стороны (шаг по нормали 100..1050 мм до свободной клетки)."""
    out: list[DoorLink] = []
    gr = m.gr
    for d in doors:
        nx, ny = d.normal()
        mx, my = d.mid
        sides: list[int | None] = []
        for sgn in (1, -1):
            cid: int | None = None
            for dist in range(100, 1100, 50):
                iy, ix = gr.ij(mx + sgn * nx * dist, my + sgn * ny * dist)
                if gr.inside(iy, ix) and m.lab[iy, ix]:
                    cid = int(m.lab[iy, ix])
                    break
            sides.append(cid)
        out.append(DoorLink(d, sides[0], sides[1]))
    m.door_links = out
    return out


def _components(nodes: set[int], edges: list[tuple[int, int]]) -> list[set[int]]:
    parent = {n: n for n in nodes}

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[int, set[int]] = {}
    for n in sorted(nodes):
        groups.setdefault(find(n), set()).add(n)
    return [groups[k] for k in sorted(groups)]


def build_apartments(m: Model, labels: Labels, params: Params) -> None:
    min_area = params.num("min_room_area_m2")
    nodes = {
        c.id for c in m.comps.values() if c.kind in ("room", "unlabeled") and c.area_m2 >= min_area
    }
    edges = [
        (lk.a, lk.b)
        for lk in m.door_links
        if lk.a in nodes
        and lk.b in nodes
        and lk.a != lk.b
        and lk.a is not None
        and lk.b is not None
    ]
    groups = _components(nodes, edges)
    merged_notes: list[str] = []
    detached: list[tuple[frozenset[int], set[int]]] = []

    def key(g: set[int]) -> frozenset[tuple[str, int]]:
        return frozenset(
            (rl.section, rl.apt_index)
            for c in g
            for rl in m.comps[c].room_labels
            if rl.apt_index is not None
        )

    i = 0
    while i < len(groups):
        j = i + 1
        while j < len(groups):
            if len(key(groups[i])) == 1 and key(groups[i]) == key(groups[j]):
                merged_notes.append(
                    f"квартира {sorted(key(groups[i]))}: компоненты {sorted(groups[j])} "
                    "присоединены по марке (нет двери между)"
                )
                detached.append((frozenset(groups[j]), groups[i]))
                groups[i] |= groups.pop(j)
            else:
                j += 1
        i += 1
    m.notes.extend(merged_notes)
    apts: dict[int, Apartment] = {}
    n = 0
    ordered = sorted(groups, key=lambda s: min(m.comps[c].centroid[0] for c in s))
    for comp_set in ordered:
        if not any(m.comps[c].room_labels for c in comp_set):
            continue
        n += 1
        ks = [
            (rl.section, rl.apt_index)
            for c in comp_set
            for rl in m.comps[c].room_labels
            if rl.apt_index is not None
        ]
        best = max(sorted(set(ks)), key=ks.count) if ks else None
        number = f"К-{n}"
        section, k = (best[0], best[1]) if best else ("", None)
        if best:
            number = _apt_number(section, best[1], labels.apt_numbers)
        apts[n] = Apartment(n, number, section, k, sorted(comp_set))
        apts[n].detached = [sorted(d) for d, _host in detached if d <= comp_set]
        for c in comp_set:
            m.comps[c].apt = n
    m.apts = apts
    mop_ids = {c.id for c in m.comps.values() if c.kind == "mop"}
    for lk in m.door_links:
        for x, y in ((lk.a, lk.b), (lk.b, lk.a)):
            if x in mop_ids and y is not None and y in m.comps and m.comps[y].apt:
                ap = m.apts[int(m.comps[y].apt or 0)]
                if ap.entry_door is None:
                    ap.entry_door, ap.entry_mop_comp, ap.entry_apt_comp = lk.door, x, y
                else:
                    ap.entry_note += f" доп.дверь {lk.door.id}"


def _apt_number(section: str, k: int, numbers: list[str]) -> str:
    """Номер квартиры: единственная подпись «Кв …» вида <секция>…<k>, иначе «Кв секция-k»."""
    cand = [
        t for t in numbers if t.startswith(section) and t.endswith(str(k)) and len(t) > len(section)
    ]
    if len(cand) == 1:
        return f"Кв {cand[0]}"
    return f"Кв {section}-{k}"


def classify_shafts(m: Model, params: Params) -> None:
    """Шахта выходит в МОП, если МОП ближе квартиры и не дальше shaft_mop_adj_mm."""
    step = m.gr.step
    adj = params.num("shaft_mop_adj_mm")
    apt_adj = params.num("shaft_apt_adj_mm")
    mop_mask = lookup_mask(m.lab, [c.id for c in m.comps.values() if c.kind == "mop"])
    table = np.zeros(int(m.lab.max()) + 1, dtype=np.int16)
    for c in m.comps.values():
        if c.apt:
            table[c.id] = c.apt
    apt_lab = table[m.lab]
    near_mop = nearest_true(mop_mask, int(np.ceil(adj / step)))
    near_apt = nearest_true(apt_lab > 0, int(np.ceil(apt_adj / step)))
    for sh in m.shafts:
        if sh.comp is None:
            sh.place = "unknown"
            continue
        ys, xs = np.nonzero(m.lab == sh.comp)
        i = int(np.argmin(near_mop.dist[ys, xs]))
        j = int(np.argmin(near_apt.dist[ys, xs]))
        dm = float(near_mop.dist[ys[i], xs[i]]) * step
        da = float(near_apt.dist[ys[j], xs[j]]) * step
        if dm <= adj and dm <= da:
            sh.place = "mop"
            sh.mop_exit = m.gr.xy(int(near_mop.iy[ys[i], xs[i]]), int(near_mop.ix[ys[i], xs[i]]))
        elif da <= apt_adj:
            sh.place = "apartment"
            sh.apt = int(apt_lab[near_apt.iy[ys[j], xs[j]], near_apt.ix[ys[j], xs[j]]])
        else:
            sh.place = "unknown"
