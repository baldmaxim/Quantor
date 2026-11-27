"""Пакет входа ИИ-правщика и ИИ-проверщика: сводка walls.json и тайлы чертежа с сеткой.

Модуль детерминированный и без сети. Он грузится двумя путями: как `app.cad_worker.ai_review_pack`
(тесты, API) и по пути к файлу из `ai_review_cli.py` под `python -I` в окружении CAD-движка, где
пакета `app` нет. Поэтому наверху только стандартная библиотека, а PyMuPDF и Pillow импортируются
лениво внутри функций рендера. Сводка, раскладка тайлов и шаг сетки - чистые функции без PyMuPDF.

Система координат ответа модели - пиксели `plan.png` от левого верхнего угла (`AiFinding.bbox_px`).
Все `bbox_px` пакета считаются тем же преобразованием, что `overlay.png`:
`px = (origin_pt + mm / mm_per_pt) * zoom - pix_origin`, ось Y перевёрнута. Числа движка берутся из
walls.json как есть: пакет суммирует только готовые поля и ничего не выводит из полигонов.
"""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

SUMMARY_SCHEMA = "quantor.ai_walls_summary.v1"
TILES_SCHEMA = "quantor.ai_tiles.v1"
SUMMARY_LIMIT_BYTES = 30 * 1024
# Целевой размер ниже жёсткого предела: запас на округление и перевод строк.
_SUMMARY_TARGET_BYTES = 30_000
TILE_LONG_SIDE_PX = 1800
TILE_OVERLAP = 0.10
TILES_TOTAL_LIMIT_BYTES = 12 * 1024 * 1024
LABEL_FONT_PX = 16
_MAX_TILE_ATTEMPTS = 5
_MAX_WARNINGS = 25
_MAX_WARNING_CHARS = 220
_MAX_HOLES = 20
_MAX_INLINE_CHARS = 160

WALL_LAYERS: tuple[tuple[str, str], ...] = (
    ("constructions", "#e11d48"),
    ("frame_partitions", "#0284c7"),
)
LINTEL_COLOR = "#15803d"
_GRID_RGB = (150, 30, 220)
# Шаги сетки в пикселях plan.png: соседние отличаются не более чем в 1,6 раза.
_GRID_STEPS = (10, 20, 25, 40, 50, 75, 100, 150, 200, 250, 400, 500, 1000, 2000)
_MAX_GRID_LINES = 8

# Кадр вида: (x0, y0 в pt страницы, мм на pt).
Frame = tuple[float, float, float]
Ring = list[list[float]]
Bbox = list[float]


class TileSpec(NamedTuple):
    row: int
    col: int
    bbox_px: tuple[float, float, float, float]


class TileMap(NamedTuple):
    """Растр тайла: масштаб px/pt и начало пиксмапа (целые пиксели) в системе страницы."""

    zoom: float
    pix_x: int
    pix_y: int
    width: int
    height: int
    plan_zoom: float
    plan_pix_x: int
    plan_pix_y: int

    def to_plan_px(self, u: float, v: float) -> tuple[float, float]:
        """Пиксель тайла -> пиксель plan.png."""
        ratio = self.plan_zoom / self.zoom
        return (
            (self.pix_x + u) * ratio - self.plan_pix_x,
            (self.pix_y + v) * ratio - self.plan_pix_y,
        )

    def from_plan_px(self, x: float, y: float) -> tuple[float, float]:
        """Пиксель plan.png -> пиксель тайла (обратное к `to_plan_px`)."""
        ratio = self.zoom / self.plan_zoom
        return (
            (x + self.plan_pix_x) * ratio - self.pix_x,
            (y + self.plan_pix_y) * ratio - self.pix_y,
        )

    def bbox_plan_px(self) -> list[float]:
        x0, y0 = self.to_plan_px(0, 0)
        x1, y1 = self.to_plan_px(self.width, self.height)
        return [x0, y0, x1, y1]

    def bbox_pt(self) -> list[float]:
        return [
            self.pix_x / self.zoom,
            self.pix_y / self.zoom,
            (self.pix_x + self.width) / self.zoom,
            (self.pix_y + self.height) / self.zoom,
        ]


