"""Конвейер: PDF + DXF вида + калибровка -> mep_routes.dxf, preview.json, candidate.json."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cad_mep import (
    candidate,
    checks,
    dxfin,
    dxfout,
    elevations,
    facade,
    risers,
    rooms,
    route,
    topology,
)
from cad_mep.errors import EXIT_NO_ROUTES, MepError
from cad_mep.issues import Issue
from cad_mep.plan import build_plan_model, open_plan
from cad_mep.raster import raster_polys
from cad_mep.result import Result
from cad_mep.systems import Planner
from cad_mep.version import GENERATOR_VERSION

HEIGHT_MIN_MM = 2000
HEIGHT_MAX_MM = 6000


@dataclass(frozen=True)
class Args:
    pdf: Path
    page_index: int
    view_dxf: Path
    scale: Path
    preview: Path
    params: Path | None
    out: Path
    view_folder: str
    # None - определить по тексту документации; число - переопределение человека
    floor_elevation_mm: int | None = None
    floor_height_mm: int | None = None
    approval_id: str | None = None
    # реестр стояков cad_risers.v1 (None — стояки по подписям шахт АР)
    risers: Path | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _validate(args: Args) -> None:
    height = args.floor_height_mm
    if height is not None and not (HEIGHT_MIN_MM <= height <= HEIGHT_MAX_MM):
        raise MepError(
            "height_invalid", f"высота этажа {height} мм вне {HEIGHT_MIN_MM}…{HEIGHT_MAX_MM}"
        )
    elevation = args.floor_elevation_mm
    if elevation is not None and abs(elevation) > elevations.ELEVATION_LIMIT_MM:
        raise MepError("elevation_invalid", f"отметка пола {elevation} мм вне допустимого")
    for p, code in ((args.pdf, "pdf_unreadable"), (args.view_dxf, "dxf_unreadable")):
        if not p.is_file():
            raise MepError(code, f"нет файла {p.name}")
    if args.risers is not None and not args.risers.is_file():
        raise MepError("risers_unreadable", f"нет файла реестра стояков {args.risers.name}")
    if not args.view_folder or "/" in args.view_folder or ".." in args.view_folder:
        raise MepError("view_folder_invalid", "view-folder: ожидалось имя вида вида pNNN_vNN")


def _topology_issues(res: Result, topo: dict[str, object]) -> None:
    """По одному замечанию на слой с висячими концами и на слой с самопересечениями."""
    layers = topo.get("layers")
    if not isinstance(layers, dict):
        return
    for layer, info in layers.items():
        if int(info["dangling"]):
            res.issues.append(
                Issue(
                    "route_dangling_ends",
                    f"{layer}: {info['dangling']} висячих концов трассы из {info['ends']}, "
                    f"первые (мм DXF): {info['dangling_samples']}",
                )
            )
        if int(info["same_layer_crossings"]):
            res.issues.append(
                Issue(
                    "route_line_crossings",
                    f"{layer}: {info['same_layer_crossings']} пересечений линий слоя, "
                    f"первые (мм DXF): {info['crossing_samples']}",
                )
            )


def generate(args: Args) -> dict[str, object]:
    """Строит три файла в <out>/views/<view-folder>/. Возвращает краткую сводку."""
    _validate(args)
    registry = risers.load_risers(args.risers) if args.risers is not None else []
    plan = open_plan(
        args.pdf, args.page_index, args.view_dxf, args.scale, args.preview, args.params
    )
    params, view_doc, frame, bbox = plan.params, plan.view_doc, plan.frame, plan.bbox
    fx0, fy0, tie, tie_by_name = plan.fx0, plan.fy0, plan.tie, plan.tie_by_name
    px0, py0, px1, py1 = plan.zone
    # отметка и высота - до тяжёлых шагов: не нашлись - сразу «введите вручную»
    resolved = elevations.resolve(
        args.pdf,
        args.page_index,
        ((px0 + px1) / 2, (py0 + py1) / 2),
        params,
        args.floor_elevation_mm,
        args.floor_height_mm,
    )
    floor_elevation = resolved.elevation.value_mm
    floor_height = resolved.height.value_mm
    pm = build_plan_model(plan)
    wall_polys, lab, doors, model, assigned = pm.wall_polys, pm.lab, pm.doors, pm.model, pm.assigned
    rooms.classify_shafts(model, params)
    rg = route.build_grid(model, doors, params)
    # простенки фасада: заливки стен PDF и штриховки сплошных конструкций DXF вида
    piers = dxfin.hatch_polys(view_doc, set(params.texts("dxf_pier_layers")), (fx0, fy0))
    prof = facade.build_profile(model, model.walls | raster_polys(model.gr, piers), params)
    planner = Planner(
        model,
        lab,
        doors,
        rg,
        params,
        float(floor_elevation),
        float(floor_height),
        prof,
        registry or None,
    )
    res = planner.run()
    res.issues[:0] = assigned
    # без стояков, питающих квартиры, остаются лишь лучи внутри квартир — это не результат
    if not any(ln.kind == "leadin" for ln in res.lines):
        reasons = "; ".join(i.message for i in res.issues[:5])
        raise MepError("routes_not_built", f"трассы не построены: {reasons}", EXIT_NO_ROUTES)
    res.issues.extend(Issue(code, message) for code, message in resolved.issues)
    if not tie_by_name:
        res.issues.append(
            Issue(
                "dxf_wall_layers_unknown",
                "в DXF вида нет слоёв контуров стен из параметров (dxf_wall_layers): привязка "
                "выполнена по всем полилиниям DXF, подложка A-WALL может быть неполной",
            )
        )
    if not lab.expl:
        res.issues.append(
            Issue(
                "no_explication",
                "экспликация на листе не найдена: нет сверки площадей, отапливаемые комнаты "
                "приняты по наружному остеклению",
            )
        )

    crossings = checks.wall_crossings(model, res, doors, params, (fx0, fy0))
    for layer, info in crossings.items():
        if int(str(info["bad_samples"])):
            res.issues.append(
                Issue(
                    "wall_crossing",
                    f"{layer}: {info['bad_samples']} точек трассы внутри стены, "
                    f"первая (мм DXF): {info['first_dxf_mm']}",
                )
            )
    beams = checks.beam_trees(model, res)
    if not beams["passed"]:
        res.issues.append(
            Issue(
                "heat_beam_loops",
                f"лучи отопления не дерево: петли {beams['loops_area_m2']} м², квартиры "
                f"{beams['apartments_not_tree']}, точек в чужих квартирах "
                f"{beams['points_in_other_apartments']}",
            )
        )
    topo = topology.route_topology(res, params, (fx0, fy0))
    _topology_issues(res, topo)
    folder = args.out / "views" / args.view_folder
    folder.mkdir(parents=True, exist_ok=True)
    dxf_path = folder / "mep_routes.dxf"
    dxf_info = dxfout.write(
        model,
        res,
        dxf_path,
        view_doc,
        wall_polys,
        params,
        (fx0, fy0),
        float(floor_elevation),
    )
    dxf_sha = sha256_file(dxf_path)
    preview = candidate.build_preview(
        res,
        bbox,
        f"views/{args.view_folder}/mep_routes.dxf",
        dxf_sha,
        frame,
        params.num("preview_diamond_mm"),
    )
    prov = candidate.Provenance(
        GENERATOR_VERSION,
        sha256_file(args.pdf),
        args.page_index,
        sha256_file(args.view_dxf),
        dxf_sha,
        params.sha256,
        args.approval_id,
        args.view_folder,
        resolved.elevation,
        resolved.height,
        sha256_file(args.risers) if args.risers is not None else None,
    )
    cand = candidate.build_candidate(
        prov,
        params,
        frame,
        tie,
        "scale.json:scale_used_for_geometry",
        model,
        lab,
        res,
        crossings,
        dxf_info,
        beams,
        topo,
        risers.registry_json(registry) if registry else None,
    )
    _dump(folder / "preview.json", preview)
    _dump(folder / "candidate.json", cand)
    return {
        "ok": True,
        "apartments": len(model.apts),
        "polylines": len(res.lines),
        "issues": len(res.issues),
    }


def _dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
