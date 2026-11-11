"""Отопление: подводки пучком от этажного шкафа (шахты ОВ) до коллекторов; лучи — beams.py."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cad_mep import beams, heatdev, heatsrc
from cad_mep.bundle import Bundle, far_to_near
from cad_mep.heatsrc import Root
from cad_mep.lanes import Layout
from cad_mep.result import NodeMark, Pt

if TYPE_CHECKING:
    from cad_mep.systems import Planner

LAYERS = ("M-OV-T1", "M-OV-T2")


@dataclass
class Feed:
    """Подводка квартиры: путь от корня до коллектора и раскладка коридорного пучка."""

    cells: list[int]
    edge: int  # с этого ребра подводка идёт по полосам квартиры (до него — по коридорным)
    layout: Layout
    idx: int  # номер пути в раскладке коридорного пучка
    root_xy: Pt


def _corridor(pl: Planner, root: Root) -> dict[int, Feed]:
    """Пучок от узла шахты: у каждой квартиры своя пара полос T1/T2, без тройников."""
    rg, p, res = pl.rg, pl.p, pl.res
    sh, n0 = root.shaft, root.node
    apts = [a for a in root.apts if a in pl.coll]
    by_node = {pl.coll[a][0]: a for a in apts}
    bundle = Bundle(rg, n0, p)
    paths: dict[int, list[int]] = {}
    for t in far_to_near(rg, n0, list(by_node)):
        path = bundle.reach(t)
        if path:
            paths[by_node[t]] = path
    for lay in LAYERS:
        pl.riser(sh, lay)
        pl.leadin(sh, lay, pl.z_heat, n0)
    res.nodes.append(NodeMark("M-NODE", "cabinet", pl.node_xy(n0), pl.z_heat, None, "heating"))
    order = sorted(paths)
    cut: list[list[int]] = []
    edge_of: dict[int, int] = {}
    for a in order:
        cells = paths[a]
        last_out = max((k for k, c in enumerate(cells) if pl.node_mop[c]), default=-1)
        edge_of[a] = max(last_out - 1, 0)
        cut.append(cells[: min(len(cells), last_out + 2)])
    layout = Layout(
        rg,
        cut,
        [2] * len(cut),
        p.num("bundle_corridor_step_mm"),
        p.num("topo_terminal_radius_mm") - 5,
    )
    root_xy = pl.node_xy(n0)
    feeds: dict[int, Feed] = {}
    for i, a in enumerate(order):
        feeds[a] = Feed(paths[a], edge_of[a], layout, i, root_xy)
        info = pl.apt_info(pl.m.apts[a])
        info["heat_shaft"] = sh.id
        info["heat_path_to_collector_m"] = round((len(paths[a]) - 1) * rg.step / 1000, 2)
    return feeds


def route(pl: Planner) -> None:
    """Источники и подводки, затем приборы и лучи каждой квартиры."""
    m, rg, res = pl.m, pl.rg, pl.res
    cabinet = pl.p.text("heating_source") == "floor_cabinet"
    roots = heatsrc.cabinets(pl) if cabinet else heatsrc.ov_roots(pl)
    placed: dict[int, list[heatdev.HeatRoom]] = {}
    for ap in m.apts.values():
        rooms, issues = heatdev.place(m, pl.L, rg, pl.prof, pl.p, ap)
        res.heat_rooms += rooms
        res.issues += issues
        placed[ap.idx] = rooms
    feeds: dict[int, Feed] = {}
    for root in roots:
        feeds.update(_corridor(pl, root))
    for ai in pl.coll:
        if ai not in feeds:
            pl.issue(
                "heat_no_path",
                f"{m.apts[ai].number}: отопление — путь от "
                f"{'этажного шкафа' if cabinet else 'шахты ОВ'} до коллектора не найден",
                m.apts[ai],
            )
    if cabinet and pl.ov_mop:
        ids = ", ".join(s.id for s in pl.ov_mop)
        pl.issue(
            "heat_ov_shafts_unused",
            f"справка: отопление идёт от этажного шкафа у шахты ВК, шахты ОВ в МОП ({ids}) "
            "трассами не используются (heating_source = floor_cabinet)",
        )
    for ap in m.apts.values():
        rooms = placed[ap.idx]
        info = pl.apt_info(ap)
        if ap.idx in pl.coll:
            info["collector_room"] = pl.coll_room.get(ap.idx)
            beams.apartment(pl, ap, rooms, feeds.get(ap.idx))
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
