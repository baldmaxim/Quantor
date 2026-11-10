"""Комнаты без подписи на плане: привязка по экспликации и помещения вне квартир.

Комната есть в экспликации квартиры, но её марки на плане нет. Она ищется по остатку площади:
площадь помещения минус площади подписанных в нём комнат. Кандидаты — помещения самой квартиры
(комната могла слиться с прихожей или остаться без единой марки) и смежные помещения без марок
вне квартир: до них нет двери, поэтому граф дверей их к квартире не отнёс.
"""

from __future__ import annotations

import math
import re

import numpy as np

from cad_mep.issues import Issue
from cad_mep.labels import ExplRow, Labels, RoomLabel, Word
from cad_mep.params import Params
from cad_mep.raster import nearest_true
from cad_mep.rooms import Apartment, Comp, Model

Pt = tuple[float, float]


def _fmt(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def _residual(comp: Comp, expl: dict[str, ExplRow]) -> float:
    ids = {rl.room_id for rl in comp.room_labels}
    return comp.area_m2 - sum(expl[i].area_m2 for i in ids if i in expl)


def _cells(m: Model, comp: Comp) -> tuple[np.ndarray, np.ndarray]:
    step = m.gr.step
    x0, y0 = int(comp.bbox[0] // step), int(comp.bbox[1] // step)
    x1, y1 = int(comp.bbox[2] // step) + 1, int(comp.bbox[3] // step) + 1
    ys, xs = np.nonzero(m.lab[y0:y1, x0:x1] == comp.id)
    return ys + y0, xs + x0


def _adjacent_apts(m: Model, comp: Comp, gap_mm: float) -> set[int]:
    """Квартиры, чьи помещения не дальше gap_mm от помещения (проём без двери)."""
    step = m.gr.step
    r = math.ceil(gap_mm / step)
    x0, y0 = max(int(comp.bbox[0] // step) - r, 0), max(int(comp.bbox[1] // step) - r, 0)
    x1, y1 = int(comp.bbox[2] // step) + r + 1, int(comp.bbox[3] // step) + r + 1
    win = m.lab[y0:y1, x0:x1]
    near = nearest_true(win == comp.id, r).dist <= r
    out: set[int] = set()
    for cid in np.unique(win[near]).tolist():
        other = m.comps.get(int(cid))
        if other is not None and other.apt is not None and other.id != comp.id:
            out.add(other.apt)
    return out


def _anchor(m: Model, comp: Comp, expl: dict[str, ExplRow]) -> Pt:
    """Точка комнаты без марки: центр той части помещения, что не занята подписанными комнатами.

    Подписанная комната занимает ближайшие к своей марке клетки на площадь из экспликации.
    """
    ys, xs = _cells(m, comp)
    step = m.gr.step
    px, py = (xs + 0.5) * step, (ys + 0.5) * step
    free = np.ones(len(ys), dtype=np.bool_)
    if comp.room_labels:
        dist = np.stack([np.hypot(px - rl.word.c[0], py - rl.word.c[1]) for rl in comp.room_labels])
        own = np.argmin(dist, axis=0)
        nearest = dist.min(axis=0)
        for rid in sorted({rl.room_id for rl in comp.room_labels}):
            row = expl.get(rid)
            if row is None:
                continue
            mine = np.flatnonzero(
                np.isin(own, [k for k, rl in enumerate(comp.room_labels) if rl.room_id == rid])
            )
            take = int(row.area_m2 * 1e6 / (step * step))
            free[mine[np.argsort(nearest[mine], kind="stable")[:take]]] = False
        if not free.any():  # площади марок покрыли всё: самая дальняя от марок клетка
            k = int(np.argmax(nearest))
            return (float(px[k]), float(py[k]))
    cx, cy = float(px[free].mean()), float(py[free].mean())
    idx = np.flatnonzero(free)
    k = int(idx[np.argmin(np.hypot(px[idx] - cx, py[idx] - cy))])
    return (float(px[k]), float(py[k]))


def _attach(m: Model, ap: Apartment, comp: Comp) -> None:
    """Помещение без двери — в состав квартиры; проход к нему построит трассировщик."""
    comp.apt = ap.idx
    ap.comps = sorted({*ap.comps, comp.id})
    ap.detached.append([comp.id])
    m.orphans.remove(comp.id)
    m.notes.append(
        f"{ap.number}: помещение #{comp.id} без марки и без двери присоединено по смежности"
    )


def by_area(m: Model, labels: Labels, params: Params, shift: tuple[float, float]) -> list[Issue]:
    """Сопоставляет комнаты экспликации без марки на плане с помещениями по остатку площади.

    shift — сдвиг локальных координат к координатам DXF (для адресов в замечаниях).
    """
    expl = labels.expl
    issues: list[Issue] = []
    tol = params.num("room_area_match_tol")
    min_area = params.num("min_room_area_m2")
    room_re = re.compile(params.text("room_id_regex"))
    on_plan = {rl.room_id for c in m.comps.values() for rl in c.room_labels}
    by_key = {(ap.section, ap.k): ap for ap in m.apts.values() if ap.k is not None}
    missing: dict[int, list[ExplRow]] = {}
    for rid in sorted(expl):
        mm = room_re.match(rid)
        if rid in on_plan or not mm or mm.group(3) != "/":
            continue
        owner = by_key.get((mm.group(1), int(mm.group(2))))
        if owner is not None:
            missing.setdefault(owner.idx, []).append(expl[rid])
    gap = params.num("virtual_max_gap_mm")
    near = {cid: _adjacent_apts(m, m.comps[cid], gap) for cid in m.orphans} if missing else {}
    # (расхождение, комната, помещение, квартира)
    pairs: list[tuple[float, str, int, int]] = []
    for ai, rows in missing.items():
        own = [
            c
            for c in m.apts[ai].comps
            if m.comps[c].kind in ("room", "unlabeled") and m.comps[c].area_m2 >= min_area
        ]
        for cid in [*own, *(c for c in m.orphans if ai in near[c])]:
            resid = _residual(m.comps[cid], expl)
            for row in rows:
                err = abs(resid - row.area_m2) / row.area_m2
                if err <= tol:
                    pairs.append((err, row.room_id, cid, ai))
    pairs.sort()
    rooms_done: set[str] = set()
    comps_done: set[int] = set()
    for err, rid, cid, ai in pairs:
        if rid in rooms_done or cid in comps_done:
            continue
        rooms_done.add(rid)
        comps_done.add(cid)
        comp, ap, row = m.comps[cid], m.apts[ai], expl[rid]
        resid = _residual(comp, expl)
        mm = room_re.match(rid)
        x, y = _anchor(m, comp, expl)
        neighbours = sorted({rl.room_id for rl in comp.room_labels})
        comp.room_labels.append(
            RoomLabel(
                Word(rid, x, y, x, y, (0.0, 0.0, 0.0, 0.0)),
                rid,
                mm.group(1) if mm else ap.section,
                ap.k,
                False,
                assigned=True,
            )
        )
        comp.kind = "room"
        where = f"помещение #{cid}"
        if neighbours:
            where += f" (общее с {', '.join(neighbours)})"
        if comp.apt is None:
            _attach(m, ap, comp)
            where += ", без двери — присоединено к квартире по смежности"
        rivals = sorted(
            {f"{r} ↔ #{c}" for e, r, c, _a in pairs if (r == rid) != (c == cid) and e <= tol}
        )
        issues.append(
            Issue(
                "room_assigned_by_area",
                f"{ap.number}: {rid} {row.name} — марки на плане нет, отнесена по площади: "
                f"{where}; экспликация {_fmt(row.area_m2)} м², остаток площади помещения "
                f"{_fmt(resid)} м² "
                f"(расхождение {err * 100:.1f} %)"
                + (f"; неоднозначно, подходило также: {'; '.join(rivals)}" if rivals else ""),
                ap.number,
            )
        )
    left = [m.comps[c] for c in m.orphans if m.comps[c].area_m2 >= min_area]
    if left:
        listing = "; ".join(
            f"#{c.id} — {_fmt(c.area_m2)} м², центр ({c.centroid[0] + shift[0]:.0f}, "
            f"{c.centroid[1] + shift[1]:.0f}) мм DXF"
            for c in left
        )
        issues.append(
            Issue(
                "rooms_outside_apartments",
                "помещения без марки не отнесены ни к одной квартире, трассы в них не ведутся: "
                + listing,
            )
        )
    return issues
