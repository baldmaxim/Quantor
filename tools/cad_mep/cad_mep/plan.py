"""Общий префикс конвейера: чтение входов, привязка PDF -> DXF, модель помещений плана.

Им пользуются генератор трасс (pipeline.generate) и разметка зон помещений (zones).
Порядок шагов и коды ошибок — те же, что были внутри generate.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import shapely
from ezdxf.document import Drawing
from shapely.geometry import Polygon

from cad_mep import assign, candidate, dxfin, pdfsrc, rooms
from cad_mep import frame as frame_mod
from cad_mep import labels as labels_mod
from cad_mep.dxfin import Door
from cad_mep.errors import EXIT_NO_ROUTES, MepError
from cad_mep.issues import Issue
from cad_mep.params import Params, load_params

Zone = tuple[float, float, float, float]


def read_json(path: Path, code: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MepError(code, f"{path.name}: не читается ({exc})") from exc


def read_scale(path: Path) -> float:
    raw = read_json(path, "scale_invalid")
    value = raw.get("scale_used_for_geometry") if isinstance(raw, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise MepError("scale_invalid", "scale.json: нет положительного scale_used_for_geometry")
    return float(value)


def read_preview_bbox(path: Path) -> list[float]:
    raw = read_json(path, "preview_invalid")
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


def wall_polys(page: pdfsrc.PageData, frame: frame_mod.Frame, zone: Zone) -> list[Polygon]:
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


@dataclass
class PlanInput:
    """Прочитанные входы и система координат растров (локальная: рамка плана с запасом)."""

    params: Params
    page: pdfsrc.PageData
    view_doc: Drawing
    tie_by_name: bool
    tie: frame_mod.TieStats
    bbox: list[float]
    frame: frame_mod.Frame
    fx0: float
    fy0: float
    extent: tuple[float, float]
    bbox_local: tuple[float, float, float, float]
    zone: Zone  # рамка плана на листе, пт


def open_plan(
    pdf: Path,
    page_index: int,
    view_dxf: Path,
    scale_path: Path,
    preview_path: Path,
    params_path: Path | None,
) -> PlanInput:
    params = load_params(params_path)
    scale = read_scale(scale_path)
    bbox = read_preview_bbox(preview_path)

    page = pdfsrc.read_page(pdf, page_index, params)
    view_doc = dxfin.read_dxf(view_dxf)
    tie_points, tie_by_name = dxfin.wall_points(view_doc, params)
    base_frame, tie = frame_mod.find_frame(page.vertices, tie_points, scale, params)

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
    return PlanInput(
        params,
        page,
        view_doc,
        tie_by_name,
        tie,
        bbox,
        frame,
        fx0,
        fy0,
        extent,
        bbox_local,
        (px0, py0, px1, py1),
    )


@dataclass
class PlanModel:
    wall_polys: list[Polygon]
    lab: labels_mod.Labels
    doors: list[Door]
    model: rooms.Model
    assigned: list[Issue]


def build_plan_model(plan: PlanInput) -> PlanModel:
    """Заливки стен, подписи, двери, помещения, квартиры и привязка комнат без марки по площади."""
    params, page, frame = plan.params, plan.page, plan.frame
    px0, py0, px1, py1 = plan.zone
    walls = wall_polys(page, frame, plan.zone)
    if not walls:
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

    doors = dxfin.load_doors(plan.view_doc, params, (plan.fx0, plan.fy0))
    model = rooms.build(walls, lab, doors, plan.bbox_local, plan.extent, params)
    rooms.door_links(model, doors)
    rooms.build_apartments(model, lab, params)
    if not model.apts:
        raise MepError(
            "no_apartments", "квартиры на плане не найдены (нет марок помещений)", EXIT_NO_ROUTES
        )
    assigned = assign.by_area(model, lab, params, (plan.fx0, plan.fy0))
    return PlanModel(walls, lab, doors, model, assigned)
