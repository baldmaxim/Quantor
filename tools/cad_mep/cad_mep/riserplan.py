"""Стояки по реестру ИОС (cad_risers.v1): вода — одна шахта ВК на секцию, пожаротушение — ниши ПК.

Реестр вводит человек по проекту ИОС. Он заменяет «стояк в каждой шахте по подписи АР»:
- В1/Т3/Т4 (свои и транзитные) — вертикали в одной шахте ВК в МОП на секцию; горизонталь — только
  у своих стояков, от этой же шахты;
- ВПВ, АУП, пожарные стояки — в нишах ПК; горизонтали ВПВ нет, магистраль АУП — от стояка АУП.
Системы, которых в реестре нет, не строятся (справка riser_system_absent).
"""

from __future__ import annotations

from itertools import pairwise
from typing import TYPE_CHECKING

from cad_mep import fire, heatsrc
from cad_mep.result import NodeMark
from cad_mep.risers import WATER_SYSTEMS, RiserEntry
from cad_mep.rooms import Shaft
from cad_mep.route import Tree, node_path, spt, tree_chains

if TYPE_CHECKING:
    from cad_mep.systems import Planner

WATER_LAYER = {"V1": "M-VK-V1", "T3": "M-VK-T3", "T4": "M-VK-T4"}
FIRE_LAYER = {"VPV": "M-PT-VPV", "AUP": "M-PT-AUP", "FS": "M-PT-VPV"}
NAME = {"V1": "В1", "T3": "Т3", "T4": "Т4", "VPV": "ВПВ", "AUP": "АУП", "FS": "пожарные стояки"}


def _slot(layer: str, idx: int, k: int) -> str:
    return f"{layer}|{idx}.{k}"


def _absent(pl: Planner, reg: list[RiserEntry], systems: tuple[str, ...]) -> None:
    have = {e.system for e in reg}
    for system in systems:
        if system not in have:
            pl.issue(
                "riser_system_absent",
                f"справка: в реестре стояков нет системы {NAME[system]} — её трассы не строятся",
            )


def _invalid(pl: Planner, e: RiserEntry, what: str) -> None:
    pl.issue(
        "riser_shaft_invalid",
        f"стояк {e.mark}: шахта {e.shaft_id} не {what} — шахта выбрана автоматически",
    )


# ---------- вода
def place_water(pl: Planner, reg: list[RiserEntry]) -> None:
    m = pl.m
    recs = [(i, e) for i, e in enumerate(reg) if e.system in WATER_LAYER]
    _absent(pl, reg, WATER_SYSTEMS)
    if not recs:
        return
    by_id = {s.id: s for s in pl.vk_mop}
    explicit: dict[int, Shaft] = {}
    for i, e in recs:
        if e.shaft_id is None:
            continue
        if e.shaft_id in by_id:
            explicit[i] = by_id[e.shaft_id]
        else:
            _invalid(pl, e, "шахта ВК в МОП")
    own = [(i, e) for i, e in recs if e.role == "own"]
    own_shafts = [explicit[i] for i, _ in own if i in explicit]
    forced = own_shafts[0] if own_shafts else None
    if len({s.id for s in own_shafts}) > 1:
        pl.issue(
            "riser_shaft_conflict",
            "собственные стояки воды указаны в разных шахтах: все ставятся в "
            f"{forced.id if forced else '?'} (первая по реестру)",
        )
    src: dict[str, Shaft] = {}
    for section in sorted({a.section for a in m.apts.values()}):
        sh = forced or heatsrc.vk_shaft_for(pl, section)
        if sh is not None:
            src[section] = sh
    home = sorted({s.id: s for s in src.values()}.values(), key=lambda s: s.id)
    if not home and pl.vk_mop:
        home = [min(pl.vk_mop, key=lambda s: s.id)]
    # вертикали — по порядку записей реестра
    for i, e in recs:
        targets = [explicit[i]] if i in explicit and e.role == "transit" else home
        if not targets:
            pl.issue(
                "riser_shaft_missing",
                f"стояк {e.mark}: нет шахты ВК в МОП — стояк не нарисован",
            )
            continue
        layer = WATER_LAYER[e.system]
        for k in range(e.count):
            for sh in targets:
                pl.riser(sh, layer, e, _slot(layer, i, k))
    first_own = {s: next(((i, e) for i, e in own if e.system == s), None) for s in WATER_SYSTEMS}
    if not any(first_own.values()):
        pl.issue(
            "riser_no_own_water",
            "водоснабжение квартир не проложено: в реестре нет собственных стояков В1, Т3, Т4",
        )
    elif home:
        for section, sh in sorted(src.items()):
            _horizontal(pl, section, sh, first_own)
    used = {sid for (sid, _key), tag in pl.slot_tag.items() if tag.system in WATER_LAYER}
    for s in sorted(pl.vk_mop, key=lambda s: s.id):
        if s.id not in used and src:
            ids = ", ".join(sorted({sh.id for sh in src.values()}))
            pl.issue(
                "riser_shaft_unused",
                f"справка: шахта ВК {s.id} стояков воды не получает — по реестру все квартиры "
                f"секции питаются от {ids}",
            )


