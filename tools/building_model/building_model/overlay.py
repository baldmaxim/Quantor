"""Растровая подложка для проверки человеком: стены модели поверх страницы PDF.

Цвета: склеенные стены по осям из segments — синий, стены с осью по контуру (outline, mixed) —
оранжевый, отсечённые — красный, проёмы с хозяином (двери, окна, пустые проёмы) — зелёный.
Добавлены слои, не меняющие смысла прежних цветов: контуры помещений — тонкая бирюзовая линия,
проёмы без хозяина (нет или неоднозначен) — пурпурные, с крестиком в опорной точке.
Команда запускается в окружении оценки (pypdfium2 и Pillow), Pydantic не используется: модель
читается как JSON. Файл пишется только в указанное место (out/); печатаются числа.
"""

from __future__ import annotations

import json
from pathlib import Path

from building_model.binding import (
    Pt,
    best_rotation,
    evaluate_rotations,
    read_pdf_page,
    read_raw_sheet,
    sheet_to_user,
    user_to_display,
)

MAX_SIDE_PX = 2500
BLUE = (30, 70, 220)
RED = (220, 30, 30)
GREEN = (20, 160, 60)
ORANGE = (255, 140, 0)
PURPLE = (200, 0, 200)
TEAL = (0, 150, 170)
CROSS_ARM_PX = 12


LEGEND: tuple[tuple[str, tuple[int, int, int], str], ...] = (
    ("синий", BLUE, "стены, склеенные по осевым линиям plangeom (segments)"),
    ("оранжевый", ORANGE, "стены с осью, выведенной по контуру (outline, mixed)"),
    ("красный", RED, "отсечённые тонкие и короткие участки"),
    ("зелёный", GREEN, "проёмы, у которых найден хозяин-стена"),
    ("пурпурный, с крестиком", PURPLE, "проёмы без хозяина (нет стены или хозяин неоднозначен)"),
    ("бирюзовая тонкая линия", TEAL, "контуры помещений"),
)


def _pt(value: object) -> Pt:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("ожидалась точка [x, y]")
    return (float(value[0]), float(value[1]))


def render_overlay(input_path: Path, model_path: Path, page: int, pdf_path: Path, out: Path) -> int:
    import pypdfium2 as pdfium
    from PIL import ImageDraw

    sheet = read_raw_sheet(input_path, page)
    with model_path.open("r", encoding="utf-8") as fh:
        model = json.load(fh)
    source = sheet["source"]
    scale_info = sheet["scale"]
    if not isinstance(source, dict) or not isinstance(scale_info, dict):
        raise ValueError("у листа нет source или scale")
    mm_per_pt = float(scale_info["mm_per_pt"])
    page_index = int(source.get("page_in_volume", page))

    geometry = read_pdf_page(pdf_path, page_index)
    shares, _ = evaluate_rotations(sheet, geometry)
    rotation = best_rotation(shares, geometry.rotate)
    crop = geometry.cropbox

    pdf = pdfium.PdfDocument(str(pdf_path))
    pdf_page = pdf[page_index]
    width_pt, height_pt = pdf_page.get_size()
    render_scale = MAX_SIDE_PX / max(width_pt, height_pt)
    image = pdf_page.render(scale=render_scale).to_pil().convert("RGB")
    draw = ImageDraw.Draw(image)

    origin = _pt(model["origin"]["sheet_mm"])

    def to_px(p: Pt) -> Pt:
        sheet_mm = (p[0] + origin[0], origin[1] - p[1])
        u, v = sheet_mm[0] / mm_per_pt, sheet_mm[1] / mm_per_pt
        x, y = sheet_to_user(u, v, rotation, crop)
        disp = user_to_display(x, y, geometry.rotate, crop)
        return (disp[0] * render_scale, disp[1] * render_scale)

    def line(a: Pt, b: Pt, color: tuple[int, int, int], width: int) -> None:
        draw.line([to_px(a), to_px(b)], fill=color, width=width)

    for room in model.get("rooms", []):
        ring = [to_px(_pt(p)) for p in room["polygon"]]
        if len(ring) >= 3:
            draw.line([*ring, ring[0]], fill=TEAL, width=1)
    for item in model["review"]["items"]:
        if str(item["code"]).startswith("wall_rejected") and item.get("a") and item.get("b"):
            line(_pt(item["a"]), _pt(item["b"]), RED, 1)
    for wall in model["walls"]:
        derived_axis = wall.get("axis_source") in ("outline", "mixed")
        line(_pt(wall["a"]), _pt(wall["b"]), ORANGE if derived_axis else BLUE, 3)
    for opening in model["openings"]:
        a, b = opening["span"]
        if opening.get("host") is None:
            line(_pt(a), _pt(b), PURPLE, 5)
            cx, cy = to_px(_pt(opening["at"]))
            draw.line(
                [(cx - CROSS_ARM_PX, cy - CROSS_ARM_PX), (cx + CROSS_ARM_PX, cy + CROSS_ARM_PX)],
                fill=PURPLE,
                width=3,
            )
            draw.line(
                [(cx - CROSS_ARM_PX, cy + CROSS_ARM_PX), (cx + CROSS_ARM_PX, cy - CROSS_ARM_PX)],
                fill=PURPLE,
                width=3,
            )
        else:
            line(_pt(a), _pt(b), GREEN, 5)

    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    print(f"страница {page}; применён поворот {rotation} (/Rotate {geometry.rotate})")
    print(
        f"растр {image.width} x {image.height} px; стен {len(model['walls'])}, "
        f"проёмов {len(model['openings'])}"
    )
    return 0
