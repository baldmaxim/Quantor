"""Линии плана для зон: отрезки штрихов в локальных мм, слияние, оси, дуги дверей, границы."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from cad_mep import zones_const as zc
from cad_mep.dxfin import Door
from cad_mep.frame import Frame
from cad_mep.pdfsrc import Strokes

FloatArr = NDArray[np.float64]
BoolArr = NDArray[np.bool_]
Line = tuple[float, float, float, float]  # xa, ya, xb, yb


@dataclass
class Segs:
    """Отрезки штрихов в локальных мм (x1, y1, x2, y2) и признаки штриха."""

    x1: FloatArr
    y1: FloatArr
    x2: FloatArr
    y2: FloatArr
    width: FloatArr
    black: BoolArr
    dark: BoolArr
    solid: BoolArr

    @property
    def length(self) -> FloatArr:
        out: FloatArr = np.hypot(self.x2 - self.x1, self.y2 - self.y1)
        return out


def localize(st: Strokes, frame: Frame) -> Segs:
    a = frame.pts_to_dxf(st.seg[:, :2])
    b = frame.pts_to_dxf(st.seg[:, 2:])
    return Segs(
        a[:, 0] - frame.x0,
        a[:, 1] - frame.y0,
        b[:, 0] - frame.x0,
        b[:, 1] - frame.y0,
        st.width,
        st.black,
        st.dark,
        st.solid,
    )


def label_frame_mask(seg_pt: FloatArr, boxes: list[tuple[float, float, float, float]]) -> BoolArr:
    """Отрезки, целиком лежащие в рамке (с запасом) подписи помещения: это буквы, не линии плана."""
    inside: BoolArr = np.zeros(len(seg_pt), dtype=np.bool_)
    xmin, xmax = np.minimum(seg_pt[:, 0], seg_pt[:, 2]), np.maximum(seg_pt[:, 0], seg_pt[:, 2])
    ymin, ymax = np.minimum(seg_pt[:, 1], seg_pt[:, 3]), np.maximum(seg_pt[:, 1], seg_pt[:, 3])
    pad = zc.LABEL_FRAME_PAD_PT
    for x0, y0, x1, y1 in boxes:
        inside |= (xmin >= x0 - pad) & (xmax <= x1 + pad) & (ymin >= y0 - pad) & (ymax <= y1 + pad)
    return inside


def _merge_intervals(items: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    items.sort()
    res: list[list[float]] = []
    for a, b in items:
        if res and a <= res[-1][1] + gap:
            res[-1][1] = max(res[-1][1], b)
        else:
            res.append([a, b])
    return [(a, b) for a, b in res]


def _cluster(coord: FloatArr, tol: float = 2.5, spread: float = 6.0) -> NDArray[np.int64]:
    order = np.argsort(coord)
    gid = np.zeros(len(coord), dtype=np.int64)
    g = 0
    start = coord[order[0]] if len(order) else 0.0
    prev = start
    for k in order:
        c = coord[k]
        if c - prev > tol or c - start > spread:
            g += 1
            start = c
        prev = c
        gid[k] = g
    return gid


def merge_lines(
    x1: FloatArr,
    y1: FloatArr,
    x2: FloatArr,
    y2: FloatArr,
    min_len_mm: float,
    gap_mm: float = zc.MERGE_GAP_MM,
) -> list[Line]:
    """Слияние коллинеарных отрезков в максимальные прямые; короче min_len_mm не берём."""
    dx, dy = x2 - x1, y2 - y1
    ln = np.hypot(dx, dy)
    keep = ln > 1.0
    x1, y1, x2, y2, dx, dy, ln = (a[keep] for a in (x1, y1, x2, y2, dx, dy, ln))
    ang = np.degrees(np.arctan2(dy, dx)) % 180.0
    horiz = (ang < 0.25) | (ang > 179.75)
    vert = np.abs(ang - 90.0) < 0.25
    out: list[Line] = []
    for mask, axis in ((horiz, 0), (vert, 1)):
        if not mask.any():
            continue
        if axis == 0:
            coord = (y1[mask] + y2[mask]) / 2
            a0, a1 = np.minimum(x1[mask], x2[mask]), np.maximum(x1[mask], x2[mask])
        else:
            coord = (x1[mask] + x2[mask]) / 2
            a0, a1 = np.minimum(y1[mask], y2[mask]), np.maximum(y1[mask], y2[mask])
        gid = _cluster(coord)
        for g in np.unique(gid):
            sel = gid == g
            c = float(coord[sel].mean())
            for a, b in _merge_intervals(
                list(zip(a0[sel].tolist(), a1[sel].tolist(), strict=True)), gap_mm
            ):
                if b - a >= min_len_mm:
                    out.append((a, c, b, c) if axis == 0 else (c, a, c, b))
    # неортогональные: только длинные «сырые» отрезки (дуги остекления — мелкие)
    rest = ~(horiz | vert) & (ln >= 35.0)
    if rest.any():
        th = np.radians(ang[rest])
        rho = -x1[rest] * np.sin(th) + y1[rest] * np.cos(th)
        t1 = x1[rest] * np.cos(th) + y1[rest] * np.sin(th)
        t2 = x2[rest] * np.cos(th) + y2[rest] * np.sin(th)
        keys = np.stack([np.round(ang[rest] / 0.5), np.round(rho / 4.0)], axis=1)
        groups: dict[tuple[float, float], list[int]] = {}
        for i, k in enumerate(keys.tolist()):
            groups.setdefault((k[0], k[1]), []).append(i)
        for idx in groups.values():
            ii = np.array(idx)
            thm, rhm = float(th[ii].mean()), float(rho[ii].mean())
            spans = list(
                zip(
                    np.minimum(t1[ii], t2[ii]).tolist(),
                    np.maximum(t1[ii], t2[ii]).tolist(),
                    strict=True,
                )
            )
            for a, b in _merge_intervals(spans, gap_mm):
                if b - a >= min_len_mm:
                    c, s = math.cos(thm), math.sin(thm)
                    out.append((a * c - rhm * s, a * s + rhm * c, b * c - rhm * s, b * s + rhm * c))
    return out


def door_arc_mask(seg: Segs, doors: list[Door]) -> BoolArr:
    """Хорды дуг створок: тонкие короткие отрезки вокруг петли двери на радиусе полотна."""
    arc: BoolArr = np.zeros(len(seg.x1), dtype=np.bool_)
    slen = seg.length
    short = slen <= zc.DOOR_ARC_MAX_CHORD_MM
    mx, my = (seg.x1 + seg.x2) / 2, (seg.y1 + seg.y2) / 2
    dxs, dys = seg.x2 - seg.x1, seg.y2 - seg.y1
    tol = zc.DOOR_ARC_RADIUS_TOL_MM
    for d in doors:
        for hx, hy in (d.a, d.b):
            r = d.width
            d1 = np.hypot(seg.x1 - hx, seg.y1 - hy)
            d2 = np.hypot(seg.x2 - hx, seg.y2 - hy)
            rad = np.hypot(mx - hx, my - hy) + 1e-9
            cosang = np.abs(dxs * (mx - hx) + dys * (my - hy)) / (slen + 1e-9) / rad
            arc |= short & (np.abs(d1 - r) < tol) & (np.abs(d2 - r) < tol) & (cosang < 0.6)
    return arc


def _axis_groups(cc: FloatArr, sel: BoolArr) -> list[list[int]]:
    idx = np.flatnonzero(sel)
    order = idx[np.argsort(cc[idx])]
    groups: list[list[int]] = []
    for i in order:
        if groups and cc[i] - cc[groups[-1][0]] <= zc.AXIS_CLUSTER_MM:
            groups[-1].append(int(i))
        else:
            groups.append([int(i)])
    return groups


def axis_mask(seg: Segs) -> BoolArr:
    """Оси здания — штрихпунктир: цепочка «длинный, щель, короткий…» сплошных тёмных отрезков."""
    ax: BoolArr = np.zeros(len(seg.x1), dtype=np.bool_)
    base = seg.dark & seg.solid & (seg.width >= zc.INK_WIDTH_MIN_PT)
    ln = seg.length
    hz = base & (np.abs(seg.y1 - seg.y2) < 1.0) & (ln > 1.0)
    vt = base & (np.abs(seg.x1 - seg.x2) < 1.0) & (ln > 1.0)
    for sel, cc, a0, a1 in (
        (hz, (seg.y1 + seg.y2) / 2, np.minimum(seg.x1, seg.x2), np.maximum(seg.x1, seg.x2)),
        (vt, (seg.x1 + seg.x2) / 2, np.minimum(seg.y1, seg.y2), np.maximum(seg.y1, seg.y2)),
    ):
        for gi in _axis_groups(cc, sel):
            merged = _merge_intervals([(float(a0[i]), float(a1[i])) for i in gi], zc.MERGE_GAP_MM)
            chain = [merged[0]]
            chains: list[list[tuple[float, float]]] = []
            for m in merged[1:]:
                gap = m[0] - chain[-1][1]
                if zc.AXIS_GAP_MIN_MM <= gap <= zc.AXIS_GAP_MAX_MM:
                    chain.append(m)
                else:
                    chains.append(chain)
                    chain = [m]
            chains.append(chain)
            for ch in chains:
                longs = sum(1 for a, b in ch if b - a >= zc.AXIS_LONG_MM)
                shorts = sum(1 for a, b in ch if b - a <= zc.AXIS_SHORT_MM)
                if len(ch) >= 3 and longs >= 1 and shorts >= 1:
                    lo, hi = ch[0][0] - 3.0, ch[-1][1] + 3.0
                    ax |= sel & (np.abs(cc - cc[gi[0]]) < 5.0) & (a0 >= lo) & (a1 <= hi)
    return ax


@dataclass
class BoundaryLines:
    """Линии границ помещений: основные (тонкая чёрная сплошная) и запасные (чуть шире допуска)."""

    main: list[Line]
    relax: list[Line]


def boundary_lines(seg: Segs, skip: BoolArr) -> BoundaryLines:
    """skip — рамки подписей и оси: из линий границ исключаются."""
    base = seg.black & seg.solid & ~skip
    main_sel = base & (np.abs(seg.width - zc.SPLIT_WIDTH_PT) < zc.SPLIT_WIDTH_TOL_PT)
    relax_sel = base & (seg.width >= zc.RELAX_WIDTH_MIN_PT) & (seg.width <= zc.RELAX_WIDTH_MAX_PT)
    return BoundaryLines(
        merge_lines(
            seg.x1[main_sel], seg.y1[main_sel], seg.x2[main_sel], seg.y2[main_sel], zc.MIN_LINE_MM
        ),
        merge_lines(
            seg.x1[relax_sel],
            seg.y1[relax_sel],
            seg.x2[relax_sel],
            seg.y2[relax_sel],
            zc.RELAX_MIN_LINE_MM,
        ),
    )


def is_door_leaf(line: Line, doors: list[Door]) -> bool:
    """Линия от петли двери, не лежащая вдоль проёма и не длиннее полотна, — створка, не граница."""
    ends = (((line[0], line[1]), (line[2], line[3])), ((line[2], line[3]), (line[0], line[1])))
    for hinge in (p for d in doors for p in (d.a, d.b)):
        for (px, py), (qx, qy) in ends:
            if math.hypot(px - hinge[0], py - hinge[1]) >= zc.DOOR_LEAF_NEAR_MM:
                continue
            for d in doors:
                if math.hypot(hinge[0] - d.a[0], hinge[1] - d.a[1]) >= 1 and (
                    math.hypot(hinge[0] - d.b[0], hinge[1] - d.b[1]) >= 1
                ):
                    continue
                ux, uy = d.b[0] - d.a[0], d.b[1] - d.a[1]
                n = math.hypot(ux, uy) or 1.0
                lx, ly = qx - px, qy - py
                ln = math.hypot(lx, ly) or 1.0
                if abs(ux * lx + uy * ly) / n / ln < 0.9 and ln < zc.DOOR_LEAF_MAX_RATIO * d.width:
                    return True
    return False