def _trunk_tree(pl: Planner, n0: int, apts: list[int]) -> tuple[dict[int, list[int]], Tree]:
    """Пути от шахты (узел n0) до вводов квартир одним деревом, без параллельных ветвей.

    Квартиры — от ближайшей к дальней; каждая подключается к уже построенному дереву
    кратчайшим путём, а не отдельным путём от шахты: общая магистраль идёт одной линией.
    """
    rg, entry = pl.rg, pl.entry
    near = spt(rg, [n0], {entry[a][0] for a in apts} | {entry[a][2] for a in apts})
    parent: dict[int, int | None] = {n0: None}
    paths: dict[int, list[int]] = {}
    for a in sorted(apts, key=lambda a: (near[entry[a][0]], a)):
        target = entry[a][0]
        if target not in parent:
            path = node_path(spt(rg, sorted(parent), [target]), target)
            if not path:
                continue
            for u, v in pairwise(path):
                parent.setdefault(v, u)
        chain = [target]
        while (up := parent[chain[-1]]) is not None:
            chain.append(up)
        paths[a] = chain[::-1]
    return paths, near


def _horizontal(
    pl: Planner,
    section: str,
    sh: Shaft,
    first_own: dict[str, tuple[int, RiserEntry] | None],
) -> None:
    """Магистраль воды секции от шахты sh: В1/Т3 с вводами в квартиры, Т4 — по коридору."""
    m, rg, res, entry = pl.m, pl.rg, pl.res, pl.entry
    apts = sorted(a for a in entry if m.apts[a].section == section)
    n0 = pl.shaft_node(sh)
    paths, near = _trunk_tree(pl, n0, apts) if n0 is not None else ({}, None)
    for a in apts:
        if a not in paths:
            pl.issue(
                "water_no_path",
                f"{m.apts[a].number}: водоснабжение — путь от шахты ВК не найден",
                m.apts[a],
            )
    apt_ids = sorted(paths)
    if n0 is None or near is None or not apt_ids:
        return
    root = pl.node_xy(n0)
    drops = {(round(entry[a][1][0]), round(entry[a][1][1])): pl.z_meter for a in apt_ids}
    chains = tree_chains(rg, list(paths.values()), pl.simplify)
    for system in ("V1", "T3"):
        own = first_own[system]
        if own is None:
            continue
        lay = WATER_LAYER[system]
        slot = _slot(lay, own[0], 0)
        pl.riser(sh, lay, own[1], slot)
        pl.leadin(sh, lay, pl.z_ceil, n0, slot)
        pl.add_chains(lay, chains, pl.z_ceil, None, root, drops)
    t4 = first_own["T4"]
    if t4 is not None:
        _circulation(pl, sh, n0, apt_ids, near, t4)
    if first_own["V1"] is None and first_own["T3"] is None:
        return
    for a in apt_ids:
        ap = m.apts[a]
        info = pl.apt_info(ap)
        info["water_shaft"] = sh.id
        info["water_path_m"] = round(pl.path_len_mm(paths[a]) / 1000, 2)
        res.nodes.append(NodeMark("M-NODE", "meter", entry[a][1], pl.z_meter, a, "water"))


def _circulation(
    pl: Planner,
    sh: Shaft,
    n0: int,
    apt_ids: list[int],
    near: Tree,
    own: tuple[int, RiserEntry],
) -> None:
    """Т4 — полосой по коридору от стояка до последнего тройника Т3 в МОП, без вводов в квартиры.

    По каждую сторону от шахты — кратчайшим путём до МОП-стороны входа самой дальней квартиры
    (там Т3 сворачивает в квартиру); конец — терминальный узел.
    """
    m, rg, res, entry = pl.m, pl.rg, pl.res, pl.entry
    sx = sh.centroid[0]
    p4s: list[list[int]] = []
    for side in (-1, 1):
        grp = [a for a in apt_ids if (entry[a][1][0] - sx) * side > 0]
        if not grp:
            continue
        last = max(grp, key=lambda a: (near[entry[a][2]], -a))
        p4 = pl.path_from(near, n0, entry[last][2])
        if p4:
            p4s.append(p4)
            res.nodes.append(
                NodeMark("M-NODE", "t4_end", pl.node_xy(p4[-1]), pl.z_ceil, last, "water")
            )
            pl.apt_info(m.apts[last])["t4_last_of_branch"] = True
    if not p4s:
        return
    lay = WATER_LAYER["T4"]
    slot = _slot(lay, own[0], 0)
    pl.riser(sh, lay, own[1], slot)
    pl.leadin(sh, lay, pl.z_ceil, n0, slot)
    pl.add_chains(lay, tree_chains(rg, p4s, pl.simplify), pl.z_ceil, None, pl.node_xy(n0))


