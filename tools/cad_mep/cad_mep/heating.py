"""Отопление: стволы от шахт ОВ до коллекторов, приборы и лучи квартир (дерево от коллектора)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cad_mep import heatdev
from cad_mep.heatdev import HeatRoom
from cad_mep.result import NodeMark
from cad_mep.rooms import Apartment
from cad_mep.route import RouteGrid, node_path, spt, tree_chains

if TYPE_CHECKING:
    from cad_mep.systems import Planner


def beam_tree(
    rg: RouteGrid, root: int, targets: list[int]
) -> tuple[list[list[int]], dict[int, float], list[int]]:
    """Дерево лучей квартиры от коллектора.

    Каждый следующий прибор — ближайший к уже построенному дереву — подключается к ближайшей
    его точке. Путь касается дерева только началом, поэтому петель нет. Возвращает пути,
    длину по дереву от коллектора до каждой клетки (мм) и приборы, до которых пути нет.
    """
    along: dict[int, float] = {root: 0.0}
    paths: list[list[int]] = []
    left = sorted(set(targets) - {root})
    while left:
        tree = spt(rg, sorted(along), left, first=True)
        best = min(left, key=lambda n: (tree[n], n))
        if not math.isfinite(tree[best]):
            break
        path = node_path(tree, best)
        base = along[path[0]]
        for i, cell in enumerate(path):
            along.setdefault(cell, base + i * rg.step)
        paths.append(path)
        left.remove(best)
    return paths, along, left


def route(pl: Planner) -> None:
    """Стволы от шахт ОВ до коллекторов, затем приборы и лучи каждой квартиры."""
    m, rg, res = pl.m, pl.rg, pl.res
    shafts = pl.ov_mop
    pick, forest, node_of = pl.assign(shafts, {a: v[0] for a, v in pl.coll.items()})
    shaft_node = {sh.id: n for n, sh in node_of.items()}
    by_shaft: dict[str, list[int]] = {}
    for ai, sh in pick.items():
        by_shaft.setdefault(sh.id, []).append(ai)
    for ai in pl.coll:
        if ai not in pick:
            pl.issue(
                "heat_no_path",
                f"{m.apts[ai].number}: отопление — путь от шахты ОВ до коллектора не найден",
                m.apts[ai],
            )
    for sid in sorted(by_shaft):
        apt_ids = by_shaft[sid]
        sh = next(s for s in shafts if s.id == sid)
        n0 = shaft_node[sid]
        paths = {a: node_path(forest, pl.coll[a][0]) for a in apt_ids}
        for lay in ("M-OV-T1", "M-OV-T2"):
            pl.riser(sh, lay)
            pl.leadin(sh, lay, pl.z_heat, n0)
        chains = tree_chains(rg, list(paths.values()), pl.simplify)
        for lay in ("M-OV-T1", "M-OV-T2"):
            pl.add_chains(lay, chains, pl.z_heat, None)
        for a in apt_ids:
            info = pl.apt_info(m.apts[a])
            info["heat_shaft"] = sh.id
            info["heat_path_to_collector_m"] = round(pl.path_len_mm(paths[a]) / 1000, 2)
    # приборы и лучи внутри квартир
    for ap in m.apts.values():
        rooms, issues = heatdev.place(m, pl.L, rg, pl.prof, pl.p, ap)
        res.heat_rooms += rooms
        res.issues += issues
        if ap.idx in pl.coll:
            beams(pl, ap, rooms)
        for room in rooms:
            if room.devices:
                continue
            why = heatdev.NO_DEVICE_REASON[room.status]
            if room.status == "glazing_of_neighbour":
                near = sorted(r.room_id for r in rooms if r.devices and r.comp == room.comp)
                if near:
                    # ниша без своего остекления, открытая в комнату с приборами: её греют они
                    room.status = heatdev.HEATED_BY_ADJACENT
                    pl.issue(
                        "room_heated_by_adjacent",
                        f"{ap.number}: {room.room_id} {room.name} — своего остекления нет, "
                        f"открыта в {', '.join(near)}: прибор не ставится, обогрев от "
                        "соседних приборов",
                        ap,
                    )
                    continue
            pl.issue(
                "heated_room_without_device",
                f"{ap.number}: {room.room_id} {room.name} — отапливаемая комната без "
                f"прибора: {why}",
                ap,
            )


def beams(pl: Planner, ap: Apartment, rooms: list[HeatRoom]) -> None:
    """Лучи квартиры: дерево от коллектора до приборов, подача и обратка парой."""
    rg, res = pl.rg, pl.res
    root, xy = pl.coll[ap.idx]
    info = pl.apt_info(ap)
    res.nodes.append(NodeMark("M-NODE", "collector", xy, pl.z_heat, ap.idx, "heating"))
    paths, along, lost = beam_tree(rg, root, [d.node for r in rooms for d in r.devices])
    if lost:
        pl.issue(
            "heat_beam_unreachable",
            f"{ap.number}: луч отопления — путь до {len(lost)} приборов не найден",
            ap,
        )
    for room in rooms:
        if room.devices and all(d.node in lost for d in room.devices):
            room.status = "unreachable"
        room.devices = [d for d in room.devices if d.node not in lost]
        for d in room.devices:
            d.path_m = round(along[d.node] / 1000, 2)
            res.nodes.append(
                NodeMark("M-NODE", "device", d.xy, pl.z_heat, ap.idx, "heating", room.room_id)
            )
    chains = tree_chains(rg, paths, pl.simplify)
    for lay in ("M-OV-T1", "M-OV-T2"):
        pl.add_chains(lay, chains, pl.z_heat, ap.idx)
    info["heat_beams_m"] = round(sum(pl.path_len_mm(p) for p in paths) / 1000, 2)
    res.beam_paths[ap.idx] = [[(float(rg.xy[n][0]), float(rg.xy[n][1])) for n in p] for p in paths]
