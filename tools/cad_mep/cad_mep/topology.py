"""Топология трасс по итоговой геометрии: висячие концы и пересечения линий (2D-проекция)."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely import STRtree
from shapely.geometry import LineString, Point

from cad_mep.layers import ROUTE_LAYERS, SYSTEM_OF_LAYER
from cad_mep.params import Params
from cad_mep.result import Pt, Result

SAMPLES = 5
JsonObj = dict[str, object]


@dataclass
class _Line:
    layer: str
    pts: list[Pt]
    geom: LineString

    @property
    def ends(self) -> list[Pt]:
        return [self.pts[0], self.pts[-1]]


def _flat(pts: list[tuple[float, float, float]]) -> list[Pt]:
    """2D-проекция: соседние точки с совпавшими x, y схлопываются (вертикальные спуски)."""
    out: list[Pt] = []
    for x, y, _ in pts:
        if not out or math.hypot(x - out[-1][0], y - out[-1][1]) > 1e-6:
            out.append((x, y))
    return out


def _collect(res: Result) -> tuple[list[_Line], dict[str, list[Pt]]]:
    """Линии трасс (без стояков) и xy стояков по слоям."""
    lines: list[_Line] = []
    risers: dict[str, list[Pt]] = {}
    for ln in res.lines:
        if ln.layer not in SYSTEM_OF_LAYER:
            continue
        pts = _flat(ln.pts)
        if ln.kind == "riser":
            risers.setdefault(ln.layer, []).extend(pts[:1])
        elif len(pts) >= 2:
            lines.append(_Line(ln.layer, pts, LineString(pts)))
    return lines, risers


def _near_any(p: Pt, targets: list[Pt], radius: float) -> bool:
    return any(math.hypot(p[0] - t[0], p[1] - t[1]) <= radius for t in targets)


def _is_crossing(a: _Line, b: _Line, p: Pt, tol: float) -> bool:
    """Внутренняя точка: не у конца любой из линий и не общая вершина обеих."""
    if _near_any(p, a.ends, tol) or _near_any(p, b.ends, tol):
        return False
    return not (_near_any(p, a.pts, tol) and _near_any(p, b.pts, tol))


def _crossings(lines: list[_Line], tol: float) -> tuple[dict[str, list[Pt]], dict[str, int]]:
    """Пересечения по отрезкам: точки внутри слоя и число пар слоёв по системам."""
    segs: list[tuple[int, LineString]] = []
    for i, ln in enumerate(lines):
        segs += [(i, LineString([a, b])) for a, b in zip(ln.pts, ln.pts[1:], strict=False)]
    same: dict[str, list[Pt]] = {}
    cross: dict[str, int] = {}
    if not segs:
        return same, cross
    geoms = np.array([g for _, g in segs], dtype=object)
    pairs = STRtree(geoms).query(geoms, predicate="intersects")
    found: set[tuple[int, int, int, int]] = set()
    for si, sj in zip(pairs[0].tolist(), pairs[1].tolist(), strict=True):
        i, j = segs[si][0], segs[sj][0]
        if si >= sj or i == j:
            continue
        inter = segs[si][1].intersection(segs[sj][1])
        if not isinstance(inter, Point):
            continue  # наложение отрезков — не пересечение
        p = (float(inter.x), float(inter.y))
        a, b = lines[i], lines[j]
        key = (min(i, j), max(i, j), round(p[0]), round(p[1]))
        if key in found or not _is_crossing(a, b, p, tol):
            continue
        found.add(key)
        if a.layer == b.layer:
            same.setdefault(a.layer, []).append(p)
        elif SYSTEM_OF_LAYER[a.layer] == SYSTEM_OF_LAYER[b.layer]:
            system = SYSTEM_OF_LAYER[a.layer]
            cross[system] = cross.get(system, 0) + 1
    return same, cross


def _free_ends(lines: list[_Line], terminals: list[Pt], tol: float, radius: float) -> list[Pt]:
    """Концы линий слоя без стыка с другой линией и без узла/стояка рядом."""
    tree = STRtree(np.array([ln.geom for ln in lines], dtype=object))
    free: list[Pt] = []
    for i, ln in enumerate(lines):
        for end in ln.ends:
            hits = tree.query(Point(end), predicate="dwithin", distance=tol).tolist()
            if not any(h != i for h in hits) and not _near_any(end, terminals, radius):
                free.append(end)
    return free


def _samples(pts: list[Pt], shift: tuple[float, float]) -> list[list[int]]:
    return [[round(x + shift[0]), round(y + shift[1])] for x, y in sorted(pts)[:SAMPLES]]


def route_topology(res: Result, params: Params, shift: tuple[float, float] = (0.0, 0.0)) -> JsonObj:
    """Висячие концы и пересечения трасс; точки-образцы — в мм DXF (смещение shift)."""
    tol = params.num("topo_end_tol_mm")
    radius = params.num("topo_terminal_radius_mm")
    lines, risers = _collect(res)
    same, cross = _crossings(lines, tol)
    layers: dict[str, JsonObj] = {}
    sums = {"lines": 0, "ends": 0, "dangling": 0, "branch_ends": 0, "same_layer_crossings": 0}
    length_total = 0.0
    used_systems: set[str] = set()
    for layer in ROUTE_LAYERS:
        mine = [ln for ln in lines if ln.layer == layer]
        if not mine:
            continue
        system = SYSTEM_OF_LAYER[layer]
        used_systems.add(system)
        terminals = [n.xy for n in res.nodes if n.system == system] + risers.get(layer, [])
        free = _free_ends(mine, terminals, tol, radius)
        # тупик ветки АУП — законный конец, не висячий
        branch, dangling = (free, []) if layer == "M-PT-AUP" else ([], free)
        crossed = same.get(layer, [])
        length = sum(ln.geom.length for ln in mine) / 1000
        length_total += length
        layers[layer] = {
            "lines": len(mine),
            "length_m": round(length, 2),
            "ends": 2 * len(mine),
            "dangling": len(dangling),
            "dangling_samples": _samples(dangling, shift),
            "branch_ends": len(branch),
            "same_layer_crossings": len(crossed),
            "crossing_samples": _samples(crossed, shift),
        }
        sums["lines"] += len(mine)
        sums["ends"] += 2 * len(mine)
        sums["dangling"] += len(dangling)
        sums["branch_ends"] += len(branch)
        sums["same_layer_crossings"] += len(crossed)
    systems: dict[str, JsonObj] = {
        s: {"cross_layer_crossings": cross.get(s, 0)} for s in sorted(used_systems)
    }
    totals: JsonObj = {
        **sums,
        "length_m": round(length_total, 2),
        "cross_layer_crossings": sum(cross.values()),
    }
    return {"layers": layers, "systems": systems, "totals": totals}
