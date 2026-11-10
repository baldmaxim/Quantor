"""candidate.json (quantor.cad_mep.candidate.v1) и preview.json (quantor.cad_engine.preview.v1)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from cad_mep.checks import lengths_by_layer, lengths_by_system
from cad_mep.elevations import Value
from cad_mep.frame import Frame, TieStats
from cad_mep.labels import Labels
from cad_mep.layers import MARK_LAYERS, ROUTE_LAYERS
from cad_mep.params import Params
from cad_mep.rooms import Model
from cad_mep.systems import Result

CANDIDATE_SCHEMA = "quantor.cad_mep.candidate.v1"
PREVIEW_SCHEMA = "quantor.cad_engine.preview.v1"

JsonObj = dict[str, object]


@dataclass(frozen=True)
class Provenance:
    generator_version: str
    pdf_sha256: str
    page_index: int
    view_dxf_sha256: str
    out_dxf_sha256: str
    params_sha256: str
    approval_id: str | None
    view_folder: str
    floor_elevation: Value
    floor_height: Value


def _value_out(v: Value) -> JsonObj:
    return {"value_mm": v.value_mm, "source": v.source, "evidence": v.evidence}


def _r(v: float, nd: int = 1) -> float:
    return round(float(v), nd)


def _sorted_unique(values: list[str]) -> list[object]:
    return list(dict.fromkeys(sorted(values)))


def build_candidate(
    prov: Provenance,
    params: Params,
    frame: Frame,
    tie: TieStats,
    scale_source: str,
    m: Model,
    labels: Labels,
    res: Result,
    crossings: dict[str, dict[str, object]],
    dxf_info: dict[str, int],
) -> JsonObj:
    dx, dy = frame.x0, frame.y0

    def dxf_xy(p: tuple[float, float]) -> object:
        return [round(p[0] + dx), round(p[1] + dy)]

    comp_ids: dict[str, list[int]] = defaultdict(list)
    for c in m.comps.values():
        for rl in c.room_labels:
            comp_ids[rl.room_id].append(c.id)
    rooms_out: list[object] = []
    for rid, e in labels.expl.items():
        cids = sorted(set(comp_ids.get(rid, [])))
        row: JsonObj = {
            "room_id": rid,
            "name": e.name,
            "expl_area_m2": e.area_m2,
            "plan_labels": sum(1 for rl in labels.rooms if rl.room_id == rid),
            "comp": cids[0] if cids else None,
        }
        if cids:
            c = m.comps[cids[0]]
            gids = sorted({r.room_id for r in c.room_labels})
            gsum = round(sum(labels.expl[g].area_m2 for g in gids if g in labels.expl), 2)
            row.update(
                comp_area_m2=round(c.area_m2, 2),
                group_ids=list(gids),
                group_expl_sum_m2=gsum,
                delta_pct=round((c.area_m2 - gsum) / gsum * 100, 1) if gsum else None,
                merged=len(gids) > 1,
                apt=c.apt,
                kind=c.kind,
            )
        rooms_out.append(row)
    missing_ids = [
        str(r["room_id"]) for r in rooms_out if isinstance(r, dict) and r["comp"] is None
    ]
    extra_labels = [rl.room_id for rl in labels.rooms if rl.room_id not in labels.expl]

    room_re = re.compile(params.text("room_id_regex"))
    exp_by_k: dict[tuple[str, int], float] = defaultdict(float)
    for r in labels.expl.values():
        mm = room_re.match(r.room_id)
        if mm and mm.group(3) == "/":
            exp_by_k[(mm.group(1), int(mm.group(2)))] += r.area_m2

    heat_by_apt: dict[int, list[object]] = defaultdict(list)
    for h in res.heat_rooms:
        heat_by_apt[h.apt].append(
            {
                "room_id": h.room_id,
                "name": h.name,
                "status": h.status,
                "device_dxf_mm": dxf_xy(h.device) if h.device else None,
                "outer_ring_len_m": h.outer_ring_len_m,
            }
        )
    apts_out: list[object] = []
    for ap in m.apts.values():
        info = res.per_apt.get(ap.idx, {})
        area = sum(m.comps[c].area_m2 for c in ap.comps)
        exp = exp_by_k.get((ap.section, ap.k), 0.0) if ap.k is not None else 0.0
        apts_out.append(
            {
                "idx": ap.idx,
                "number": ap.number,
                "comps": list(ap.comps),
                "rooms": _sorted_unique(
                    [rl.room_id for c in ap.comps for rl in m.comps[c].room_labels]
                ),
                "entry_door": ap.entry_door.id if ap.entry_door else None,
                "entry_door_mid_dxf_mm": dxf_xy(ap.entry_door.mid) if ap.entry_door else None,
                "entry_door_width_mm": round(ap.entry_door.width) if ap.entry_door else None,
                "plan_area_m2": round(area, 2),
                "expl_rooms_sum_m2": round(exp, 2) if exp else None,
                "delta_pct": round((area - exp) / exp * 100, 1) if exp else None,
                "heat": {
                    "shaft": info.get("heat_shaft"),
                    "path_shaft_to_collector_m": info.get("heat_path_to_collector_m"),
                    "beams_plan_m": info.get("heat_beams_m"),
                    "devices": heat_by_apt.get(ap.idx, []),
                },
                "water": {
                    "shaft": info.get("water_shaft"),
                    "path_shaft_to_entry_m": info.get("water_path_m"),
                    "t4_last_of_branch": bool(info.get("t4_last_of_branch")),
                },
                "lengths_own_lines": lengths_by_system(res, ap.idx),
                "detached_groups": [list(g) for g in ap.detached],
            }
        )
    shafts_out: list[object] = []
    for s in m.shafts:
        lx, ly = frame.local_to_dxf(*s.label_pt)
        shafts_out.append(
            {
                "id": s.id,
                "systems": list(s.systems),
                "place": s.place,
                "contour": s.contour_status,
                "area_m2": round(s.area_m2, 3),
                "centroid_dxf_mm": dxf_xy(s.centroid),
                "label_pt": [_r(v) for v in frame.dxf_to_pt(lx, ly)],
                "apt": s.apt,
                "risers": res.shaft_use.get(s.id),
            }
        )
    by_place: Counter[str] = Counter()
    for s in m.shafts:
        for sys_ in s.systems:
            by_place[f"{sys_}/{s.place}"] += 1
    label_counts = Counter(sy for s in labels.shafts for sy in s.systems)
    mop_shafts = {
        k: sum(
            1
            for s in m.shafts
            if k in s.systems and s.place == "mop" and s.contour_status == "found"
        )
        for k in ("ОВ", "ВК", "ПК")
    }
    by_layer = lengths_by_layer(res)
    by_system = lengths_by_system(res)
    totals = {
        "plan_m": round(sum(v["plan_m"] for v in by_layer.values()), 2),
        "len3d_m": round(sum(v["len3d_m"] for v in by_layer.values()), 2),
    }
    wall_viol = sum(int(str(v["bad_samples"])) for v in crossings.values())
    z: JsonObj = {
        "heating_m": prov.floor_elevation.value_mm + params.num("z_heat_mm"),
        "ceiling_m": prov.floor_elevation.value_mm
        + prov.floor_height.value_mm
        - params.num("ceiling_below_slab_mm"),
        "meter_m": prov.floor_elevation.value_mm + params.num("z_meter_mm"),
    }
    complete = all(
        res.per_apt.get(a.idx, {}).get("heat_shaft")
        and res.per_apt.get(a.idx, {}).get("water_shaft")
        for a in m.apts.values()
    )
    checks: JsonObj = {
        "tie_pdf_to_dxf": {
            "passed": True,
            "voters": tie.voters,
            "n_checked": tie.n_checked,
            "err_median_mm": _r(tie.err_median_mm, 3),
            "err_p90_mm": _r(tie.err_p90_mm, 3),
            "share_under_limit": round(tie.share_under_limit, 4),
            "limit_mm": tie.limit_mm,
        },
        "no_wall_crossing": {"passed": wall_viol == 0, "per_layer": crossings},
        "apartments_count": {
            "plan": len(m.apts),
            "expl": len(exp_by_k),
            "passed": len(m.apts) == len(exp_by_k),
        },
        "rooms_count": {
            "expl_rooms_total": len(labels.expl),
            "found_on_plan": len(labels.expl) - len(missing_ids),
            "missing_ids": list(missing_ids),
            "unknown_plan_labels": list(extra_labels),
        },
        "each_apt_has_heat_and_water": {"passed": bool(complete)},
        "dxf": dict(dxf_info),
    }
    provenance: JsonObj = {
        "generator_version": prov.generator_version,
        "pdf_sha256": prov.pdf_sha256,
        "page_index": prov.page_index,
        "view_dxf_sha256": prov.view_dxf_sha256,
        "mep_routes_dxf_sha256": prov.out_dxf_sha256,
        "params_sha256": prov.params_sha256,
        "approval_id": prov.approval_id,
        "view_folder": prov.view_folder,
        "floor_elevation": _value_out(prov.floor_elevation),
        "floor_height": _value_out(prov.floor_height),
        "scale": {"mm_per_pt": frame.scale, "source": scale_source},
        "frame": {"origin_pt": [_r(frame.ox, 4), _r(frame.oy, 4)]},
        "params": params.dump(),
    }
    return {
        "schema": CANDIDATE_SCHEMA,
        "status": "candidate_requires_review",
        "provenance": provenance,
        "elevation": {
            "floor_elevation_mm": {
                "value": prov.floor_elevation.value_mm,
                "source": prov.floor_elevation.source,
            },
            "floor_height_mm": {
                "value": prov.floor_height.value_mm,
                "source": prov.floor_height.source,
            },
            "sheet_marks_mm": list(labels.elevation_marks_mm),
            "levels_mm": z,
        },
        "assumptions": params.assumed(),
        "shafts": shafts_out,
        "shaft_summary": {
            "label_counts": dict(label_counts),
            "mop_shafts_with_contour": mop_shafts,
            "by_system_place": dict(sorted(by_place.items())),
        },
        "apartments": apts_out,
        "rooms": rooms_out,
        "routes": {
            "layers": {k: {"system": v[0]} for k, v in ROUTE_LAYERS.items() if k in by_layer},
            "by_layer": by_layer,
            "by_system": by_system,
            "common_lines": lengths_by_system(res, None),
            "fire": res.fire,
            "totals": totals,
        },
        "virtual_openings": m.virtual_openings,
        "notes": list(m.notes),
        "issues": [
            {"code": i.code, "message": i.message, "apartment": i.apartment} for i in res.issues
        ],
        "checks": checks,
    }


def build_preview(
    res: Result,
    parent_bbox: list[float],
    dxf_rel_path: str,
    dxf_sha256: str,
    frame: Frame,
    diamond_mm: float,
) -> JsonObj:
    """Превью в тех же координатах (мм DXF) и рамке, что preview.json движка у родителя."""
    dx, dy = frame.x0, frame.y0
    paths: list[tuple[str, bool, list[float]]] = []
    for ln in res.lines:
        flat: list[float] = []
        last: tuple[float, float] | None = None
        for x, y, _z in ln.pts:
            q = (round(x + dx, 2), round(y + dy, 2))
            if q != last:
                flat += [q[0], q[1]]
                last = q
        if len(flat) >= 4:
            paths.append((ln.layer, False, flat))
    for nd in res.nodes:
        x, y = nd.xy[0] + dx, nd.xy[1] + dy
        d = diamond_mm
        ring = [x, y - d, x + d, y, x, y + d, x - d, y, x, y - d]
        paths.append((nd.layer, True, [round(v, 2) for v in ring]))
    order = [*ROUTE_LAYERS, *MARK_LAYERS]
    used = [name for name in order if any(p[0] == name for p in paths)]
    index = {name: i for i, name in enumerate(used)}
    out_paths: list[object] = [
        {"layer": index[lay], "closed": closed, "fill": False, "points": pts}
        for lay, closed, pts in paths
    ]
    n_points = sum(len(p[2]) // 2 for p in paths)
    return {
        "bbox": list(parent_bbox),
        "dxf": dxf_rel_path,
        "dxf_sha256": dxf_sha256,
        "flatten_mm": 0,
        "layers": list(used),
        "paths": out_paths,
        "points": n_points,
        "schema": PREVIEW_SCHEMA,
        "skipped": {},
        "truncated": False,
        "units": "mm",
    }
