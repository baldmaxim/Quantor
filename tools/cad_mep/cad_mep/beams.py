"""Квартира: пучок лучей от коллектора — один отвод на комнату, остальные приборы — перемычки."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from cad_mep.bundle import Bundle
from cad_mep.heatdev import Device, HeatRoom
from cad_mep.lanes import Layout, fan, jog_shift
from cad_mep.result import Line3D, NodeMark, Pt
from cad_mep.rooms import Apartment
from cad_mep.route import node_path, spt

if TYPE_CHECKING:
    from cad_mep.heating import Feed
    from cad_mep.systems import Planner

LAYERS = ("M-OV-T1", "M-OV-T2")
INF = math.inf


@dataclass
class Item:
    """Путь комнаты: луч до первого прибора и цепочка перемычек к остальным."""

    room: HeatRoom
    cells: list[int]
    devices: list[tuple[Device, int]]  # (прибор, индекс узла в cells)


def _hop(
    pl: Planner,
    bundle: Bundle,
    end: int,
    rest: list[Device],
    comps: set[int],
    block: dict[int, float],
) -> tuple[list[int], Device] | None:
    """Перемычка от конца цепочки до ближайшего по пути прибора: по комнате, иначе по квартире."""
    for in_room in (True, False):
        if in_room:
            outside = ~np.isin(pl.node_comp, list(comps))
            extra = dict.fromkeys(np.nonzero(outside)[0].tolist(), INF)
        else:
            extra = dict(block)
        for cell in bundle.along:
            extra[cell] = INF
        tree = spt(pl.rg, [end], [d.node for d in rest], True, None, extra)
        found = [d for d in rest if math.isfinite(tree[d.node])]
        if found:
            best = min(found, key=lambda d: (tree[d.node], d.node))
            seg = node_path(tree, best.node)
            bundle.add(seg)
            return seg, best
    return None


def _pieces(
    pts: list[Pt], idx: dict[int, int], marks: list[int], xys: list[Pt], radius: float
) -> list[list[Pt]]:
    """Ломаная полосы, разрезанная по узлам приборов; разрез далеко от узла сводится на узел."""
    out: list[list[Pt]] = []
    start = 0
    head: list[Pt] = []
    for m, xy in zip(marks[:-1], xys[:-1], strict=True):
        cut = idx[m]
        piece = [*head, *pts[start : cut + 1]]
        far = math.hypot(pts[cut][0] - xy[0], pts[cut][1] - xy[1]) > radius
        head = [xy] if far else []
        if far:
            piece.append(xy)
        out.append(piece)
        start = cut
    out.append([*head, *pts[start:]])
    return out


def _feed_lane(pl: Planner, feed: Feed, lay: Layout, lane: int) -> list[Pt]:
    """Подводка квартиры: коридорная полоса до двери, затем место в пучке квартиры."""
    cells, je = feed.cells, feed.edge
    n = len(cells)
    corr = feed.layout.offs[feed.idx][lane]
    offs = list(corr[:je])
    apt_off = lay.offs[0][1 - lane]  # у пути квартиры ход обратный: левая полоса — правая
    offs += [-apt_off[n - 2 - k] for k in range(je, n - 1)]
    jog: dict[int, float] = {}
    for k in range(je + 1, n - 1):
        jog[k] = -jog_shift(apt_off[n - 2 - k], apt_off[n - 1 - k])
    pts, idx = feed.layout.polyline(cells, offs, (), jog)
    snap = feed.layout.snap
    pts, idx = fan(
        pts,
        idx,
        feed.root_xy,
        feed.layout.start_fan,
        pl.node_xy(cells[-1]),
        False,
        abs(offs[0]) > snap,
    )
    back, _ = fan(
        pts[::-1],
        {},
        pl.node_xy(cells[-1]),
        lay.start_fan,
        feed.root_xy,
        False,
        abs(offs[-1]) > snap,
    )
    return back[::-1]


def apartment(pl: Planner, ap: Apartment, rooms: list[HeatRoom], feed: Feed | None) -> None:
    """Подводка в квартире, лучи и перемычки: полосы T1/T2 одним пучком от коллектора."""
    rg, res, p = pl.rg, pl.res, pl.p
    col, col_xy = pl.coll[ap.idx]
    info = pl.apt_info(ap)
    res.nodes.append(
        NodeMark(
            "M-NODE", "collector", col_xy, pl.z_heat, ap.idx, "heating", pl.coll_room.get(ap.idx)
        )
    )
    seed = feed.cells[feed.edge :][::-1] if feed is not None else None
    bundle = Bundle(rg, col, p, seed)
    block = pl.foreign(ap.idx)
    devs = [d for r in rooms for d in r.devices]
    t0 = spt(rg, [col], [d.node for d in devs]) if devs else None
    lost: list[Device] = []
    ranked: list[tuple[HeatRoom, list[Device]]] = []
    for room in rooms:
        ok = [d for d in room.devices if t0 is not None and math.isfinite(t0[d.node])]
        lost += [d for d in room.devices if d not in ok]
        if ok and t0 is not None:
            ranked.append((room, sorted(ok, key=lambda d: (t0[d.node], d.node))))
    ranked.sort(key=lambda rd: (-(t0[rd[1][0].node] if t0 is not None else 0.0), rd[0].room_id))
    items: list[Item] = []
    for room, ordered in ranked:
        first = ordered[0]
        cells = bundle.reach(first.node, (), block)
        if not cells:
            lost += ordered
            continue
        item = Item(room, cells, [(first, len(cells) - 1)])
        comps = {int(pl.node_comp[d.node]) for d in ordered}
        rest, end = ordered[1:], first.node
        while rest:
            hop = _hop(pl, bundle, end, rest, comps, block)
            if hop is None:
                lost += rest
                break
            seg, dev = hop
            item.cells += seg[1:]
            item.devices.append((dev, len(item.cells) - 1))
            rest.remove(dev)
            end = dev.node
        items.append(item)
    if lost:
        pl.issue(
            "heat_beam_unreachable",
            f"{ap.number}: луч отопления — путь до {len(lost)} приборов не найден",
            ap,
        )
    lost_nodes = {d.node for d in lost}
    for room in rooms:
        if room.devices and all(d.node in lost_nodes for d in room.devices):
            room.status = "unreachable"
        room.devices = [d for d in room.devices if d.node not in lost_nodes]
        for d in room.devices:
            d.path_m = round(bundle.along[d.node] / 1000, 2)
            res.nodes.append(
                NodeMark("M-NODE", "device", d.xy, pl.z_heat, ap.idx, "heating", room.room_id)
            )
    step = p.num("bundle_beam_step_mm")
    snap = p.num("topo_terminal_radius_mm") - 5
    paths = ([seed] if seed is not None and len(seed) > 1 else []) + [i.cells for i in items]
    lay = Layout(rg, paths, [2] * len(paths), step, snap)
    lead = 1 if paths and paths[0] is seed else 0
    if lead and feed is not None:
        for lane, layer in enumerate(LAYERS):
            pts = _feed_lane(pl, feed, lay, lane)
            res.lines.append(Line3D(layer, [(x, y, pl.z_heat) for x, y in pts], ap.idx, "route"))
    beams_mm = jumpers_mm = 0.0
    for n, item in enumerate(items):
        marks = [m for _, m in item.devices]
        xys = [d.xy for d, _ in item.devices]
        for lane, layer in enumerate(LAYERS):
            pts, idx = lay.lane(lead + n, lane, marks)
            for k, piece in enumerate(
                _pieces(pts, idx, marks, xys, p.num("topo_terminal_radius_mm") - 10)
            ):
                if len(piece) >= 2:
                    kind = "route" if k == 0 else "jumper"
                    res.lines.append(
                        Line3D(layer, [(x, y, pl.z_heat) for x, y in piece], ap.idx, kind)
                    )
        beams_mm += marks[0] * rg.step
        jumpers_mm += (marks[-1] - marks[0]) * rg.step
    info["heat_beams_m"] = round((beams_mm + jumpers_mm) / 1000, 2)
    info["heat_jumpers_m"] = round(jumpers_mm / 1000, 2)
    res.beam_paths[ap.idx] = [[pl.node_xy(c) for c in i.cells] for i in items]
