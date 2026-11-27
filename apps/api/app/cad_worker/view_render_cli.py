"""Рендер снимков вида CAD (`plan.png`, `overlay.png`, `slab_overlay.png`, `render.json`).

Скрипт запускается только подпроцессом `cad-worker` через интерпретатор CAD-движка:
`PyMuPDF` и `Pillow` импортируются лениво внутри функции и никогда не попадают в процесс API.
Координатная сетка и цвета наложения совпадают с `ai_review_cli.py`:
- `plan.png` — исходная страница PDF (или вырезка по `view_zone`), длинная сторона до 2000 px;
- `overlay.png` — тот же растр с контурами `walls.json` (стены `#e11d48`, каркасные `#0284c7`,
  перемычки дверей `#15803d`);
- `slab_overlay.png` — тот же растр с контуром плиты перекрытия `slab`, отверстиями `slab_holes`,
  разноуровневыми участками `levels.zones`, проёмами и лёгкой координатной сеткой в пикселях
  (шаг 200 px) для точной проверки плит, шахт, террас/балконов, фасадов и `bbox_px`;
- `render.json` — `{"clip": [x0, y0, x1, y1], "zoom": float, "width_px": int, "height_px": int}`
  для точного перевода `bbox_px` -> `bbox_pt` страницы PDF.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any

MAX_SIDE_PX = 2000
GRID_STEP_PX = 200


def _parse_zone(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    parts = [float(item) for item in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("view-zone: нужны 4 числа x0,y0,x1,y1")
    return (parts[0], parts[1], parts[2], parts[3])


def slab_rings(slab: Any) -> list[list[list[float]]]:
    """Контуры плиты из блока `slab` walls.json: части `parts`, иначе единственный `shell`."""
    if not isinstance(slab, dict):
        return []
    parts = slab.get("parts")
    if isinstance(parts, list) and parts:
        rings = [
            part["shell"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("shell"), list)
        ]
        if rings:
            return rings
    shell = slab.get("shell")
    return [shell] if isinstance(shell, list) else []


def render_slab_overlay(
    *,
    base_rgb: Any,
    walls: dict[str, Any],
    frame: tuple[float, float, float],
    zoom: float,
    pix_x: int,
    pix_y: int,
    out_path: Path,
) -> None:
    """Наложение плиты перекрытия, отверстий, уровней, проёмов и пиксельной сетки."""
    pil_image: Any = importlib.import_module("PIL.Image")
    pil_draw: Any = importlib.import_module("PIL.ImageDraw")

    ox, oy, mm_per_pt = frame

    def to_px(ring: list[list[float]]) -> list[tuple[float, float]]:
        return [
            ((ox + float(x) / mm_per_pt) * zoom - pix_x, (oy - float(y) / mm_per_pt) * zoom - pix_y)
            for x, y in ring
        ]

    base = base_rgb.convert("RGBA")
    layer = pil_image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = pil_draw.Draw(layer)
    width, height = base.size

    # 1. Плита перекрытия (`slab`) — полупрозрачный синий контур; все части `slab.parts`
    # (cad_walls v1.27), у старого файла без `parts` — один контур `shell`.
    for slab_ring in slab_rings(walls.get("slab")):
        pts = to_px(slab_ring)
        if len(pts) >= 3:
            draw.polygon(pts, fill=(0, 115, 230, 50), outline=(0, 70, 210, 235))
            draw.line([*pts, pts[0]], fill=(0, 70, 210, 245), width=3)

    # 2. Разноуровневые участки плиты (`levels.zones`) — зелёные контуры (включая отверстия).
    levels = walls.get("levels")
    if isinstance(levels, dict) and isinstance(levels.get("zones"), list):
        for zone in levels["zones"]:
            if not isinstance(zone, dict):
                continue
            rings: list[Any] = []
            if isinstance(zone.get("shell"), list):
                rings.append(zone["shell"])
            if isinstance(zone.get("holes"), list):
                rings.extend(h for h in zone["holes"] if isinstance(h, list))
            for ring in rings:
                pts = to_px(ring)
                if len(pts) >= 3:
                    draw.line([*pts, pts[0]], fill=(16, 160, 70, 220), width=2)

    # 3. Отверстия-кандидаты в плите (`slab_holes`) — оранжево-красная заливка + подпись ID.
    holes = walls.get("slab_holes")
    if isinstance(holes, list):
        for hole in holes:
            if not isinstance(hole, dict) or not isinstance(hole.get("shell"), list):
                continue
            pts = to_px(hole["shell"])
            if len(pts) >= 3:
                draw.polygon(pts, fill=(235, 55, 20, 115), outline=(200, 15, 0, 255))
                draw.line([*pts, pts[0]], fill=(200, 15, 0, 255), width=2)
                hole_id = str(hole.get("id") or "")
                if hole_id:
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                    draw.rectangle([cx - 12, cy - 7, cx + 18, cy + 7], fill=(180, 15, 0, 220))
                    draw.text((cx - 9, cy - 6), hole_id[:6], fill=(255, 255, 255, 255))

    # 4. Проёмы (`openings`): окна — голубой, остальные — зелёный.
    openings = walls.get("openings")
    if isinstance(openings, list):
        for opening in openings:
            if not isinstance(opening, dict) or not isinstance(opening.get("lintel"), list):
                continue
            pts = to_px(opening["lintel"])
            if len(pts) < 3:
                continue
            is_window = opening.get("kind") == "window"
            fill = (0, 190, 240, 140) if is_window else (21, 128, 61, 120)
            stroke = (0, 115, 180, 240) if is_window else (21, 128, 61, 230)
            draw.polygon(pts, fill=fill, outline=stroke)
            draw.line([*pts, pts[0]], fill=stroke, width=2)

    # 5. Лёгкая координатная сетка в пикселях (`plan.png`) для точного снятия `bbox_px`.
    for x in range(GRID_STEP_PX, width, GRID_STEP_PX):
        draw.line([(x, 0), (x, height)], fill=(100, 116, 139, 90), width=1)
        draw.rectangle([x + 2, 2, x + 34, 15], fill=(255, 255, 255, 215))
        draw.text((x + 4, 3), str(x), fill=(30, 64, 175, 255))
    for y in range(GRID_STEP_PX, height, GRID_STEP_PX):
        draw.line([(0, y), (width, y)], fill=(100, 116, 139, 90), width=1)
        draw.rectangle([2, y + 2, 34, y + 15], fill=(255, 255, 255, 215))
        draw.text((4, y + 3), str(y), fill=(30, 64, 175, 255))

    pil_image.alpha_composite(base, layer).convert("RGB").save(out_path)


def render_view(
    *,
    pdf_path: Path,
    walls_path: Path,
    out_dir: Path,
    page_index: int,
    frame: tuple[float, float, float],
    view_zone: tuple[float, float, float, float] | None,
) -> None:
    import pymupdf  # type: ignore[import-not-found]  # Окружение CAD-движка.

    pil_image: Any = importlib.import_module("PIL.Image")
    pil_draw: Any = importlib.import_module("PIL.ImageDraw")

    walls = json.loads(walls_path.read_bytes())
    with pymupdf.open(pdf_path) as source:
        page = source[page_index]
        clip = page.rect
        if view_zone is not None:
            clip &= pymupdf.Rect(view_zone)
        if clip.is_empty:
            raise ValueError("Вид не пересекает страницу")
        zoom = MAX_SIDE_PX / max(clip.width, clip.height)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        pix.save(out_dir / "plan.png")

    extent = [
        pix.x / zoom,
        pix.y / zoom,
        (pix.x + pix.width) / zoom,
        (pix.y + pix.height) / zoom,
    ]
    (out_dir / "render.json").write_text(
        json.dumps(
            {"clip": extent, "zoom": zoom, "width_px": pix.width, "height_px": pix.height},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    base_rgb = pil_image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image = base_rgb.copy()
    draw = pil_draw.Draw(image)
    ox, oy, mm_per_pt = frame

    def draw_ring(ring: list[list[float]], color: str) -> None:
        points = [
            ((ox + x / mm_per_pt) * zoom - pix.x, (oy - y / mm_per_pt) * zoom - pix.y)
            for x, y in ring
        ]
        if len(points) >= 3:
            draw.line([*points, points[0]], fill=color, width=2)

    for group, color in (("constructions", "#e11d48"), ("frame_partitions", "#0284c7")):
        for row in walls.get(group, []):
            polygon = row["polygon"]
            for ring in [polygon["shell"], *polygon["holes"]]:
                draw_ring(ring, color)
    for opening in walls.get("openings", []):
        if opening.get("lintel"):
            draw_ring(opening["lintel"], "#15803d")
    image.save(out_dir / "overlay.png")

    render_slab_overlay(
        base_rgb=base_rgb,
        walls=walls,
        frame=frame,
        zoom=zoom,
        pix_x=pix.x,
        pix_y=pix.y,
        out_path=out_dir / "slab_overlay.png",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--walls", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--ox", type=float, required=True)
    parser.add_argument("--oy", type=float, required=True)
    parser.add_argument("--k", type=float, required=True)
    parser.add_argument("--view-zone", default=None)
    args = parser.parse_args()
    render_view(
        pdf_path=args.pdf,
        walls_path=args.walls,
        out_dir=args.out_dir,
        page_index=args.page,
        frame=(args.ox, args.oy, args.k),
        view_zone=_parse_zone(args.view_zone),
    )


if __name__ == "__main__":
    main()
