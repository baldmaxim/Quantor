"""Проверки результата: пересечения стен, длины по слоям и по квартирам."""

from __future__ import annotations

import math
from itertools import pairwise

from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

from cad_mep.dxfin import Door
from cad_mep.layers import SYSTEM_OF_LAYER
from cad_mep.params import Params
from cad_mep.raster import dilate, erode, raster_polys
from cad_mep.result import Result, len3, plan_len
from cad_mep.rooms import Model


def wall_crossings(
    m: Model, res: Result, doors: list[Door], params: Params, shift: tuple[float, float]
) -> dict[str, dict[str, object]]:
    """Трасса не пересекает стены, кроме дверей и виртуальных проходов (шаг check_sample_mm)."""
    gr = m.gr
    ok_zone = raster_polys(gr, [d.barrier(0.0, params.num("door_zone_half_t_mm")) for d in doors])
    ok_zone = dilate(ok_zone, params.count("check_zone_dilate_cells"))
    half = params.num("virtual_strip_half_mm")
    for vo in m.virtual_openings:
        p0, p1 = vo["from"], vo["to"]
        if isinstance(p0, list) and isinstance(p1, list):
            seg = LineString([(float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1]))])
            ok_zone |= raster_polys(gr, [seg.buffer(half, cap_style="flat")])
    # выход из шахты — через одну её стену (ТЗ): окрестность контуров шахт тоже разрешена
    exit_mm = params.num("check_shaft_exit_mm")
    ok_zone |= raster_polys(
        gr, [sh.contour.buffer(exit_mm) for sh in m.shafts if sh.place == "mop" and sh.contour]
    )
    sample = params.num("check_sample_mm")
    # касание кромки стены (в пределах клетки растра) нарушением не считается — только заход вглубь
    core = m.walls
    for _ in range(params.count("check_wall_touch_cells")):
        core = erode(core)
    per_layer: dict[str, dict[str, object]] = {}
    for ln in res.lines:
        if ln.kind not in ("route", "jumper"):
            continue
        bad = 0
        first: list[int] | None = None
        for (x0, y0, _), (x1, y1, _) in zip(ln.pts, ln.pts[1:], strict=False):
            length = math.hypot(x1 - x0, y1 - y0)
            n = max(2, int(length // sample))
            for k in range(n + 1):
                x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
                iy, ix = gr.ij(x, y)
                if gr.inside(iy, ix) and core[iy, ix] and not ok_zone[iy, ix]:
                    bad += 1
                    first = first or [round(x + shift[0]), round(y + shift[1])]
        d = per_layer.setdefault(
            ln.layer, {"lines": 0, "bad_samples": 0, "lines_with_crossing": 0, "first_dxf_mm": None}
        )
        d["lines"] = int(str(d["lines"])) + 1
        d["bad_samples"] = int(str(d["bad_samples"])) + bad
        if bad:
            d["lines_with_crossing"] = int(str(d["lines_with_crossing"])) + 1
            d["first_dxf_mm"] = d["first_dxf_mm"] or first
    return per_layer


def beam_trees(m: Model, res: Result) -> dict[str, object]:
    """Лучи отопления каждой квартиры — дерево: без петель и без захода в чужие квартиры.

    Петли ищутся дважды: по осям (граф узлов сетки: рёбер на одно меньше, чем узлов) и по
    начерченным линиям подачи и обратки (площадь замкнутых контуров).
    """
    not_tree: list[str] = []
    foreign = 0
    for ai, paths in sorted(res.beam_paths.items()):
        nodes = {pt for path in paths for pt in path}
        edges = {frozenset(pair) for path in paths for pair in pairwise(path)}
        if nodes and len(edges) != len(nodes) - 1:
            not_tree.append(m.apts[ai].number)
        for x, y in nodes:
            iy, ix = m.gr.ij(x, y)
            comp = m.comps.get(int(m.lab[iy, ix])) if m.gr.inside(iy, ix) else None
            if comp is not None and comp.apt not in (None, ai):
                foreign += 1
    area = 0.0
    for ai in sorted(res.beam_paths):
        for layer in ("M-OV-T1", "M-OV-T2"):
            lines = [
                LineString([(x, y) for x, y, _ in ln.pts])
                for ln in res.lines
                if ln.layer == layer and ln.apt == ai and len(ln.pts) > 1
            ]
            area += sum(face.area for face in polygonize(unary_union(lines)))
    return {
        "passed": not not_tree and foreign == 0 and area == 0.0,
        "apartments_not_tree": not_tree,
        "loops_area_m2": round(area / 1e6, 4),
        "points_in_other_apartments": foreign,
    }


def topology_check(topo: dict[str, object]) -> dict[str, object]:
    """FAIL при висячих концах или самопересечениях слоя; пересечения слоёв — справочно."""
    totals = topo.get("totals")
    if not isinstance(totals, dict):
        return {"passed": False, "status": "FAIL", "dangling_ends": None}
    dangling, same = int(totals["dangling"]), int(totals["same_layer_crossings"])
    return {
        "passed": dangling == 0 and same == 0,
        "status": "PASS" if dangling == 0 and same == 0 else "FAIL",
        "dangling_ends": dangling,
        "same_layer_crossings": same,
        "cross_layer_crossings": int(totals["cross_layer_crossings"]),
        "branch_ends": int(totals["branch_ends"]),
    }


def lengths_by_layer(res: Result) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for ln in res.lines:
        d = out.setdefault(ln.layer, {"plan_m": 0.0, "len3d_m": 0.0, "polylines": 0.0})
        d["plan_m"] += plan_len(ln.pts) / 1000
        d["len3d_m"] += len3(ln.pts) / 1000
        d["polylines"] += 1
    for d in out.values():
        d["plan_m"] = round(d["plan_m"], 2)
        d["len3d_m"] = round(d["len3d_m"], 2)
        d["polylines"] = int(d["polylines"])
    return out


def lengths_by_system(res: Result, apt: int | str | None = "all") -> dict[str, dict[str, float]]:
    """Длины по системам (план и 3D, м): по всем линиям, либо только линиям данной квартиры."""
    out: dict[str, dict[str, float]] = {}
    for ln in res.lines:
        if apt != "all" and ln.apt != apt:
            continue
        s = SYSTEM_OF_LAYER.get(ln.layer, ln.layer)
        d = out.setdefault(s, {"plan_m": 0.0, "len3d_m": 0.0})
        d["plan_m"] += plan_len(ln.pts) / 1000
        d["len3d_m"] += len3(ln.pts) / 1000
    return {s: {k: round(v, 2) for k, v in d.items()} for s, d in out.items()}