# ---------- пожаротушение
def fire_niches(pl: Planner) -> list[Shaft]:
    """Ниши ПК в МОП с найденным контуром: по (x, y)."""
    return sorted(
        (
            s
            for s in pl.m.shafts
            if "ПК" in s.systems and s.place == "mop" and s.contour_status == "found"
        ),
        key=lambda s: (s.centroid[0], s.centroid[1], s.id),
    )


def place_fire(pl: Planner, reg: list[RiserEntry]) -> None:
    rg, res = pl.rg, pl.res
    _absent(pl, reg, ("VPV", "AUP"))
    for n in pl.pk_nodes:  # метка шкафа ПК, как при расчёте без реестра
        xy = (float(rg.xy[n][0]), float(rg.xy[n][1]))
        res.nodes.append(NodeMark("M-NODE", "pk", xy, pl.z_ceil, None, "fire"))
    recs = [(i, e) for i, e in enumerate(reg) if e.system in FIRE_LAYER]
    niches = fire_niches(pl)
    placed: list[tuple[int, int, Shaft]] = []
    load: dict[str, list[str]] = {s.id: [] for s in niches}
    by_id = {s.id: s for s in niches}
    auto: list[tuple[int, RiserEntry]] = []
    for i, e in recs:
        if e.shaft_id is not None and e.shaft_id in by_id:
            for k in range(e.count):
                placed.append((i, k, by_id[e.shaft_id]))
                load[e.shaft_id].append(e.mark)
            continue
        if e.shaft_id is not None:
            _invalid(pl, e, "ниша ПК в МОП")
        auto.append((i, e))
    for system in ("VPV", "AUP", "FS"):
        for i, e in (r for r in auto if r[1].system == system):
            if not niches:
                pl.issue(
                    "riser_shaft_missing",
                    f"стояк {e.mark}: нет ниши ПК в МОП — стояк не нарисован",
                )
                continue
            one_niche = system == "FS"  # пара сухо/мокро — вместе в одной нише
            for k in range(1 if one_niche else e.count):
                free = [s for s in niches if not load[s.id]]
                sh = free[0] if free else min(niches, key=lambda s: len(load[s.id]))
                n = e.count if one_niche else 1
                if free:
                    pl.issue(
                        "riser_auto_shaft",
                        f"справка: стояк {_title(e, k, e.count, one_niche)} поставлен в {sh.id} "
                        "автоматически",
                    )
                else:
                    others = ", ".join(load[sh.id])
                    pl.issue(
                        "riser_shaft_shared",
                        f"справка: свободных ниш ПК нет, стояк {_title(e, k, e.count, one_niche)} "
                        f"поставлен в {sh.id} совместно со стояками {others}",
                    )
                for j in range(n):
                    placed.append((i, k + j, sh))
                    load[sh.id].append(e.mark)
    placed.sort(key=lambda t: (t[0], t[1]))
    for i, k, sh in placed:
        e = reg[i]
        layer = FIRE_LAYER[e.system]
        pl.riser(sh, layer, e, _slot(layer, i, k))
    ap_paths: list[list[int]] = []
    cover: list[dict[str, object]] = []
    source: str | None = None
    first_aup = next(((i, k, sh) for i, k, sh in placed if reg[i].system == "AUP"), None)
    if first_aup is not None:
        i, k, sh = first_aup
        source = sh.id
        node = rg.node(
            *(sh.mop_exit or sh.label_pt), r_mm=pl.p.num("pk_node_radius_mm"), only_mop=True
        )
        if node is not None:
            ap_paths, cover = fire.aup_branch(pl, sh, node, reg[i], _slot(FIRE_LAYER["AUP"], i, k))
    res.fire = {
        "source_shaft": source,
        "pk_count": len(pl.pk_nodes),
        "vpv_paths_m": [],
        "aup_paths_m": [round(pl.path_len_mm(p) / 1000, 2) for p in ap_paths],
        "aup_coverage": cover,
        "riser_registry": True,
    }


def _title(e: RiserEntry, k: int, count: int, together: bool) -> str:
    if together and count > 1:
        return f"{e.mark} (×{count})"
    return f"{e.mark} №{k + 1} из {count}" if count > 1 else e.mark
