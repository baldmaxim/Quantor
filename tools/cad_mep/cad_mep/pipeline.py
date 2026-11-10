"""Конвейер: PDF + DXF вида + калибровка -> mep_routes.dxf, preview.json, candidate.json."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import shapely
from shapely.geometry import Polygon

from cad_mep import candidate, checks, dxfin, dxfout, pdfsrc, rooms, route
from cad_mep import frame as frame_mod
from cad_mep import labels as labels_mod
from cad_mep.errors import EXIT_NO_ROUTES, MepError
from cad_mep.params import load_params
from cad_mep.systems import Issue, Planner, Result
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
    floor_elevation_mm: int
    floor_height_mm: int
    approval_id: str | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _read_json(path: Path, code: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MepError(code, f"{path.name}: не читается ({exc})") from exc


def _read_scale(path: Path) -> float:
    raw = _read_json(path, "scale_invalid")
    value = raw.get("scale_used_for_geometry") if isinstance(raw, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise MepError("scale_invalid", "scale.json: нет положительного scale_used_for_geometry")
    return float(value)


def _read_preview_bbox(path: Path) -> list[float]:
    raw = _read_json(path, "preview_invalid")
    bbox = raw.get("bbox") if isinstance(raw, dict) else None
    schema = raw.get("schema") if isinstance(raw, dict) else None
    if schema != candidate.PREVIEW_SCHEMA:
        raise MepError(
            "preview_invalid",
            f"preview.json: схема {schema!r}, ожидалась {candidate.PREVIEW_SCHEMA}",
        )
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in bbox)
    ):
        raise MepError("preview_invalid", "preview.json: нет bbox из четырёх чисел")
    vals = [float(v) for v in bbox if isinstance(v, int | float)]
    if not (vals[0] < vals[2] and vals[1] < vals[3]):
        raise MepError("preview_invalid", "preview.json: пустой bbox")
    return vals


def _validate(args: Args) -> None:
    if not (HEIGHT_MIN_MM <= args.floor_height_mm <= HEIGHT_MAX_MM):
        raise MepError(
            "height_invalid",
            f"высота этажа {args.floor_height_mm} мм вне {HEIGHT_MIN_MM}…{HEIGHT_MAX_MM}",
        )
    if abs(args.floor_elevation_mm) > 1_000_000:
        raise MepError(
            "elevation_invalid", f"отметка пола {args.floor_elevation_mm} мм вне допустимого"
        )
    for p, code in ((args.pdf, "pdf_unreadable"), (args.view_dxf, "dxf_unreadable")):
        if not p.is_file():
            raise MepError(code, f"нет файла {p.name}")
    if not args.view_folder or "/" in args.view_folder or ".." in args.view_folder:
        raise MepError("view_folder_invalid", "view-folder: ожидалось имя вида вида pNNN_vNN")


def _wall_polys(
    page: pdfsrc.PageData, frame: frame_mod.Frame, zone: tuple[float, float, float, float]
) -> list[Polygon]:
    zx0, zy0, zx1, zy1 = zone
    out: list[Polygon] = []
    for f in page.wall_fills:
        bx0, by0, bx1, by1 = f.bbox
        if bx1 < zx0 or bx0 > zx1 or by1 < zy0 or by0 > zy1:
            continue
        poly = Polygon([frame.pt_to_local(x, y) for x, y in f.pts])
        if not poly.is_valid:
            fixed = poly.buffer(0)  # самопересечение: делим на валидные части
            out.extend(
                q for q in shapely.get_parts(fixed) if isinstance(q, Polygon) and not q.is_empty
            )
        elif not poly.is_empty:
            out.append(poly)
    return out


def generate(args: Args) -> dict[str, object]:
    """Строит три файла в <out>/views/<view-folder>/. Возвращает краткую сводку."""
    _validate(args)
    params = load_params(args.params)
    scale = _read_scale(args.scale)
    bbox = _read_preview_bbox(args.preview)

    page = pdfsrc.read_page(args.pdf, args.page_index, params)
    view_doc = dxfin.read_dxf(args.view_dxf)
    base_frame, tie = frame_mod.find_frame(
        page.vertices, dxfin.wall_points(view_doc, params), scale, params
    )

    # локальная система растров: рамка плана с запасом, кратная шагу сетки трассировки
    align = params.num("grid_route_mm")
    margin = params.num("grid_margin_mm")
    fx0 = math.floor((bbox[0] - margin) / align) * align
    fy0 = math.floor((bbox[1] - margin) / align) * align
    extent = (bbox[2] + margin - fx0, bbox[3] + margin - fy0)
    frame = base_frame.with_local(fx0, fy0)
    bbox_local = (bbox[0] - fx0, bbox[1] - fy0, bbox[2] - fx0, bbox[3] - fy0)

    pad = params.num("plan_zone_pad_mm")
    px0, py1 = frame.dxf_to_pt(bbox[0] - pad, bbox[1] - pad)
    px1, py0 = frame.dxf_to_pt(bbox[2] + pad, bbox[3] + pad)
    zone = (px0, py0, px1, py1)
    wall_polys = _wall_polys(page, frame, zone)
    if not wall_polys:
        raise MepError("plan_not_found", "в рамке плана нет заливок стен", EXIT_NO_ROUTES)
    plan_words: list[labels_mod.Word] = []
    expl_words: list[labels_mod.Word] = []
    for w in page.words:
        cx, cy = (w.x0 + w.x1) / 2, (w.y0 + w.y1) / 2
        target = plan_words if (px0 <= cx <= px1 and py0 <= cy <= py1) else expl_words
        target.append(labels_mod.to_word(w, frame))
    lab = labels_mod.parse_plan(plan_words, params)
    lab.expl = labels_mod.parse_explication(expl_words, params)
    lab.apt_numbers = labels_mod.parse_apt_numbers(page.words, params)
    lab.elevation_marks_mm = labels_mod.parse_elevations(page.words, params)

    doors = dxfin.load_doors(view_doc, params, (fx0, fy0))
    model = rooms.build(wall_polys, lab, doors, bbox_local, extent, params)
    rooms.door_links(model, doors)
    rooms.build_apartments(model, lab, params)
    rooms.classify_shafts(model, params)
    if not model.apts:
        raise MepError(
            "no_apartments", "квартиры на плане не найдены (нет марок помещений)", EXIT_NO_ROUTES
        )
    rg = route.build_grid(model, doors, params)
    res = Planner(
        model, lab, doors, rg, params, float(args.floor_elevation_mm), float(args.floor_height_mm)
    ).run()
    # без стояков, питающих квартиры, остаются лишь лучи внутри квартир — это не результат
    if not any(ln.kind == "leadin" for ln in res.lines):
        reasons = "; ".join(i.message for i in res.issues[:5])
        raise MepError("routes_not_built", f"трассы не построены: {reasons}", EXIT_NO_ROUTES)
    _issue_elevation(res, lab.elevation_marks_mm, args.floor_elevation_mm)
    if not lab.expl:
        res.issues.append(
            Issue(
                "no_explication",
                "экспликация на листе не найдена: нет сверки площадей и приборов отопления",
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
        float(args.floor_elevation_mm),
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
        args.floor_elevation_mm,
        args.floor_height_mm,
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
    )
    _dump(folder / "preview.json", preview)
    _dump(folder / "candidate.json", cand)
    return {
        "ok": True,
        "apartments": len(model.apts),
        "polylines": len(res.lines),
        "issues": len(res.issues),
    }


def _issue_elevation(res: Result, marks: list[int], entered: int) -> None:
    """Отметка с листа не совпадает с введённой — замечание, не ошибка."""
    if marks and entered not in marks:
        found = ", ".join(f"{v / 1000:+.3f}".replace(".", ",") for v in marks)
        res.issues.append(
            Issue(
                "elevation_mismatch",
                f"введённая отметка пола {entered / 1000:+.3f} м не найдена среди отметок листа "
                f"({found})",
            )
        )


def _dump(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