# --- преобразования координат --------------------------------------------------------------


def mm_to_px(
    frame: Frame, zoom: float, pix_x: float, pix_y: float, x_mm: float, y_mm: float
) -> tuple[float, float]:
    ox, oy, mm_per_pt = frame
    return ((ox + x_mm / mm_per_pt) * zoom - pix_x, (oy - y_mm / mm_per_pt) * zoom - pix_y)


def ring_converter(
    frame: Frame, zoom: float, pix_x: float, pix_y: float
) -> Callable[[Ring], list[tuple[float, float]]]:
    """Контур в мм вида -> точки растра с масштабом `zoom` и началом пиксмапа (pix_x, pix_y)."""

    def convert(ring: Ring) -> list[tuple[float, float]]:
        return [mm_to_px(frame, zoom, pix_x, pix_y, float(x), float(y)) for x, y in ring]

    return convert


def draw_overlay(
    draw: Any,
    walls: dict[str, Any],
    convert: Callable[[Ring], list[tuple[float, float]]],
    width: int,
) -> None:
    """Наложение конструкций и перемычек проёмов: цвета и логика `overlay.png`."""
    for group, color in WALL_LAYERS:
        for row in walls.get(group, []):
            polygon = row["polygon"]
            for ring in [polygon["shell"], *polygon["holes"]]:
                points = convert(ring)
                if len(points) >= 3:
                    draw.line([*points, points[0]], fill=color, width=width)
    for opening in walls.get("openings", []):
        if opening.get("lintel"):
            points = convert(opening["lintel"])
            if len(points) >= 3:
                draw.line([*points, points[0]], fill=LINTEL_COLOR, width=width)


# --- сводка walls.json ---------------------------------------------------------------------


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return round(value)


def _bbox_px_of_mm(
    points_mm: Ring, frame: Frame, zoom: float, pix_x: float, pix_y: float
) -> list[int] | None:
    if not points_mm:
        return None
    pixels = [mm_to_px(frame, zoom, pix_x, pix_y, float(x), float(y)) for x, y in points_mm]
    xs, ys = [p[0] for p in pixels], [p[1] for p in pixels]
    return [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))]


def _bbox_ring(bbox: Any) -> Ring | None:
    if (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in bbox)
    ):
        x0, y0, x1, y1 = bbox
        return [[x0, y0], [x1, y1]]
    return None


def _construction_row(
    row: dict[str, Any], frame: Frame, zoom: float, pix_x: float, pix_y: float
) -> dict[str, Any] | None:
    ring = _bbox_ring(row.get("bbox"))
    if ring is None:
        polygon = row.get("polygon")
        ring = polygon.get("shell") if isinstance(polygon, dict) else None
    bbox = _bbox_px_of_mm(ring or [], frame, zoom, pix_x, pix_y)
    if bbox is None:
        return None
    layers = row.get("source_layers")
    result: dict[str, Any] = {
        "id": row.get("id"),
        "kind": row.get("kind"),
        "layer": layers[0] if isinstance(layers, list) and layers else None,
        "thickness_mm": _int(row.get("thickness_nominal_mm")),
        "length_mm": _int(row.get("length_axis_mm")),
        "bbox_px": bbox,
    }
    if result["thickness_mm"] is None and _int(row.get("thickness_measured_mm")) is not None:
        result["thickness_measured_mm"] = _int(row.get("thickness_measured_mm"))
    return result


