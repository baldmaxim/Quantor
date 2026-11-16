"""Картинка проверки привязки: лист PDF, оси модели и разрез этажа поверх него.

Рисуется на копии страницы в памяти (исходный PDF не меняется) средствами PyMuPDF,
в неповёрнутом пространстве страницы - том же, что у placement.json.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

GROUP_COLOR = {"walls": (0.0, 0.4, 0.8), "columns": (0.85, 0.35, 0.1), "curtain": (0.0, 0.6, 0.45)}
AXIS_COLOR = (0.8, 0.0, 0.8)


def _to_sheet(affine: list[list[float]], x: float, y: float) -> fitz.Point:
    (a, b, c), (d, e, f) = affine
    return fitz.Point(a * x + b * y + c, d * x + e * y + f)


def draw_overlay(
    pdf: Path | str,
    placement: dict[str, Any],
    grids: dict[str, Any],
    png: Path | str,
    footprint: dict[str, Any] | None = None,
    dpi: int = 60,
) -> Path:
    """PNG с осями (пунктир) и контурами разреза этажа; возвращает путь к файлу."""
    affine = placement.get("affine")
    if not affine:
        raise ValueError("в placement нет подгонки (affine) - рисовать нечего")
    with fitz.open(str(pdf)) as src, fitz.open() as doc:
        doc.insert_pdf(src, from_page=placement["page"], to_page=placement["page"])
        page = doc[0]
        page.set_rotation(0)
        shape = page.new_shape()
        for axis in grids.get("axes", []):
            shape.draw_line(_to_sheet(affine, *axis["p0"]), _to_sheet(affine, *axis["p1"]))
        shape.finish(color=AXIS_COLOR, width=0.6, dashes="[6 4] 0", stroke_opacity=0.8)
        for group, rings in (footprint or {}).get("polygons", {}).items():
            color = GROUP_COLOR.get(group, (0.5, 0.5, 0.5))
            for ring in rings:
                shape.draw_polyline([_to_sheet(affine, x, y) for x, y in ring])
                shape.finish(
                    color=color,
                    fill=color,
                    width=0.4,
                    closePath=True,
                    fill_opacity=0.35,
                    stroke_opacity=0.8,
                )
        shape.commit()
        out = Path(png)
        page.get_pixmap(dpi=dpi, alpha=False).save(str(out))
    return out
