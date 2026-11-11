"""Пожаротушение: ВПВ до пожарных кранов и ветка АУП по внеквартирным помещениям."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cad_mep import aup
from cad_mep.result import NodeMark
from cad_mep.risers import RiserEntry
from cad_mep.rooms import Shaft
from cad_mep.route import Tree, node_path, spt, tree_chains

if TYPE_CHECKING:
    from cad_mep.systems import Planner


def _names(row: dict[str, object]) -> list[object]:
    names = row.get("names")
    return list(names) if isinstance(names, list) and names else [f"помещение #{row['comp']}"]


def aup_branch(
    pl: Planner, sh: Shaft, node: int, tag: RiserEntry | None = None, slot: str | None = None
) -> tuple[list[list[int]], list[dict[str, object]]]:
    """Ветка АУП от узла node шахты sh: пути, линии, замечания; возвращает пути и покрытие.

    tag и slot — стояк АУП из реестра (иначе стояк слоя, как по подписям шахт АР).
    """
    rg = pl.rg
    aup_rooms = aup.regions(rg, pl.m, pl.expl, pl.p)
    ap_paths = aup.extend(rg, node, aup_rooms, pl.p)
    if ap_paths:
        pl.riser(sh, "M-PT-AUP", tag, slot)
        pl.leadin(sh, "M-PT-AUP", pl.z_ceil, node, slot)
        pl.add_chains(
            "M-PT-AUP",
            tree_chains(rg, ap_paths, pl.simplify),
            pl.z_ceil,
            None,
            pl.node_xy(node),
            tips=True,
        )
    else:
        pl.issue("fire_aup_no_ends", "АУП: внеквартирные помещения для ветки не найдены")
    cover = aup.coverage(rg, aup_rooms, ap_paths, pl.p)
    need = pl.p.num("aup_cover_min_share")
    for row in cover:
        share = row["covered_share"]
        if isinstance(share, float) and share < need:
            pl.issue(
                "aup_coverage_low",
                f"АУП: {', '.join(str(n) for n in _names(row))} — ветка покрывает "
                f"{share * 100:.0f} % площади (нужно не меньше {need * 100:.0f} %)",
            )
    return ap_paths, cover


def route(pl: Planner) -> None:
    """ВПВ от шахты ВК до шкафов ПК и ветка АУП по внеквартирным помещениям."""
    rg, res = pl.rg, pl.res
    vk = pl.vk_mop
    if not pl.pk_nodes or not vk:
        pl.issue("fire_no_source", "пожаротушение: нет ПК или шахты ВК в МОП")
        return
    near_r = pl.p.num("near_pk_dist_mm")
    near_pk = [
        s
        for s in vk
        if any(math.hypot(s.centroid[0] - p.c[0], s.centroid[1] - p.c[1]) < near_r for p in pl.L.pk)
    ]
    best: Shaft | None = None
    bsum = math.inf
    btree: Tree | None = None
    bn0 = -1
    for sh in near_pk or vk:
        n0 = pl.shaft_node(sh)
        if n0 is None:
            continue
        tree = spt(rg, [n0], pl.fire_targets)
        total = float(sum(tree[n] for n in pl.pk_nodes))
        if math.isfinite(total) and total < bsum:
            best, bsum, btree, bn0 = sh, total, tree, n0
    if best is None or btree is None:
        pl.issue("fire_no_path", "пожаротушение: путь от шахт ВК до ПК не найден")
        return
    paths = [p for p in (node_path(btree, n) for n in pl.pk_nodes) if p]
    for n in pl.pk_nodes:  # метка шкафа ПК: конечная точка ВПВ для проверки топологии
        xy = (float(rg.xy[n][0]), float(rg.xy[n][1]))
        res.nodes.append(NodeMark("M-NODE", "pk", xy, pl.z_ceil, None, "fire"))
    pl.riser(best, "M-PT-VPV")
    pl.leadin(best, "M-PT-VPV", pl.z_ceil, bn0)
    root = pl.node_xy(bn0)
    pl.add_chains("M-PT-VPV", tree_chains(rg, paths, pl.simplify), pl.z_ceil, None, root)
    # АУП: ветка от той же шахты до дальних точек каждого внеквартирного помещения
    ap_paths, cover = aup_branch(pl, best, bn0)
    res.fire = {
        "source_shaft": best.id,
        "pk_count": len(pl.pk_nodes),
        "vpv_paths_m": [round(pl.path_len_mm(p) / 1000, 2) for p in paths],
        "aup_paths_m": [round(pl.path_len_mm(p) / 1000, 2) for p in ap_paths],
        "aup_coverage": cover,
    }
