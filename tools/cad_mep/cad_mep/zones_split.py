"""Разделение слитых помещений: одна область детектора с несколькими марками режется линиями плана.

Открытая планировка (кухня-гостиная, прихожая с коридором) не разделена стеной: детектор помещений
даёт одну область на несколько марок экспликации. Границей между ними служит тонкая чёрная линия
плана; по ней на тонком растре ставится барьер, и области делятся по маркам.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from cad_mep import zones_const as zc
from cad_mep.dxfin import Door
from cad_mep.labels import ExplRow, RoomLabel
from cad_mep.raster import IntArr, label
from cad_mep.rooms import Comp, Model
from cad_mep.zones_lines import BoundaryLines, Line, is_door_leaf
from cad_mep.zones_poly import largest
from cad_mep.zones_raster import Field, Window, barrier_mask, part_areas

PartMarks = dict[int, list[str]]


def window_of(c: Comp, fld: Field) -> Window:
    """Окно обработки помещения в клетках тонкого растра (рамка + запас)."""
    x0, y0, x1, y1 = c.bbox
    f, pad = fld.f, zc.WINDOW_PAD_PX
    return (
        max(int(x0 // f) - pad, 0),
        max(int(y0 // f) - pad, 0),
        min(int(x1 // f) + pad + 1, fld.nx),
        min(int(y1 // f) + pad + 1, fld.ny),
    )


def cells_polygon(model: Model, cid: int) -> Polygon:
    """Многоугольник из клеток детектора помещения (локальные мм)."""
    step = model.gr.step
    mask = model.lab == cid
    boxes = []
    for iy in np.flatnonzero(mask.any(axis=1)):
        d = np.diff(np.concatenate(([0], mask[iy].astype(np.int8), [0])))
        for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1), strict=True):
            boxes.append(box(a * step, iy * step, b * step, (iy + 1) * step))
    union = unary_union(boxes)
    if isinstance(union, Polygon):
        return union
    biggest = largest(union)
    if biggest is None:
        raise ValueError("пустая маска помещения")
    return biggest


def mark_part(lab2: IntArr, win: Window, fld: Field, rl: RoomLabel) -> int:
    """Метка части, в которой лежит марка (или ближайшей к ней не дальше MARK_SNAP_MM); 0 — нет."""
    f = fld.f
    x, y = rl.word.c
    ix, iy = int(x // f) - win[0], int(y // f) - win[1]
    if 0 <= iy < lab2.shape[0] and 0 <= ix < lab2.shape[1] and lab2[iy, ix]:
        return int(lab2[iy, ix])
    r = int(zc.MARK_SNAP_MM / f)
    ya, yb = max(iy - r, 0), min(iy + r + 1, lab2.shape[0])
    xa, xb = max(ix - r, 0), min(ix + r + 1, lab2.shape[1])
    sub = lab2[ya:yb, xa:xb]
    ys, xs = np.nonzero(sub)
    if len(ys) == 0:
        return 0
    d = np.hypot(ys + ya - iy, xs + xa - ix)
    k = int(np.argmin(d))
    if d[k] * f > zc.MARK_SNAP_MM:
        return 0
    return int(sub[ys[k], xs[k]])


def adjacency(lab2: IntArr, a: int, reach: int = 3) -> dict[int, int]:
    """Соседи части a (метки > 0) и число их клеток в кольце шириной reach вокруг неё."""
    ys, xs = np.nonzero(lab2 == a)
    y0, y1 = max(ys.min() - reach - 1, 0), ys.max() + reach + 2
    x0, x1 = max(xs.min() - reach - 1, 0), xs.max() + reach + 2
    sub = lab2[y0:y1, x0:x1]
    m = sub == a
    cur = m.copy()
    for _ in range(reach):
        nxt = cur.copy()
        nxt[1:] |= cur[:-1]
        nxt[:-1] |= cur[1:]
        nxt[:, 1:] |= cur[:, :-1]
        nxt[:, :-1] |= cur[:, 1:]
        cur = nxt
    vals = sub[cur & ~m]
    vals = vals[(vals > 0) & (vals != a)]
    uniq, counts = np.unique(vals, return_counts=True)
    return {int(v): int(c) for v, c in zip(uniq, counts, strict=True)}


class LineIndex:
    """Пространственный индекс линий границ: какие линии заходят внутрь маски помещения."""

    def __init__(self, lines: list[Line], step: float) -> None:
        self.lines = lines
        self.geos = [LineString([(ln[0], ln[1]), (ln[2], ln[3])]) for ln in lines]
        self.tree = STRtree(self.geos)
        self.step = step

    def inside(self, polygon: Polygon, inside_min: float) -> list[Line]:
        inner = polygon.buffer(-self.step / 2, join_style="mitre")
        if inner.is_empty:
            inner = polygon
        out: list[Line] = []
        for i in self.tree.query(polygon.buffer(40)):
            if self.geos[int(i)].intersection(inner).length >= inside_min:
                out.append(self.lines[int(i)])
        return out


class Splitter:
    """Состояние разметки: растр меток, марки по комнатам, замечания по помещениям."""

    def __init__(
        self,
        fld: Field,
        model: Model,
        expl: dict[str, ExplRow],
        lines: BoundaryLines,
        doors: list[Door],
        comp_marks: dict[int, list[RoomLabel]],
    ) -> None:
        self.fld = fld
        self.model = model
        self.expl = expl
        self.doors = doors
        self.comp_marks = comp_marks
        self.main = LineIndex(lines.main, model.gr.step)
        self.relax = LineIndex(lines.relax, model.gr.step)
        self.mark_seed: dict[str, int] = {}  # марка -> метка области в поле
        self.part_apt: dict[int, int | None] = {}  # метка выделенной части -> квартира
        self.comp_notes: dict[int, list[str]] = defaultdict(list)
        self.next_id = max(100000, int(model.lab.max()) + 1)

    # --- маски помещений
    def prune_comp(self, c: Comp) -> None:
        """Из стартовой маски убираем клетки под препятствиями; отрезанные и малые куски — прочь."""
        fld = self.fld
        win = window_of(c, fld)
        wx0, wy0, wx1, wy1 = win
        sub = fld.gi[wy0:wy1, wx0:wx1]
        m = sub == c.id
        cut = m & fld.obst[wy0:wy1, wx0:wx1]
        lab_, n = label(m & ~cut)
        if n == 0:
            return
        areas = part_areas(lab_, n, fld.f)[1:]
        big = areas.max()
        marked = {mark_part(lab_, win, fld, rl) for rl in self.comp_marks[c.id] if not rl.assigned}
        keep_ids = [
            i + 1
            for i, a in enumerate(areas)
            if a >= zc.PRUNE_KEEP_RATIO * big or (i + 1) in marked or a >= zc.PRUNE_KEEP_M2
        ]
        dropped = float(sum(a for i, a in enumerate(areas) if (i + 1) not in keep_ids))
        sub[m] = 0
        sub[cut] = -1
        sub[np.isin(lab_, keep_ids)] = c.id
        if dropped > 0.02:
            self.comp_notes[c.id].append(
                f"отсечено масок за препятствиями: {n - len(keep_ids)} кусков, {dropped:.2f} м²"
            )

    def _try_split(self, c: Comp, used: list[Line], win: Window) -> tuple[IntArr, int]:
        wx0, wy0, wx1, wy1 = win
        mask = self.fld.gi[wy0:wy1, wx0:wx1] == c.id
        return label(mask & ~barrier_mask(used, win, self.fld))

    def _classify(self, lab2: IntArr, win: Window, placed: list[RoomLabel]) -> PartMarks:
        pm: PartMarks = defaultdict(list)
        for rl in placed:
            pm[mark_part(lab2, win, self.fld, rl)].append(rl.room_id)
        return pm

    # --- разделение
    def process_comp(self, c: Comp) -> None:
        """Режет помещение с несколькими марками на части и записывает их в поле меток."""
        fld = self.fld
        labels_all = self.comp_marks[c.id]
        placed = [rl for rl in labels_all if not rl.assigned]
        unplaced = sorted({rl.room_id for rl in labels_all if rl.assigned})
        notes = self.comp_notes[c.id]
        win = window_of(c, fld)
        wx0, wy0, wx1, wy1 = win
        poly = cells_polygon(self.model, c.id)
        found = self.main.inside(poly, zc.LINE_INSIDE_MM)
        used = [ln for ln in found if not is_door_leaf(ln, self.doors)]
        if len(found) != len(used):
            notes.append(f"отброшено линий полотен дверей: {len(found) - len(used)}")
        lab2, n = self._try_split(c, used, win)
        pm = self._classify(lab2, win, placed)
        # эскалация: части с >= 2 марок -> добавляем следующие ближайшие линии
        pool = [
            ln
            for ln in self.relax.inside(poly, zc.RELAX_INSIDE_MM)
            if ln not in used and not is_door_leaf(ln, self.doors)
        ]
        guard = 0
        while any(len(v) >= 2 for p, v in pm.items() if p) and pool and guard < zc.ESCALATION_LIMIT:
            guard += 1
            bad = next(v for p, v in pm.items() if p and len(v) >= 2)
            pts = [rl.word.c for rl in placed if rl.room_id in bad]
            mid = Point(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            pool.sort(key=lambda ln: LineString([(ln[0], ln[1]), (ln[2], ln[3])]).distance(mid))
            added = False
            for ln in list(pool[: zc.ESCALATION_TRY]):
                pool.remove(ln)
                lab3, n3 = self._try_split(c, [*used, ln], win)
                pm3 = self._classify(lab3, win, placed)
                if sum(len(v) >= 2 for v in pm3.values()) < sum(len(v) >= 2 for v in pm.values()):
                    used.append(ln)
                    lab2, n, pm = lab3, n3, pm3
                    x0, y0, x1, y1 = ln
                    notes.append(
                        f"добавлена запасная линия ({x0:.0f},{y0:.0f})-({x1:.0f},{y1:.0f})"
                    )
                    added = True
                    break
            if not added:
                break
        part_marks: PartMarks = {p: pm.get(p, []) for p in range(1, n + 1)}
        self._merge_tiny(lab2, n, part_marks)
        areas = part_areas(lab2, n, fld.f)
        live = [p for p in part_marks if (lab2 == p).any()]
        free_parts = [p for p in live if not part_marks[p]]
        unplaced_left = self._parts_by_area(free_parts, unplaced, areas, part_marks, notes)
        free_parts = [p for p in live if not part_marks[p]]
        for p in free_parts:
            self._report_free_part(lab2, p, areas, part_marks, win, notes)
        live = [p for p in part_marks if (lab2 == p).any() and part_marks[p]]
        areas = part_areas(lab2, n, fld.f)
        sub = fld.gi[wy0:wy1, wx0:wx1]
        sub[sub == c.id] = 0  # барьеры и клочки — свободны, их занимает рост
        for p in live:
            marks_p = sorted(part_marks[p])
            pid = self.next_id
            self.next_id += 1
            sub[lab2 == p] = pid
            self.part_apt[pid] = c.apt
            for m in marks_p:
                self.mark_seed[m] = pid
            if len(marks_p) > 1:
                notes.append(f"НЕ РАЗДЕЛЕНО: {', '.join(marks_p)}")
        for m in unplaced_left:
            notes.append(f"{m}: отдельной части не нашлось")

    def _merge_tiny(self, lab2: IntArr, n: int, part_marks: PartMarks) -> None:
        """Клочки без марки меньше TINY_PART_M2 присоединяются к самому длинному соседу."""
        changed = True
        while changed:
            changed = False
            areas = part_areas(lab2, n, self.fld.f)
            cands = sorted(
                (p for p in part_marks if not part_marks[p] and (lab2 == p).any()),
                key=lambda p: areas[p],
            )
            for p in cands:
                if areas[p] >= zc.TINY_PART_M2:
                    continue
                adj = adjacency(lab2, p)
                labeled = {q: v for q, v in adj.items() if part_marks.get(q)}
                pick: int | None = None
                if labeled:
                    pick = max(labeled, key=lambda q: labeled[q])
                elif adj:
                    pick = max(adj, key=lambda q: adj[q])
                if pick is None:
                    lab2[lab2 == p] = 0  # изолированный клочок: пусть решает рост
                else:
                    lab2[lab2 == p] = pick
                    part_marks.setdefault(pick, [])
                part_marks.pop(p, None)
                changed = True
                break

    def _parts_by_area(
        self,
        free_parts: list[int],
        unplaced: list[str],
        areas: NDArray[np.float64],
        part_marks: PartMarks,
        notes: list[str],
    ) -> list[str]:
        """Марки без позиции на плане -> безымянные части по минимальному расхождению площадей."""
        if not (free_parts and unplaced):
            return list(unplaced)
        expl = self.expl
        pairs = sorted(
            (abs(areas[p] - expl[m].area_m2) / expl[m].area_m2, p, m)
            for p in free_parts
            for m in unplaced
        )
        used_p: set[int] = set()
        used_m: set[str] = set()
        for _err, p, m in pairs:
            if p in used_p or m in used_m:
                continue
            part_marks[p] = [m]
            used_p.add(p)
            used_m.add(m)
            notes.append(
                f"{m}: марки на плане нет, часть по площади ({areas[p]:.2f} м² при "
                f"{expl[m].area_m2:.2f})"
            )
        return [m for m in unplaced if m not in used_m]

    def _report_free_part(
        self,
        lab2: IntArr,
        p: int,
        areas: NDArray[np.float64],
        part_marks: PartMarks,
        win: Window,
        notes: list[str],
    ) -> None:
        """Крупная часть без марки: отчёт и слияние с соседней частью, у которой марка есть."""
        adj = adjacency(lab2, p)
        labeled = {q: v for q, v in adj.items() if part_marks.get(q)}
        if not labeled:
            notes.append(f"ОТЧЁТ: часть без марки {areas[p]:.2f} м² изолирована")
            return
        ys, xs = np.nonzero(lab2 == p)
        f = self.fld.f
        notes.append(
            f"ОТЧЁТ: часть без марки {areas[p]:.2f} м² (центр {xs.mean() * f + win[0] * f:.0f},"
            f"{ys.mean() * f + win[1] * f:.0f} мм) слита в соседнюю"
        )
        pick = max(labeled, key=lambda q: labeled[q])
        lab2[lab2 == p] = pick
        part_marks.pop(p, None)

    def run(self) -> None:
        """Очистка масок и разделение; одиночные марки сеют свою область целиком."""
        model = self.model
        for cid in self.comp_marks:
            self.prune_comp(model.comps[cid])
        multi = {
            cid
            for cid, marks in self.comp_marks.items()
            if len({rl.room_id for rl in marks}) >= 2 and model.comps[cid].kind == "room"
        }
        for cid in sorted(multi):
            self.process_comp(model.comps[cid])
        for cid, marks in self.comp_marks.items():
            if cid not in multi:
                for rl in marks:
                    self.mark_seed[rl.room_id] = cid

    def label_apt(self, lbl: int) -> int | None:
        """Квартира области по метке (помещение детектора или выделенная часть)."""
        if lbl in self.part_apt:
            return self.part_apt[lbl]
        cc = self.model.comps.get(lbl)
        return cc.apt if cc else None
