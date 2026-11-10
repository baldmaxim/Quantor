"""Трассы отопления, пожаротушения, водоснабжения, канализации и их 3D (шаги 4–5 ТЗ прототипа)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np
from shapely.errors import GEOSException
from shapely.geometry import LineString

from cad_mep import aup, facade, heatdev
from cad_mep.dxfin import Door
from cad_mep.heatdev import HeatRoom
from cad_mep.issues import Issue
from cad_mep.labels import Labels
from cad_mep.layers import SYSTEM_OF_LAYER
from cad_mep.params import Params
from cad_mep.rooms import Apartment, Model, Shaft
from cad_mep.route import RouteGrid, Tree, node_path, spt, tree_chains

Pt = tuple[float, float]
Pt3 = tuple[float, float, float]


@dataclass
class Line3D:
    layer: str
    pts: list[Pt3]
    apt: int | None = None  # None — общий участок / стояк
    kind: str = "route"  # route | riser | leadin


@dataclass
class NodeMark:
    layer: str  # M-NODE | M-RISER
    kind: str  # collector | device | meter | riser
    xy: Pt
    z: float
    apt: int | None = None
    system: str | None = None
    room: str | None = None


@dataclass
class Result:
    lines: list[Line3D] = field(default_factory=list)
    nodes: list[NodeMark] = field(default_factory=list)
    per_apt: dict[int, dict[str, object]] = field(default_factory=dict)
    fire: dict[str, object] | None = None
    shaft_use: dict[str, list[str]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    heat_rooms: list[HeatRoom] = field(default_factory=list)
    # осевые пути лучей по квартирам (узлы сетки): проверка «дерево без петель»
    beam_paths: dict[int, list[list[Pt]]] = field(default_factory=dict)


def _offset(chain: list[Pt], dist: float) -> list[Pt]:
    """Параллельная линия на dist от цепочки; сторона — «слева» при ходе по +X (иначе +Y)."""
    if len(chain) < 2 or abs(dist) < 1e-6:
        return chain
    flip = (chain[-1][0] - chain[0][0], chain[-1][1] - chain[0][1])
    rev = flip[0] < -1e-6 or (abs(flip[0]) <= 1e-6 and flip[1] < 0)
    pts = chain[::-1] if rev else chain
    try:
        oc = LineString(pts).offset_curve(dist, join_style="mitre", mitre_limit=3.0)
    except (GEOSException, ValueError):
        return chain
    if oc.is_empty or oc.geom_type != "LineString":
        # мультилиния при острых углах — берём самую длинную часть
        if oc.geom_type == "MultiLineString":
            oc = max(oc.geoms, key=lambda g: g.length)
        else:
            return chain
    out = [(float(x), float(y)) for x, y, *_ in oc.coords]
    d_same = abs(out[0][0] - pts[0][0]) + abs(out[0][1] - pts[0][1])
    d_flip = abs(out[-1][0] - pts[0][0]) + abs(out[-1][1] - pts[0][1])
    if d_same > d_flip:
        out = out[::-1]
    return out[::-1] if rev else out


def _names(row: dict[str, object]) -> list[object]:
    names = row.get("names")
    return list(names) if isinstance(names, list) and names else [f"помещение #{row['comp']}"]


def len3(pts: list[Pt3]) -> float:
    return float(
        sum(
            math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q, strict=True)))
            for p, q in pairwise(pts)
        )
    )


def plan_len(pts: list[Pt3]) -> float:
    return float(sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(pts)))


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
    ) -> None:
        self.m, self.L, self.doors, self.rg, self.p = m, labels, doors, rg, params
        self.prof = prof
        self.res = Result()
        self.riser_x: dict[str, dict[str, float]] = {}  # шахта -> слой -> порядок
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
        self._vk_mop: list[Shaft] = []
        self._ov_mop: list[Shaft] = []
        self.coll: dict[int, tuple[int, Pt]] = {}
        self.entry: dict[int, tuple[int, Pt, int]] = {}
        self.pk_nodes: list[int] = []

    # ---------- общие помощники
    def issue(self, code: str, message: str, apt: Apartment | None = None) -> None:
        self.res.issues.append(Issue(code, message, apt.number if apt else None))

    def shaft_node(self, sh: Shaft) -> int | None:
        if not sh.mop_exit:
            return None
        return self.rg.node(*sh.mop_exit, r_mm=self.p.num("shaft_node_radius_mm"), only_mop=True)

    def riser(self, sh: Shaft, layer: str) -> Pt:
        """Точка стояка слоя в шахте; смещение применяется в finalize_risers."""
        d = self.riser_x.setdefault(sh.id, {})
        if layer not in d:
            d[layer] = float(len(d))
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
        drops: dict[tuple[int, int], float] | None = None,
    ) -> None:
        off = self.offsets.get(layer, 0.0)
        for ch in chains:
            oc = _offset(ch, off)
            pts3: list[Pt3] = [(x, y, z) for x, y in oc]
            if drops:
                for end in (0, -1):
                    key = (round(ch[end][0]), round(ch[end][1]))
                    if key in drops:
                        x, y, _ = pts3[end]
                        z2 = drops[key]
                        pts3 = [(x, y, z2), *pts3] if end == 0 else [*pts3, (x, y, z2)]
            self.res.lines.append(Line3D(layer, pts3, apt, "route"))

    def leadin(self, sh: Shaft, layer: str, z: float, node: int) -> None:
        xy = self.riser(sh, layer)
        tgt = (float(self.rg.xy[node][0]), float(self.rg.xy[node][1]))
        self.res.lines.append(
            Line3D(layer, [(xy[0], xy[1], z), (tgt[0], tgt[1], z)], None, "leadin")
        )

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
        self._ov_mop = [
            s
            for s in m.shafts
            if "ОВ" in s.systems and s.place == "mop" and s.contour_status == "found"
        ]
        self._vk_mop = [
            s
            for s in m.shafts
            if "ВК" in s.systems and s.place == "mop" and s.contour_status == "found"
        ]
        for ap in m.apts.values():
            n, xy = self.collector(ap)
            if n is None or xy is None:
                self.issue(
                    "heat_no_collector",
                    f"{ap.number}: отопление — не найден коллектор у входной двери",
                    ap,
                )
            else:
                self.coll[ap.idx] = (n, xy)
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

    # ---------- квартира
    def collector(self, ap: Apartment) -> tuple[int | None, Pt | None]:
        """Коллектор — у входной двери на collector_offset_mm от стены, ближе всего к двери."""
        if ap.entry_door is None or ap.entry_apt_comp is None:
            return None, None
        rg = self.rg
        off = self.p.num("collector_offset_mm")
        mask = (rg.comp_of == ap.entry_apt_comp) & (rg.d >= off) & (rg.d < off + 2 * rg.step)
        ys, xs = np.nonzero(mask)
        if len(ys) == 0:
            mask = (rg.comp_of == ap.entry_apt_comp) & (rg.d >= self.p.num("collector_fallback_mm"))
            ys, xs = np.nonzero(mask)
            if len(ys) == 0:
                return None, None
        mx, my = ap.entry_door.mid
        px, py = (xs + 0.5) * rg.step, (ys + 0.5) * rg.step
        dd = np.hypot(px - mx, py - my)
        dd = np.where(dd < self.p.num("collector_door_clear_mm"), 1e9, dd)  # не в самом проёме
        k = int(np.argmin(dd))
        return int(rg.idx[ys[k], xs[k]]), (float(px[k]), float(py[k]))

    def beam_tree(
        self, root: int, targets: list[int]
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
            tree = spt(self.rg, sorted(along), left, first=True)
            best = min(left, key=lambda n: (tree[n], n))
            if not math.isfinite(tree[best]):
                break
            path = node_path(tree, best)
            base = along[path[0]]
            for i, cell in enumerate(path):
                along.setdefault(cell, base + i * self.rg.step)
            paths.append(path)
            left.remove(best)
        return paths, along, left

    # ---------- отопление
    def heating(self) -> None:
        m, rg, res = self.m, self.rg, self.res
        shafts = self._ov_mop
        pick, forest, node_of = self.assign(shafts, {a: v[0] for a, v in self.coll.items()})
        shaft_node = {sh.id: n for n, sh in node_of.items()}
        by_shaft: dict[str, list[int]] = {}
        for ai, sh in pick.items():
            by_shaft.setdefault(sh.id, []).append(ai)
        for ai in self.coll:
            if ai not in pick:
                self.issue(
                    "heat_no_path",
                    f"{m.apts[ai].number}: отопление — путь от шахты ОВ до коллектора не найден",
                    m.apts[ai],
                )
        for sid in sorted(by_shaft):
            apt_ids = by_shaft[sid]
            sh = next(s for s in shafts if s.id == sid)
            n0 = shaft_node[sid]
            paths = {a: node_path(forest, self.coll[a][0]) for a in apt_ids}
            for lay in ("M-OV-T1", "M-OV-T2"):
                self.riser(sh, lay)
                self.leadin(sh, lay, self.z_heat, n0)
            chains = tree_chains(rg, list(paths.values()), self.simplify)
            for lay in ("M-OV-T1", "M-OV-T2"):
                self.add_chains(lay, chains, self.z_heat, None)
            for a in apt_ids:
                info = self.apt_info(m.apts[a])
                info["heat_shaft"] = sh.id
                info["heat_path_to_collector_m"] = round(self.path_len_mm(paths[a]) / 1000, 2)
        # приборы и лучи внутри квартир
        for ap in m.apts.values():
            rooms, issues = heatdev.place(m, self.L, rg, self.prof, self.p, ap)
            res.heat_rooms += rooms
            res.issues += issues
            if ap.idx in self.coll:
                self.beams(ap, rooms)
            for room in rooms:
                if room.devices:
                    continue
                why = heatdev.NO_DEVICE_REASON[room.status]
                if room.status == "glazing_of_neighbour":
                    near = sorted(r.room_id for r in rooms if r.devices and r.comp == room.comp)
                    why += f" ({', '.join(near)})"
                self.issue(
                    "heated_room_without_device",
                    f"{ap.number}: {room.room_id} {room.name} — отапливаемая комната без "
                    f"прибора: {why}",
                    ap,
                )

    def beams(self, ap: Apartment, rooms: list[HeatRoom]) -> None:
        """Лучи квартиры: дерево от коллектора до приборов, подача и обратка парой."""
        rg, res = self.rg, self.res
        root, xy = self.coll[ap.idx]
        info = self.apt_info(ap)
        res.nodes.append(NodeMark("M-NODE", "collector", xy, self.z_heat, ap.idx, "heating"))
        paths, along, lost = self.beam_tree(root, [d.node for r in rooms for d in r.devices])
        if lost:
            self.issue(
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
                    NodeMark("M-NODE", "device", d.xy, self.z_heat, ap.idx, "heating", room.room_id)
                )
        chains = tree_chains(rg, paths, self.simplify)
        for lay in ("M-OV-T1", "M-OV-T2"):
            self.add_chains(lay, chains, self.z_heat, ap.idx)
        info["heat_beams_m"] = round(sum(self.path_len_mm(p) for p in paths) / 1000, 2)
        res.beam_paths[ap.idx] = [
            [(float(rg.xy[n][0]), float(rg.xy[n][1])) for n in p] for p in paths
        ]

    # ---------- водоснабжение
    def water(self) -> None:
        m, rg, res = self.m, self.rg, self.res
        shafts = self._vk_mop
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
                self.add_chains(lay, chains, self.z_ceil, None, drops)
            # Т4 — по коридору до последней квартиры ветки (с каждой стороны от шахты), без вводов
            sx = sh.centroid[0]
            for side in (-1, 1):
                grp = [a for a in apt_ids if (entry[a][1][0] - sx) * side > 0]
                if not grp:
                    continue
                last = max(grp, key=lambda a: forest[entry[a][2]])
                p4 = self.path_from(forest, n0, entry[last][2])
                if p4:
                    self.riser(sh, "M-VK-T4")
                    self.leadin(sh, "M-VK-T4", self.z_ceil, n0)
                    self.add_chains(
                        "M-VK-T4", tree_chains(rg, [p4], self.simplify), self.z_ceil, None
                    )
                    self.apt_info(m.apts[last])["t4_last_of_branch"] = True
            for a in apt_ids:
                ap = m.apts[a]
                info = self.apt_info(ap)
                info["water_shaft"] = sh.id
                info["water_path_m"] = round(self.path_len_mm(paths[a]) / 1000, 2)
                res.nodes.append(NodeMark("M-NODE", "meter", entry[a][1], self.z_meter, a, "water"))

    # ---------- пожаротушение
    def fire(self) -> None:
        rg, res = self.rg, self.res
        vk = self._vk_mop
        if not self.pk_nodes or not vk:
            self.issue("fire_no_source", "пожаротушение: нет ПК или шахты ВК в МОП")
            return
        near_r = self.p.num("near_pk_dist_mm")
        near_pk = [
            s
            for s in vk
            if any(
                math.hypot(s.centroid[0] - p.c[0], s.centroid[1] - p.c[1]) < near_r
                for p in self.L.pk
            )
        ]
        best: Shaft | None = None
        bsum = math.inf
        btree: Tree | None = None
        bn0 = -1
        for sh in near_pk or vk:
            n0 = self.shaft_node(sh)
            if n0 is None:
                continue
            tree = spt(rg, [n0], self.fire_targets)
            total = float(sum(tree[n] for n in self.pk_nodes))
            if math.isfinite(total) and total < bsum:
                best, bsum, btree, bn0 = sh, total, tree, n0
        if best is None or btree is None:
            self.issue("fire_no_path", "пожаротушение: путь от шахт ВК до ПК не найден")
            return
        paths = [p for p in (node_path(btree, n) for n in self.pk_nodes) if p]
        self.riser(best, "M-PT-VPV")
        self.leadin(best, "M-PT-VPV", self.z_ceil, bn0)
        self.add_chains("M-PT-VPV", tree_chains(rg, paths, self.simplify), self.z_ceil, None)
        # АУП: ветка от той же шахты до дальних точек каждого внеквартирного помещения
        aup_rooms = aup.regions(rg, self.m, self.expl, self.p)
        ap_paths = aup.extend(rg, bn0, aup_rooms, self.p)
        if ap_paths:
            self.riser(best, "M-PT-AUP")
            self.leadin(best, "M-PT-AUP", self.z_ceil, bn0)
            self.add_chains("M-PT-AUP", tree_chains(rg, ap_paths, self.simplify), self.z_ceil, None)
        else:
            self.issue("fire_aup_no_ends", "АУП: внеквартирные помещения для ветки не найдены")
        cover = aup.coverage(rg, aup_rooms, ap_paths, self.p)
        need = self.p.num("aup_cover_min_share")
        for row in cover:
            share = row["covered_share"]
            if isinstance(share, float) and share < need:
                self.issue(
                    "aup_coverage_low",
                    f"АУП: {', '.join(str(n) for n in _names(row))} — ветка покрывает "
                    f"{share * 100:.0f} % площади (нужно не меньше {need * 100:.0f} %)",
                )
        res.fire = {
            "source_shaft": best.id,
            "pk_count": len(self.pk_nodes),
            "vpv_paths_m": [round(self.path_len_mm(p) / 1000, 2) for p in paths],
            "aup_paths_m": [round(self.path_len_mm(p) / 1000, 2) for p in ap_paths],
            "aup_coverage": cover,
        }

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
            for lay, k in d.items():
                dx = (k - (n - 1) / 2) * step
                x, y = sh.centroid[0] + dx, sh.centroid[1]
                self.res.lines.append(
                    Line3D(lay, [(x, y, self.zf), (x, y, self.zf + self.h)], None, "riser")
                )
                self.res.nodes.append(
                    NodeMark("M-RISER", "riser", (x, y), self.zf, None, SYSTEM_OF_LAYER.get(lay))
                )
                for ln in self.res.lines:
                    if (
                        ln.layer == lay
                        and ln.kind == "leadin"
                        and abs(ln.pts[0][0] - sh.centroid[0]) < 1e-6
                        and abs(ln.pts[0][1] - sh.centroid[1]) < 1e-6
                    ):
                        ln.pts[0] = (x, y, ln.pts[0][2])
            self.res.shaft_use[sid] = list(d)

    def run(self) -> Result:
        self._prepare()
        self.heating()
        self.water()
        self.fire()
        self.sewer()
        self.finalize_risers()
        return self.res
