"""Источники отопления: этажный шкаф секции и коллектор квартиры во влажной комнате."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from cad_mep.result import Pt
from cad_mep.rooms import Apartment, Shaft
from cad_mep.route import spt

if TYPE_CHECKING:
    from cad_mep.systems import Planner


@dataclass(frozen=True)
class Collector:
    node: int
    xy: Pt
    room_id: str | None  # влажная комната; None — прежнее правило у входной двери
    fallback: bool


@dataclass
class Root:
    """Корень пучка подводок: шахта (стояки) и узел сетки у неё."""

    shaft: Shaft
    node: int
    apts: list[int]
    cabinet: bool  # этажный шкаф (иначе — шахта ОВ)


def _wet_rooms(pl: Planner, ap: Apartment) -> list[tuple[int, str]]:
    rx = re.compile(pl.p.text("collector_room_regex"), re.IGNORECASE)
    out: list[tuple[int, str]] = []
    for cid in ap.comps:
        for rl in pl.m.comps[cid].room_labels:
            row = pl.expl.get(rl.room_id)
            if row is not None and rx.search(row.name):
                out.append((cid, rl.room_id))
                break
    return out


def wet_collector(pl: Planner, ap: Apartment, entry_node: int) -> Collector | None:
    """Коллектор в влажной комнате, ближайшей ко входу по пути: у двери санузла, вне створки."""
    wet = _wet_rooms(pl, ap)
    if not wet:
        return None
    rg = pl.rg
    room_of = dict(wet)
    cells = np.nonzero(np.isin(pl.node_comp, list(room_of)))[0]
    tree = spt(rg, [entry_node], cells.tolist())
    reach = [int(n) for n in cells if math.isfinite(tree[int(n)])]
    if not reach:
        return None
    nearest = min(reach, key=lambda n: (tree[n], n))
    cid = int(pl.node_comp[nearest])
    near_xy = (float(rg.xy[nearest][0]), float(rg.xy[nearest][1]))
    door_pt, swing = near_xy, None
    links = [lk for lk in pl.m.door_links if cid in (lk.a, lk.b)]
    if links:
        lk = min(
            links,
            key=lambda k: math.hypot(k.door.mid[0] - near_xy[0], k.door.mid[1] - near_xy[1]),
        )
        door_pt, swing = lk.door.mid, (lk.door.a, lk.door.width + pl.p.num("collector_swing_mm"))
    off = pl.p.num("collector_offset_mm")
    in_room = pl.node_comp == cid
    px, py = rg.xy[:, 0], rg.xy[:, 1]
    free = np.ones(len(px), dtype=np.bool_)
    if swing is not None:
        free = np.hypot(px - swing[0][0], py - swing[0][1]) >= swing[1]
    ok = np.zeros(len(px), dtype=np.bool_)
    ok[reach] = True
    for lo, hi in (
        (off, off + 2 * rg.step),
        (off, math.inf),
        (pl.p.num("collector_fallback_mm"), math.inf),
    ):
        mask = in_room & free & ok & (pl.node_d >= lo) & (pl.node_d < hi)
        ids = np.nonzero(mask)[0]
        if len(ids):
            dd = np.hypot(px[ids] - door_pt[0], py[ids] - door_pt[1])
            best = int(ids[int(np.argmin(dd))])
            return Collector(best, (float(px[best]), float(py[best])), room_of[cid], False)
    return None


def entry_collector(pl: Planner, ap: Apartment) -> Collector | None:
    """Прежнее правило: у входной двери на collector_offset_mm от стены, ближе всего к двери."""
    if ap.entry_door is None or ap.entry_apt_comp is None:
        return None
    rg = pl.rg
    off = pl.p.num("collector_offset_mm")
    mask = (rg.comp_of == ap.entry_apt_comp) & (rg.d >= off) & (rg.d < off + 2 * rg.step)
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        mask = (rg.comp_of == ap.entry_apt_comp) & (rg.d >= pl.p.num("collector_fallback_mm"))
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            return None
    mx, my = ap.entry_door.mid
    px, py = (xs + 0.5) * rg.step, (ys + 0.5) * rg.step
    dd = np.hypot(px - mx, py - my)
    dd = np.where(dd < pl.p.num("collector_door_clear_mm"), 1e9, dd)  # не в самом проёме
    k = int(np.argmin(dd))
    return Collector(int(rg.idx[ys[k], xs[k]]), (float(px[k]), float(py[k])), None, True)


def find_collector(pl: Planner, ap: Apartment) -> Collector | None:
    """Влажная комната по экспликации, иначе — прежнее правило с замечанием."""
    entry = pl.entry.get(ap.idx)
    found = wet_collector(pl, ap, entry[0]) if entry is not None else None
    if found is not None:
        return found
    found = entry_collector(pl, ap)
    if found is not None:
        pl.issue(
            "collector_fallback_entry",
            f"{ap.number}: отопление — влажная комната (санузел, ванная) в экспликации не найдена "
            "или недоступна: коллектор поставлен у входной двери",
            ap,
        )
    return found


def _sum_to_entries(pl: Planner, node: int, targets: list[int]) -> tuple[int, float]:
    tree = spt(pl.rg, [node], targets)
    dist = [tree[t] for t in targets]
    lost = sum(1 for d in dist if not math.isfinite(d))
    return lost, float(sum(d for d in dist if math.isfinite(d)))


def _shaft_node(pl: Planner, sh: Shaft) -> int | None:
    pt = sh.mop_exit or sh.centroid
    return pl.rg.node(*pt, r_mm=pl.p.num("cabinet_shaft_radius_mm"), only_mop=True)


def _candidates(pl: Planner, shafts: list[Shaft]) -> list[tuple[Shaft, int]]:
    out: list[tuple[Shaft, int]] = []
    for sh in shafts:
        node = _shaft_node(pl, sh)
        if node is not None:
            out.append((sh, node))
    return out


def cabinets(pl: Planner) -> list[Root]:
    """Этажный шкаф на секцию: у шахты ВК в МОП (иначе ОВ), с наименьшей суммой путей до входов."""
    by_section: dict[str, list[int]] = {}
    for ai in pl.coll:
        by_section.setdefault(pl.m.apts[ai].section, []).append(ai)
    roots: list[Root] = []
    for section in sorted(by_section):
        apts = by_section[section]
        targets = sorted({pl.entry[a][2] for a in apts if a in pl.entry})
        kind = "ВК"
        cand = _candidates(pl, pl.vk_mop)
        if not cand:
            kind = "ОВ"
            cand = _candidates(pl, pl.ov_mop)
        if not cand or not targets:
            pl.issue(
                "heat_no_cabinet",
                f"секция {section or '?'}: этажный шкаф отопления не поставлен — нет шахты ВК или "
                "ОВ в МОП рядом с коридором",
            )
            continue
        best = min(cand, key=lambda c: (*_sum_to_entries(pl, c[1], targets), c[0].id))
        if kind != "ВК":
            pl.issue(
                "heat_cabinet_on_ov_shaft",
                f"секция {section or '?'}: шахты ВК в МОП нет, этажный шкаф поставлен у шахты ОВ "
                f"{best[0].id}",
            )
        roots.append(Root(best[0], best[1], sorted(apts), True))
    return roots


def ov_roots(pl: Planner) -> list[Root]:
    """Прежнее поведение: каждая квартира — от ближайшей по пути шахты ОВ в МОП."""
    pick, _forest, node_of = pl.assign(pl.ov_mop, {a: v[0] for a, v in pl.coll.items()})
    node = {sh.id: n for n, sh in node_of.items()}
    by_shaft: dict[str, list[int]] = {}
    for ai, sh in pick.items():
        by_shaft.setdefault(sh.id, []).append(ai)
    return [
        Root(next(s for s in pl.ov_mop if s.id == sid), node[sid], sorted(apts), False)
        for sid, apts in sorted(by_shaft.items())
    ]
