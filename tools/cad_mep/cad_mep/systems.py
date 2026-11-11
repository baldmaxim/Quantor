"""Планировщик трасс: общие узлы и помощники, водоснабжение, канализация, стояки и их 3D.

Отопление — heating.py, пожаротушение — fire.py (шаги 4–5 ТЗ прототипа).
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString

from cad_mep import facade, fire, heating, heatsrc, riserplan
from cad_mep.dxfin import Door
from cad_mep.issues import Issue
from cad_mep.labels import Labels
from cad_mep.layers import SYSTEM_OF_LAYER
from cad_mep.params import Params
from cad_mep.result import Line3D, NodeMark, Pt, Pt3, Result
from cad_mep.risers import RiserEntry
from cad_mep.rooms import Apartment, Model, Shaft
from cad_mep.route import RouteGrid, Tree, node_path, spt, tree_chains
from cad_mep.treeoff import offset_tree


class Planner:
    def __init__(
        self,
        m: Model,
        labels: Labels,
        doors: list[Door],
        rg: RouteGrid,
        params: Params,
        floor_mm: float,
        height_mm: float,
        prof: facade.Profile,
        registry: list[RiserEntry] | None = None,
    ) -> None:
        self.m, self.L, self.doors, self.rg, self.p = m, labels, doors, rg, params
        self.prof = prof
        self.registry = registry  # None — реестра стояков нет: стояки по подписям шахт АР
        self.res = Result()
        self.riser_x: dict[str, dict[str, float]] = {}  # шахта -> место стояка -> порядок
        # место стояка по умолчанию называется слоем; в реестре — слой и номер записи
        self.slot_layer: dict[tuple[str, str], str] = {}
        self.slot_tag: dict[tuple[str, str], RiserEntry] = {}
        self._leadins: list[tuple[Line3D, str, str]] = []
        self.cabinet_shaft: dict[str, Shaft] = {}  # секция -> шахта ВК этажного шкафа
        self.expl = labels.expl
        self.zf = floor_mm
        self.h = height_mm
        self.z_heat = floor_mm + params.num("z_heat_mm")
        self.z_ceil = floor_mm + height_mm - params.num("ceiling_below_slab_mm")
        self.z_meter = floor_mm + params.num("z_meter_mm")
        self.offsets = params.num_map("layer_offset_mm")
        self.simplify = params.num("chain_simplify_mm")
        self.heat_targets: set[int] = set()
        self.water_targets: set[int] = set()
        self.fire_targets: set[int] = set()
        self.vk_mop: list[Shaft] = []
        self.ov_mop: list[Shaft] = []
        self.coll: dict[int, tuple[int, Pt]] = {}
        self.coll_room: dict[int, str | None] = {}
        ys, xs = np.nonzero(rg.pas)  # порядок совпадает с нумерацией узлов rg.idx
        self.node_comp = rg.comp_of[ys, xs]
        self.node_d = rg.d[ys, xs]
        self.node_mop = rg.mop[ys, xs]
        self.apt_of_comp = {c.id: c.apt for c in m.comps.values() if c.apt is not None}
        self._foreign: dict[int, dict[int, float]] = {}
        self.entry: dict[int, tuple[int, Pt, int]] = {}
        self.pk_nodes: list[int] = []

    # ---------- общие помощники
    def issue(self, code: str, message: str, apt: Apartment | None = None) -> None:
        self.res.issues.append(Issue(code, message, apt.number if apt else None))

    def shaft_node(self, sh: Shaft) -> int | None:
        if not sh.mop_exit:
            return None
        return self.rg.node(*sh.mop_exit, r_mm=self.p.num("shaft_node_radius_mm"), only_mop=True)

    def riser(
        self, sh: Shaft, layer: str, tag: RiserEntry | None = None, slot: str | None = None
    ) -> Pt:
        """Точка стояка слоя в шахте; смещение применяется в finalize_risers.

        slot — отдельное место стояка (по реестру на слое бывает несколько стояков); без него
        место стояка — слой.
        """
        key = slot or layer
        d = self.riser_x.setdefault(sh.id, {})
        if key not in d:
            d[key] = float(len(d))
            self.slot_layer[(sh.id, key)] = layer
            if tag is not None:
                self.slot_tag[(sh.id, key)] = tag
        return (sh.centroid[0], sh.centroid[1])

    def door_sides(self, door: Door) -> tuple[Pt, Pt]:
        """(точка со стороны МОП, точка со стороны квартиры) на water_entry_mm от центра проёма."""
        nx, ny = door.normal()
        mx, my = door.mid
        off = self.p.num("water_entry_mm")
        r = self.p.num("door_side_radius_mm")
        out = [(mx + s * nx * off, my + s * ny * off) for s in (1, -1)]
        dist: list[float] = []
        for pt in out:
            n = self.rg.node(*pt, r_mm=r, only_mop=True)
            dist.append(float(np.hypot(*(self.rg.xy[n] - np.array(pt)))) if n is not None else 1e9)
        return (out[0], out[1]) if dist[0] <= dist[1] else (out[1], out[0])

    def add_chains(
        self,
        layer: str,
        chains: list[list[Pt]],
        z: float,
        apt: int | None,
        root: Pt,
        drops: dict[tuple[int, int], float] | None = None,
        tips: bool = False,
    ) -> None:
        """Цепочки дерева слоя со смещением слоя; стыки на тройниках и концы — без разрывов."""
        off = self.offsets.get(layer, 0.0)
        for ch, oc in zip(chains, offset_tree(chains, root, off, tips), strict=True):
            pts3: list[Pt3] = [(x, y, z) for x, y in oc]
            if drops:
                for end in (0, -1):
                    key = (round(ch[end][0]), round(ch[end][1]))
                    if key in drops:
                        x, y, _ = pts3[end]
                        z2 = drops[key]
                        pts3 = [(x, y, z2), *pts3] if end == 0 else [*pts3, (x, y, z2)]
            self.res.lines.append(Line3D(layer, pts3, apt, "route"))

    def node_xy(self, node: int) -> Pt:
        return (float(self.rg.xy[node][0]), float(self.rg.xy[node][1]))

    def foreign(self, apt: int) -> dict[int, float]:
        """Узлы, закрытые для путей квартиры: МОП и чужие квартиры (inf)."""
        if apt not in self._foreign:
            owner = np.array([self.apt_of_comp.get(int(c), -1) for c in self.node_comp])
            bad = self.node_mop | ((self.node_comp > 0) & (owner != apt))
            self._foreign[apt] = dict.fromkeys(np.nonzero(bad)[0].tolist(), float("inf"))
        return self._foreign[apt]

    def leadin(self, sh: Shaft, layer: str, z: float, node: int, slot: str | None = None) -> None:
        xy = self.riser(sh, layer, slot=slot)
        tgt = (float(self.rg.xy[node][0]), float(self.rg.xy[node][1]))
        line = Line3D(layer, [(xy[0], xy[1], z), (tgt[0], tgt[1], z)], None, "leadin")
        self.res.lines.append(line)
        self._leadins.append((line, sh.id, slot or layer))

    def apt_info(self, ap: Apartment) -> dict[str, object]:
        return self.res.per_apt.setdefault(ap.idx, {"number": ap.number})

    def path_len_mm(self, nodes: list[int]) -> float:
        if len(nodes) < 2:
            return 0.0
        ls = LineString([(float(self.rg.xy[n][0]), float(self.rg.xy[n][1])) for n in nodes])
        return float(ls.simplify(self.p.num("path_simplify_mm")).length)

    def assign(
        self, shafts: list[Shaft], targets: dict[int, int]
    ) -> tuple[dict[int, Shaft], Tree, dict[int, Shaft]]:
        """Квартира -> ближайшая по пути шахта.

        Одно лесное дерево от узлов всех шахт: путь к цели идёт от ближайшего источника, так что
        «ближайшая шахта» и её путь получаются за один обход сетки.
        """
        by_node: dict[int, Shaft] = {}
        for sh in shafts:
            n = self.shaft_node(sh)
            if n is not None:
                by_node.setdefault(n, sh)
        tree = spt(self.rg, list(by_node), set(targets.values()))
        pick: dict[int, Shaft] = {}
        for ai, node in targets.items():
            path = node_path(tree, node)
            if path and path[0] in by_node:
                pick[ai] = by_node[path[0]]
        return pick, tree, by_node

    def path_from(self, tree: Tree, source: int, target: int) -> list[int]:
        """Путь от конкретной шахты: из леса, а если там ближе другая шахта — отдельным обходом."""
        path = node_path(tree, target)
        if path and path[0] == source:
            return path
        return node_path(spt(self.rg, [source], [target]), target)

    # ---------- подготовка узлов (чтобы деревья путей считались один раз с общим набором целей)
    def _prepare(self) -> None:
        m, rg = self.m, self.rg
        self.ov_mop = [
            s
            for s in m.shafts
            if "ОВ" in s.systems and s.place == "mop" and s.contour_status == "found"
        ]
        self.vk_mop = [
            s
            for s in m.shafts
            if "ВК" in s.systems and s.place == "mop" and s.contour_status == "found"
        ]
        for ap in m.apts.values():
            if ap.entry_door is None:
                self.issue(
                    "water_no_entry_door", f"{ap.number}: водоснабжение — нет входной двери", ap
                )
                continue
            p_mop, p_apt = self.door_sides(ap.entry_door)
            n_in = rg.node(*p_apt, r_mm=self.p.num("entry_node_radius_mm"))
            n_mop = rg.node(*p_mop, r_mm=self.p.num("door_side_radius_mm"), only_mop=True)
            if n_in is None or n_mop is None:
                self.issue(
                    "water_entry_outside",
                    f"{ap.number}: водоснабжение — точка ввода/МОП у двери вне проходимой области",
                    ap,
                )
                continue
            self.entry[ap.idx] = (n_in, (float(rg.xy[n_in][0]), float(rg.xy[n_in][1])), n_mop)
        for ap in m.apts.values():
            col = heatsrc.find_collector(self, ap)
            if col is None:
                self.issue(
                    "heat_no_collector",
                    f"{ap.number}: отопление — не найден коллектор у входной двери",
                    ap,
                )
            else:
                self.coll[ap.idx] = (col.node, col.xy)
                self.coll_room[ap.idx] = col.room_id
        for s in (s for s in m.shafts if "ПК" in s.systems):
            n = rg.node(
                *(s.mop_exit or s.label_pt), r_mm=self.p.num("pk_node_radius_mm"), only_mop=True
            )
            if n is not None:
                self.pk_nodes.append(n)
            else:
                self.issue("fire_pk_no_corridor", f"ПК {s.id}: нет МОП рядом — ВПВ не подведена")
        self.heat_targets = {v[0] for v in self.coll.values()}
        self.water_targets = {v[0] for v in self.entry.values()} | {
            v[2] for v in self.entry.values()
        }
        self.fire_targets = set(self.pk_nodes)

    # ---------- водоснабжение
    def water(self) -> None:
        m, rg, res = self.m, self.rg, self.res
        shafts = self.vk_mop
        entry = self.entry
        pick, forest, node_of = self.assign(shafts, {a: v[0] for a, v in entry.items()})
        shaft_node = {sh.id: n for n, sh in node_of.items()}
        for ai in entry:
            if ai not in pick:
                self.issue(
                    "water_no_path",
                    f"{m.apts[ai].number}: водоснабжение — путь от шахты ВК не найден",
                    m.apts[ai],
                )
        by_shaft: dict[str, list[int]] = {}
        for ai, sh in pick.items():
            by_shaft.setdefault(sh.id, []).append(ai)
        for sid in sorted(by_shaft):
            apt_ids = by_shaft[sid]
            sh = next(s for s in shafts if s.id == sid)
            n0 = shaft_node[sid]
            paths = {a: node_path(forest, entry[a][0]) for a in apt_ids}
            drops = {(round(entry[a][1][0]), round(entry[a][1][1])): self.z_meter for a in apt_ids}
            chains = tree_chains(rg, list(paths.values()), self.simplify)
            for lay in ("M-VK-V1", "M-VK-T3"):
                self.riser(sh, lay)
                self.leadin(sh, lay, self.z_ceil, n0)
                self.add_chains(lay, chains, self.z_ceil, None, self.node_xy(n0), drops)
            # Т4 — по коридору до последней квартиры ветки (с каждой стороны от шахты), без вводов
            sx = sh.centroid[0]
            p4s: list[list[int]] = []
            for side in (-1, 1):
                grp = [a for a in apt_ids if (entry[a][1][0] - sx) * side > 0]
                if not grp:
                    continue
                last = max(grp, key=lambda a: forest[entry[a][2]])
                p4 = self.path_from(forest, n0, entry[last][2])
                if p4:
                    p4s.append(p4)
                    res.nodes.append(
                        NodeMark(
                            "M-NODE", "t4_end", self.node_xy(p4[-1]), self.z_ceil, last, "water"
                        )
                    )
                    self.apt_info(m.apts[last])["t4_last_of_branch"] = True
            if p4s:
                self.riser(sh, "M-VK-T4")
                self.leadin(sh, "M-VK-T4", self.z_ceil, n0)
                self.add_chains(
                    "M-VK-T4",
                    tree_chains(rg, p4s, self.simplify),
                    self.z_ceil,
                    None,
                    self.node_xy(n0),
                )
            for a in apt_ids:
                ap = m.apts[a]
                info = self.apt_info(ap)
                info["water_shaft"] = sh.id
                info["water_path_m"] = round(self.path_len_mm(paths[a]) / 1000, 2)
                res.nodes.append(NodeMark("M-NODE", "meter", entry[a][1], self.z_meter, a, "water"))

    # ---------- канализация
    def sewer(self) -> None:
        for sh in self.m.shafts:
            if "ВК" in sh.systems and sh.place == "apartment" and sh.contour_status == "found":
                self.riser(sh, "M-VK-K1")

    # ---------- стояки (вертикали на весь этаж) с разносом
    def finalize_risers(self) -> None:
        by_id = {s.id: s for s in self.m.shafts}
        step = self.p.num("riser_step_mm")
        for sid in sorted(self.riser_x):
            d = self.riser_x[sid]
            sh = by_id[sid]
            n = len(d)
            used: list[dict[str, object]] = []
            for key, k in d.items():
                lay = self.slot_layer[(sid, key)]
                tag = self.slot_tag.get((sid, key))
                dx = (k - (n - 1) / 2) * step
                x, y = sh.centroid[0] + dx, sh.centroid[1]
                self.res.lines.append(
                    Line3D(lay, [(x, y, self.zf), (x, y, self.zf + self.h)], None, "riser")
                )
                self.res.nodes.append(
                    NodeMark(
                        "M-RISER",
                        "riser",
                        (x, y),
                        self.zf,
                        None,
                        SYSTEM_OF_LAYER.get(lay),
                        label=tag.label() if tag else None,
                    )
                )
                for ln, lead_sid, lead_key in self._leadins:
                    if lead_sid == sid and lead_key == key:
                        ln.pts[0] = (x, y, ln.pts[0][2])
                used.append(
                    {
                        "layer": lay,
                        "system": tag.system if tag else None,
                        "mark": tag.mark if tag else None,
                        "role": tag.role if tag else None,
                        "dn_mm": tag.dn_mm if tag else None,
                    }
                )
            self.res.shaft_use[sid] = [self.slot_layer[(sid, key)] for key in d]
            self.res.shaft_risers[sid] = used

    def run(self) -> Result:
        self._prepare()
        heating.route(self)
        if self.registry is None:
            self.water()
            fire.route(self)
            self.issue(
                "risers_registry_missing",
                "справка: реестр стояков не задан — стояки по подписям шахт АР",
            )
        else:
            riserplan.place_water(self, self.registry)
            riserplan.place_fire(self, self.registry)
        self.sewer()
        self.finalize_risers()
        return self.res
