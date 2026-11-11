"""Машино-места паркинга по серым векторам листа: поиск, тип по легенде, разметка для zones.json.

Место — полоса между двумя параллельными «рельсами» (серые линии 4,3-6,8 м) с глифом машины внутри
(мелкие серые пути). Пары ищутся под любым углом. Тип места — по легенде листа (parking_legend).
Результат — кандидат: размеры считаются по калибровке масштаба листа, не по подписям чертежа.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.strtree import STRtree

from cad_mep import parking_const as pc
from cad_mep.parking_legend import F64, Classified, PathIndex, Zone, classify, find_templates
from cad_mep.pdfsrc import ParkingPage, read_parking_page

I64 = NDArray[np.int64]


@dataclass(frozen=True)
class Stall:
    """Кандидат в место: вершины в пт листа, размеры в метрах, число кусков глифа."""

    corners: F64  # (4, 2)
    width_m: float
    length_m: float
    glyph: int


def _in_zone(pts: F64, zone: Zone) -> NDArray[np.bool_]:
    return (
        (pts[:, 0] >= zone[0])
        & (pts[:, 0] <= zone[2])
        & (pts[:, 1] >= zone[1])
        & (pts[:, 1] <= zone[3])
    )


def _rails(idx: PathIndex, zone: Zone, k: float) -> tuple[F64, F64]:
    """Рельсы в рамке плана (концы a, b в пт): серые линии нужной длины без повторов."""
    chunks = [
        p.segs
        for p, c in zip(idx.paths, idx.centers, strict=True)
        if not p.hatch and len(p.segs) and zone[0] <= c[0] <= zone[2] and zone[1] <= c[1] <= zone[3]
    ]
    segs = np.concatenate(chunks) if chunks else np.zeros((0, 4))
    length = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1]) * k
    segs = segs[(length >= pc.RAIL_MIN_M) & (length <= pc.RAIL_MAX_M)]
    a, b = segs[:, :2], segs[:, 2:]
    swap = (a[:, 0] > b[:, 0]) | ((a[:, 0] == b[:, 0]) & (a[:, 1] > b[:, 1]))
    key = np.round(
        np.where(swap[:, None], np.hstack([b, a]), np.hstack([a, b])), pc.RAIL_KEY_DIGITS
    )
    keep = np.sort(np.unique(key, axis=0, return_index=True)[1])
    a, b = a[keep], b[keep]
    inside = _in_zone((a + b) / 2, zone)
    return a[inside], b[inside]


def _pairs(a: F64, b: F64, k: float) -> tuple[I64, I64, F64]:
    """Пары рельс (i, j) и знаковое расстояние s от i до j: параллельны, с общей частью."""
    vec = b - a
    ln = np.hypot(vec[:, 0], vec[:, 1])
    u = vec / ln[:, None]
    reach = pc.PAIR_SEARCH_M / k
    lo, hi = np.minimum(a, b) - reach, np.maximum(a, b) + reach
    tree = STRtree(np.asarray(shapely.linestrings(np.stack([a, b], axis=1)), dtype=object))
    i, j = tree.query(shapely.box(lo[:, 0], lo[:, 1], hi[:, 0], hi[:, 1]))
    sel = i != j
    i, j = i[sel], j[sel]
    sin = np.abs(u[i, 0] * vec[j, 1] - u[i, 1] * vec[j, 0]) / ln[j]
    nrm = np.stack([-u[:, 1], u[:, 0]], axis=1)
    s = (((a[j] + b[j]) / 2 - a[i]) * nrm[i]).sum(axis=1)
    pa, pb = ((a[j] - a[i]) * u[i]).sum(axis=1), ((b[j] - a[i]) * u[i]).sum(axis=1)
    over = np.minimum(ln[i], np.maximum(pa, pb)) - np.maximum(0.0, np.minimum(pa, pb))
    ok = (sin <= pc.PAIR_PARALLEL_SIN_MAX) & (np.abs(s) * k >= pc.PAIR_NEAR_MIN_M)
    ok &= over >= pc.PAIR_OVERLAP_MIN * np.minimum(ln[i], ln[j])
    return i[ok], j[ok], s[ok]


def _bands(a: F64, b: F64, k: float) -> tuple[F64, F64]:
    """Полосы между ближайшими рельсами каждой стороны: вершины (m, 4, 2) в пт и ширины в м."""
    i, j, s = _pairs(a, b, k)
    side = (s > 0).astype(np.int64)
    order = np.lexsort((np.abs(s), i * 2 + side))
    first = np.unique((i * 2 + side)[order], return_index=True)[1]
    i, j, s = i[order][first], j[order][first], s[order][first]
    width = np.abs(s) * k
    ok = (width >= pc.PAIR_WIDTH_MIN_M) & (width <= pc.PAIR_WIDTH_MAX_M)
    i, j, s, width = i[ok], j[ok], s[ok], width[ok]
    vec = b[i] - a[i]
    ln = np.hypot(vec[:, 0], vec[:, 1])
    u = vec / ln[:, None]
    nrm = np.stack([-u[:, 1], u[:, 0]], axis=1)
    pa, pb = ((a[j] - a[i]) * u).sum(axis=1), ((b[j] - a[i]) * u).sum(axis=1)
    lo, hi = np.maximum(0.0, np.minimum(pa, pb)), np.minimum(ln, np.maximum(pa, pb))
    p0, p1 = a[i] + u * lo[:, None], a[i] + u * hi[:, None]
    shift = nrm * s[:, None]
    return np.stack([p0, p1, p1 + shift, p0 + shift], axis=1), width


def _dedupe(quads: F64, width: F64) -> tuple[F64, F64]:
    """Полосы с центром в одной клетке — одно место."""
    c = quads.mean(axis=1)
    cell = np.round(c / pc.BAND_CENTER_CELL_PT)
    keep = np.sort(np.unique(cell, axis=0, return_index=True)[1])
    return quads[keep], width[keep]


def _glyph_counts(idx: PathIndex, quads: F64, zone: Zone, k: float) -> I64:
    """Кусков глифа (мелкие серые пути) внутри каждой полосы."""
    small = ~idx.hatch & (idx.maxside * k < pc.GLYPH_PIECE_MAX_M) & _in_zone(idx.centers, zone)
    pts = np.asarray(shapely.points(idx.centers[small]), dtype=object)
    polys = np.asarray(shapely.polygons(quads), dtype=object)
    pair = STRtree(pts).query(polys, predicate="contains")
    return np.bincount(pair[0], minlength=len(quads)).astype(np.int64)


def _suppress(quads: F64, width: F64, glyph: I64) -> list[int]:
    """Номера принятых полос: узкие раньше, при равенстве больше глифа; перекрытие до доли."""
    polys = np.asarray(shapely.polygons(quads), dtype=object)
    area = np.asarray(shapely.area(polys), dtype=np.float64)
    tree = STRtree(polys)
    accepted: list[int] = []
    taken = np.zeros(len(quads), dtype=np.bool_)
    for n in np.lexsort((-glyph, width)):
        near = tree.query(polys[n])
        near = near[taken[near]]
        inter = np.asarray(shapely.area(shapely.intersection(polys[n], polys[near])))
        if np.all(inter <= pc.NMS_OVERLAP_MAX * np.minimum(area[n], area[near])):
            taken[n] = True
            accepted.append(int(n))
    return accepted


def find_stalls(idx: PathIndex, zone: Zone, scale_mm_per_pt: float) -> list[Stall]:
    """Места в рамке плана: пары рельс, глиф внутри, без перекрытий."""
    k = scale_mm_per_pt / 1000.0
    a, b = _rails(idx, zone, k)
    if len(a) < 2:
        return []
    quads, width = _dedupe(*_bands(a, b, k))
    if len(quads) == 0:
        return []
    glyph = _glyph_counts(idx, quads, zone, k)
    good = glyph >= pc.GLYPH_PIECES_MIN
    quads, width, glyph = quads[good], width[good], glyph[good]
    out = []
    for n in _suppress(quads, width, glyph):
        e = np.hypot(*(quads[n, 1] - quads[n, 0])) * k
        out.append(Stall(quads[n], float(width[n]), float(e), int(glyph[n])))
    return out


def _norm(page: ParkingPage, corners: F64) -> list[list[float]]:
    """Вершины в долях экранной (повёрнутой) страницы от левого верхнего угла (6 знаков)."""
    m = page.rotation
    x = m[0] * corners[:, 0] + m[2] * corners[:, 1] + m[4]
    y = m[1] * corners[:, 0] + m[3] * corners[:, 1] + m[5]
    return [
        [round(float(px / page.width), 6), round(float(py / page.height), 6)]
        for px, py in zip(x, y, strict=True)
    ]


def _reading_order(page: ParkingPage, stalls: list[Stall], k: float) -> list[int]:
    """Сверху вниз по рядам (шаг ROW_STEP_M), в ряду слева направо — по экранным центрам."""
    keys = []
    for n, s in enumerate(stalls):
        c = s.corners.mean(axis=0)
        m = page.rotation
        cx, cy = m[0] * c[0] + m[2] * c[1] + m[4], m[1] * c[0] + m[3] * c[1] + m[5]
        keys.append((round(cy * k / pc.ROW_STEP_M), cx, n))
    return [n for *_, n in sorted(keys)]


def _space_json(page: ParkingPage, s: Stall, cl: Classified) -> dict[str, object]:
    return {
        "parking_type": cl.parking_type,
        "label": cl.label,
        "points": _norm(page, s.corners),
        "width_m": round(s.width_m, 2),
        "length_m": round(s.length_m, 2),
        "area_m2": round(s.width_m * s.length_m, 2),
        "type_margin": cl.margin,
        "notes": cl.notes,
    }


def find_parking(
    pdf: Path, page_index: int, zone: Zone | None, scale_mm_per_pt: float
) -> dict[str, object]:
    """Поля zones.json: parking_spaces, parking_legend, parking_summary."""
    page = read_parking_page(pdf, page_index)
    idx = PathIndex(page.paths)
    if zone is None:  # рамка плана не привязана: ищем по всей странице, рамка = охват мест
        side = max(page.width, page.height)
        stalls = find_stalls(idx, (0.0, 0.0, side, side), scale_mm_per_pt)
        if stalls:
            allc = np.vstack([s.corners for s in stalls])
            zone = (*allc.min(axis=0).tolist(), *allc.max(axis=0).tolist())
    else:
        stalls = find_stalls(idx, zone, scale_mm_per_pt)
    if not stalls or zone is None:
        return {"parking_spaces": [], "parking_legend": [], "parking_summary": []}
    templates = find_templates(page, idx, zone)
    order = _reading_order(page, stalls, scale_mm_per_pt / 1000.0)
    classes = [classify(idx, stalls[n].corners, templates) for n in order]
    spaces = [_space_json(page, stalls[n], cl) for n, cl in zip(order, classes, strict=True)]
    counts = Counter(cl.parking_type for cl in classes)
    labels: dict[str, str | None] = {}
    for cl in classes:
        labels.setdefault(cl.parking_type, cl.label)
    legend = [{"parking_type": t.parking_type, "label": t.label} for t in templates]
    summary = [
        {"parking_type": t, "label": labels[t], "count": n}
        for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {"parking_spaces": spaces, "parking_legend": legend, "parking_summary": summary}