def _opening_row(
    row: dict[str, Any], frame: Frame, zoom: float, pix_x: float, pix_y: float
) -> dict[str, Any] | None:
    ring = row.get("lintel") if isinstance(row.get("lintel"), list) else None
    if not ring:
        center = row.get("center")
        reach = max(_int(row.get("width_mm")) or 0, _int(row.get("thickness_mm")) or 0) / 2
        if isinstance(center, list) and len(center) == 2 and reach > 0:
            cx, cy = float(center[0]), float(center[1])
            ring = [[cx - reach, cy - reach], [cx + reach, cy + reach]]
    bbox = _bbox_px_of_mm(ring or [], frame, zoom, pix_x, pix_y)
    if bbox is None:
        return None
    return {
        "id": row.get("id"),
        "kind": row.get("kind"),
        "status": row.get("status"),
        "width_mm": _int(row.get("width_mm")),
        "bbox_px": bbox,
    }


def _group_totals(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], str]
) -> dict[str, Any]:
    totals: dict[str, list[float]] = {}
    for row in rows:
        bucket = totals.setdefault(key(row), [0, 0.0])
        bucket[0] += 1
        bucket[1] += float(row.get("length_axis_mm") or 0.0)
    return {
        name: {"count": int(count), "length_mm": round(length)}
        for name, (count, length) in sorted(totals.items())
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _trim(text: Any, limit: int) -> str:
    return str(text or "")[:limit]


def _slab_block(
    walls: dict[str, Any], frame: Frame, zoom: float, pix_x: float, pix_y: float
) -> dict[str, Any]:
    slab = walls.get("slab")
    block: dict[str, Any] = {}
    if isinstance(slab, dict):
        block.update(
            {
                "basis": slab.get("basis"),
                "needs_review": slab.get("needs_review"),
                "area_mm2": _int(slab.get("area_mm2")),
            }
        )
    holes: list[dict[str, Any]] = []
    for hole in walls.get("slab_holes") or []:
        if not isinstance(hole, dict):
            continue
        holes.append(
            {
                "id": hole.get("id"),
                "status": hole.get("status"),
                "reason": hole.get("reason"),
                "area_mm2": _int(hole.get("area_mm2")),
                "bbox_px": _bbox_px_of_mm(hole.get("shell") or [], frame, zoom, pix_x, pix_y),
            }
        )
    block["holes_total"] = len(holes)
    block["holes"] = holes[:_MAX_HOLES]
    return block


def _diagnostics(walls: dict[str, Any]) -> dict[str, Any]:
    checks = _dict(walls.get("checks"))
    raw_warnings = [w for w in checks.get("warnings") or [] if isinstance(w, dict)]
    codes: dict[str, int] = {}
    for warning in raw_warnings:
        code = str(warning.get("code"))
        codes[code] = codes.get(code, 0) + 1
    result: dict[str, Any] = {
        "residue_ratio": checks.get("residue_ratio"),
        "warning_codes": codes,
        "warnings": [
            {"code": w.get("code"), "message": _trim(w.get("message"), _MAX_WARNING_CHARS)}
            for w in raw_warnings[:_MAX_WARNINGS]
        ],
    }
    extra = walls.get("diagnostics")
    if isinstance(extra, list):
        result["engine"] = [
            {"code": r.get("code"), "message": _trim(r.get("message"), _MAX_WARNING_CHARS)}
            for r in extra[:_MAX_WARNINGS]
            if isinstance(r, dict)
        ]
    for key in ("axes", "levels"):
        block = walls.get(key)
        if isinstance(block, dict):
            result[key] = {
                "status": block.get("status"),
                "message": _trim(block.get("message"), _MAX_WARNING_CHARS) or None,
            }
    legend = walls.get("legend")
    if isinstance(legend, dict):
        result["legend"] = {
            "conflicts": len(legend.get("conflicts") or {}),
            "unparsed": len(legend.get("unparsed") or []),
        }
    return result


def dump_summary(summary: dict[str, Any]) -> str:
    """JSON для Read: поле на строку, элементы списков по одному на строку, длинные словари тоже.

    Строка не длиннее нескольких сотен знаков: длинную строку Read обрезает.
    """

    def compact(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def emit(name: str | None, value: Any, tail: str, expand_dict: bool = True) -> list[str]:
        head = "" if name is None else f"{compact(name)}:"
        if isinstance(value, list) and value:
            lines = [head + "["]
            for position, element in enumerate(value):
                lines += emit(None, element, "," if position < len(value) - 1 else "", False)
            return [*lines, "]" + tail]
        if isinstance(value, dict) and expand_dict and len(compact(value)) > _MAX_INLINE_CHARS:
            lines = [head + "{"]
            for position, (key, element) in enumerate(value.items()):
                lines += emit(key, element, "," if position < len(value) - 1 else "")
            return [*lines, "}" + tail]
        return [head + compact(value) + tail]

    lines = ["{"]
    items = list(summary.items())
    for index, (key, value) in enumerate(items):
        lines += emit(key, value, "," if index < len(items) - 1 else "")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _size(summary: dict[str, Any]) -> int:
    return len(dump_summary(summary).encode("utf-8"))


def build_walls_summary(
    walls: dict[str, Any],
    *,
    frame: Frame,
    zoom: float,
    pix_x: float,
    pix_y: float,
    width_px: int,
    height_px: int,
    view_zone: list[float] | None = None,
) -> dict[str, Any]:
    """Сводка walls.json ≤ 30 КБ; при нехватке места списки усекаются (короткие первыми)."""
    constructions_raw = [r for r in walls.get("constructions", []) if isinstance(r, dict)]
    constructions_raw += [r for r in walls.get("frame_partitions", []) if isinstance(r, dict)]
    constructions = [
        row
        for row in (_construction_row(r, frame, zoom, pix_x, pix_y) for r in constructions_raw)
        if row is not None
    ]
    lengths = {str(r.get("id")): float(r.get("length_axis_mm") or 0.0) for r in constructions_raw}
    constructions.sort(key=lambda r: (-lengths.get(str(r["id"]), 0.0), str(r["id"])))
    openings_raw = [r for r in walls.get("openings", []) if isinstance(r, dict)]
    openings = [
        row
        for row in (_opening_row(r, frame, zoom, pix_x, pix_y) for r in openings_raw)
        if row is not None
    ]
    openings.sort(key=lambda r: (-(r["width_mm"] or 0), str(r["id"])))

    heights = _dict(walls.get("heights"))
    title = _dict(heights.get("title"))
    mm_per_pt = frame[2]
    opening_kinds: dict[str, int] = {}
    for row in openings_raw:
        label = f"{row.get('kind')}/{row.get('status')}"
        opening_kinds[label] = opening_kinds.get(label, 0) + 1
    base: dict[str, Any] = {
        "schema": SUMMARY_SCHEMA,
        "generator": walls.get("generator"),
        "units": "mm",
        "scale": {
            "mm_per_pt": round(mm_per_pt, 4),
            "mm_per_plan_px": round(mm_per_pt / zoom, 3),
            "plan_px_per_pt": round(zoom, 4),
        },
        "plan_png": {
            "width_px": width_px,
            "height_px": height_px,
            "view_zone_pt": [round(v, 2) for v in view_zone] if view_zone else None,
            "coordinates": "bbox_px - пиксели plan.png от левого верхнего угла",
        },
        "heights": {
            key: heights.get(key)
            for key in (
                "floor_elevation_mm",
                "floor_height_mm",
                "elevation_status",
                "height_status",
                "slab_thickness_mm",
                "door_height_mm",
            )
        }
        | {"title": _trim(title.get("text"), 120) or None},
        "counts": {
            "constructions": len(constructions_raw),
            "openings": len(openings_raw),
            "openings_by_kind_status": dict(sorted(opening_kinds.items())),
            "by_kind": _group_totals(constructions_raw, lambda r: str(r.get("kind"))),
            "by_layer": _group_totals(
                constructions_raw,
                lambda r: str((r.get("source_layers") or [None])[0]),
            ),
            "by_kind_thickness": [
                {
                    "kind": t.get("kind"),
                    "thickness_nominal_mm": _int(t.get("thickness_nominal_mm")),
                    "count": t.get("count"),
                    "length_mm": _int(t.get("length_axis_mm")),
                }
                for t in walls.get("totals", [])
                if isinstance(t, dict)
            ],
        },
        "slab": _slab_block(walls, frame, zoom, pix_x, pix_y),
        "diagnostics": _diagnostics(walls),
    }
    return _fit_lists(base, constructions, openings)


def _shrink_fixed_part(base: dict[str, Any]) -> bool:
    """Убирает последний элемент из первого непустого усекаемого списка; False - убирать нечего."""
    diagnostics, slab, counts = base["diagnostics"], base["slab"], base["counts"]
    for owner, key in (
        (diagnostics, "warnings"),
        (slab, "holes"),
        (diagnostics, "engine"),
        (counts, "by_kind_thickness"),
    ):
        if owner.get(key):
            owner[key] = owner[key][:-1]
            return True
    for owner, key in ((counts, "by_layer"), (diagnostics, "warning_codes")):
        if owner.get(key):
            owner[key] = dict(list(owner[key].items())[:-1])
            return True
    return False


def _fit_lists(
    base: dict[str, Any], constructions: list[dict[str, Any]], openings: list[dict[str, Any]]
) -> dict[str, Any]:
    total_c, total_o = len(constructions), len(openings)

    def assemble(kept_c: int, kept_o: int) -> dict[str, Any]:
        summary = dict(base)
        truncated: dict[str, str] = {}
        if kept_c < total_c:
            truncated["constructions"] = f"{kept_c}/{total_c}"
        if kept_o < total_o:
            truncated["openings"] = f"{kept_o}/{total_o}"
        if truncated:
            summary["truncated"] = truncated
        summary["constructions"] = constructions[:kept_c]
        summary["openings"] = openings[:kept_o]
        return summary

    # Постоянная часть (счётчики, диагностика) ужимается, только если она одна не помещается.
    while _size(assemble(0, 0)) > _SUMMARY_TARGET_BYTES:
        if not _shrink_fixed_part(base):
            raise ValueError("Сводка walls.json не помещается в предел")
    if _size(assemble(total_c, total_o)) <= _SUMMARY_TARGET_BYTES:
        return assemble(total_c, total_o)
    # Проёмы получают не больше 40 % свободного места, остальное - конструкциям.
    room = _SUMMARY_TARGET_BYTES - _size(assemble(0, 0))
    kept_o, spent = 0, 0
    for row in openings:
        cost = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()) + 2
        if spent + cost > room * 0.4:
            break
        spent += cost
        kept_o += 1
    low, high = 0, total_c
    while low < high:
        middle = (low + high + 1) // 2
        if _size(assemble(middle, kept_o)) <= _SUMMARY_TARGET_BYTES:
            low = middle
        else:
            high = middle - 1
    return assemble(low, kept_o)


# --- тайлы ---------------------------------------------------------------------------------


def plan_tiles(width: int, height: int) -> list[TileSpec]:
    """Сетка тайлов поверх plan.png: ≈3 по длинной стороне, перекрытие 10 % ячейки."""
    if width <= 0 or height <= 0:
        return []
    if width >= height:
        cols, rows = 3, min(3, max(1, round(3 * height / width)))
    else:
        rows, cols = 3, min(3, max(1, round(3 * width / height)))
    cell_w, cell_h = width / cols, height / rows
    pad_x, pad_y = TILE_OVERLAP / 2 * cell_w, TILE_OVERLAP / 2 * cell_h
    return [
        TileSpec(
            row,
            col,
            (
                max(0.0, col * cell_w - pad_x),
                max(0.0, row * cell_h - pad_y),
                min(float(width), (col + 1) * cell_w + pad_x),
                min(float(height), (row + 1) * cell_h + pad_y),
            ),
        )
        for row in range(rows)
        for col in range(cols)
    ]


def tile_zoom(tiles: list[TileSpec], plan_zoom: float) -> float:
    """Общий масштаб тайлов px/pt: длинная сторона самого большого тайла ≈ 1800 px."""
    longest = max(max(t.bbox_px[2] - t.bbox_px[0], t.bbox_px[3] - t.bbox_px[1]) for t in tiles)
    return TILE_LONG_SIDE_PX * plan_zoom / longest


def grid_step(span_px: float) -> int:
    """Шаг сетки в px plan.png: не больше 8 линий на длинной стороне, обычно 5-8."""
    for step in _GRID_STEPS:
        if span_px / step < _MAX_GRID_LINES:
            return step
    return _GRID_STEPS[-1]


def grid_positions(start: float, end: float, step: int) -> list[int]:
    first = math.ceil(start / step) * step
    return list(range(first, math.floor(end) + 1, step))


def tile_name(spec: TileSpec, kind: str) -> str:
    return f"tiles/r{spec.row}c{spec.col}_{kind}.png"


def _font(size: int) -> Any:
    font_module: Any = importlib.import_module("PIL.ImageFont")
    try:
        return font_module.load_default(size=size)
    except TypeError:
        return font_module.load_default()


def _draw_grid(image: Any, tile: TileMap, mm_per_plan_px: float) -> Any:
    """Полупрозрачная сетка с подписями: px plan.png (система ответа) и мм от начала вида."""
    pil_image: Any = importlib.import_module("PIL.Image")
    pil_draw: Any = importlib.import_module("PIL.ImageDraw")
    layer = pil_image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = pil_draw.Draw(layer)
    font = _font(LABEL_FONT_PX)
    x0, y0, x1, y1 = tile.bbox_plan_px()
    step = grid_step(max(x1 - x0, y1 - y0))
    line = (*_GRID_RGB, 95)
    width, height = image.size

    def label(x: float, y: float, text: str) -> None:
        left, top, right, bottom = draw.textbbox((x, y), text, font=font)
        draw.rectangle((left - 2, top - 1, right + 2, bottom + 1), fill=(255, 255, 255, 215))
        draw.text((x, y), text, font=font, fill=(*_GRID_RGB, 255))

    for gx in grid_positions(x0, x1, step):
        u = tile.from_plan_px(gx, 0)[0]
        draw.line([(u, 0), (u, height)], fill=line, width=1)
        text = f"x{gx}"
        mm = f"{round(gx * mm_per_plan_px)}mm"
        label(u + 3, 2, text)
        label(u + 3, 2 + LABEL_FONT_PX + 4, mm)
        label(u + 3, height - 2 * LABEL_FONT_PX - 10, text)
        label(u + 3, height - LABEL_FONT_PX - 5, mm)
    for gy in grid_positions(y0, y1, step):
        v = tile.from_plan_px(0, gy)[1]
        draw.line([(0, v), (width, v)], fill=line, width=1)
        text = f"y{gy}"
        mm = f"{round(gy * mm_per_plan_px)}mm"
        label(3, v + 3, text)
        label(3, v + 3 + LABEL_FONT_PX + 4, mm)
        label(width - 90, v + 3, text)
        label(width - 90, v + 3 + LABEL_FONT_PX + 4, mm)
    return pil_image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def _save_palette(image: Any, path: Path) -> int:
    pil_image: Any = importlib.import_module("PIL.Image")
    image.quantize(colors=256, method=pil_image.Quantize.MEDIANCUT).save(path, optimize=True)
    return path.stat().st_size


def render_tiles(
    root: Path,
    walls: dict[str, Any],
    *,
    frame: Frame,
    plan_zoom: float,
    plan_pix_x: int,
    plan_pix_y: int,
    plan_width: int,
    plan_height: int,
) -> dict[str, Any]:
    """Тайлы из `source.pdf` (`*_pdf.png`) и с наложением (`*_overlay.png`) + описание `tiles.json`.

    Общий размер файлов ≤ 12 МБ: при превышении масштаб тайлов уменьшается и рендер повторяется.
    """
    pymupdf: Any = importlib.import_module("pymupdf")
    pil_image: Any = importlib.import_module("PIL.Image")
    pil_draw: Any = importlib.import_module("PIL.ImageDraw")
    specs = plan_tiles(plan_width, plan_height)
    if not specs:
        raise ValueError("Пустой растр: тайлы не построить")
    folder = root / "tiles"
    folder.mkdir(exist_ok=True)
    mm_per_plan_px = frame[2] / plan_zoom
    base_zoom = tile_zoom(specs, plan_zoom)
    entries: list[dict[str, Any]] = []
    with pymupdf.open(root / "source.pdf") as document:
        page = document[0]
        for attempt in range(_MAX_TILE_ATTEMPTS):
            zoom = base_zoom * 0.8**attempt
            entries = []
            total = 0
            for spec in specs:
                x0, y0, x1, y1 = spec.bbox_px
                clip = pymupdf.Rect(
                    (plan_pix_x + x0) / plan_zoom,
                    (plan_pix_y + y0) / plan_zoom,
                    (plan_pix_x + x1) / plan_zoom,
                    (plan_pix_y + y1) / plan_zoom,
                )
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
                tile = TileMap(
                    zoom,
                    pixmap.x,
                    pixmap.y,
                    pixmap.width,
                    pixmap.height,
                    plan_zoom,
                    plan_pix_x,
                    plan_pix_y,
                )
                base = pil_image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                overlay = base.copy()
                draw_overlay(
                    pil_draw.Draw(overlay),
                    walls,
                    ring_converter(frame, zoom, pixmap.x, pixmap.y),
                    3,
                )
                sizes = [
                    _save_palette(
                        _draw_grid(image, tile, mm_per_plan_px), root / tile_name(spec, kind)
                    )
                    for kind, image in (("pdf", base), ("overlay", overlay))
                ]
                total += sum(sizes)
                entries.append(
                    {
                        "id": f"r{spec.row}c{spec.col}",
                        "pdf": tile_name(spec, "pdf"),
                        "overlay": tile_name(spec, "overlay"),
                        "size_px": [pixmap.width, pixmap.height],
                        "bbox_px": [round(v, 1) for v in tile.bbox_plan_px()],
                        "bbox_pt": [round(v, 2) for v in tile.bbox_pt()],
                        "plan_px_per_tile_px": round(plan_zoom / zoom, 4),
                        "mm_per_tile_px": round(frame[2] / zoom, 3),
                    }
                )
            if total <= TILES_TOTAL_LIMIT_BYTES:
                break
        else:
            raise ValueError("Тайлы больше допустимого размера")
    description = {
        "schema": TILES_SCHEMA,
        "plan_png": {"width_px": plan_width, "height_px": plan_height},
        "mm_per_plan_px": round(mm_per_plan_px, 3),
        "grid_labels": "x/y - пиксели plan.png (система ответа); mm - от угла plan.png",
        "tiles": entries,
    }
    (root / "tiles.json").write_text(json.dumps(description, ensure_ascii=False), encoding="utf-8")
    return description


def write_pack(
    root: Path,
    walls: dict[str, Any],
    *,
    frame: Frame,
    plan_zoom: float,
    plan_pix_x: int,
    plan_pix_y: int,
    plan_width: int,
    plan_height: int,
    view_zone: list[float] | None = None,
) -> None:
    """`walls_summary.json`, `tiles/*.png`, `tiles.json` рядом с plan.png и source.pdf."""
    summary = build_walls_summary(
        walls,
        frame=frame,
        zoom=plan_zoom,
        pix_x=plan_pix_x,
        pix_y=plan_pix_y,
        width_px=plan_width,
        height_px=plan_height,
        view_zone=view_zone,
    )
    (root / "walls_summary.json").write_text(dump_summary(summary), encoding="utf-8")
    render_tiles(
        root,
        walls,
        frame=frame,
        plan_zoom=plan_zoom,
        plan_pix_x=plan_pix_x,
        plan_pix_y=plan_pix_y,
        plan_width=plan_width,
        plan_height=plan_height,
    )


PACK_FILES: tuple[str, ...] = ("walls_summary.json", "tiles.json")
