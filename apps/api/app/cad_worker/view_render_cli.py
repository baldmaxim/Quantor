"""Рендер снимков вида CAD (`plan.png`, `overlay.png`, `render.json`) в окружении движка.

Скрипт запускается только подпроцессом `cad-worker` через интерпретатор CAD-движка:
`PyMuPDF` и `Pillow` импортируются лениво внутри функции и никогда не попадают в процесс API.
Координатная сетка и цвета наложения совпадают с `ai_review_cli.py`:
- `plan.png` — исходная страница PDF (или вырезка по `view_zone`), длинная сторона до 2000 px;
- `overlay.png` — тот же растр с контурами `walls.json` (стены `#e11d48`, каркасные `#0284c7`,
  перемычки дверей `#15803d`);
- `render.json` — `{"clip": [x0, y0, x1, y1], "zoom": float, "width_px": int, "height_px": int}`
  для точного перевода `bbox_px` -> `bbox_pt` страницы PDF.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MAX_SIDE_PX = 2000


def _parse_zone(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    parts = [float(item) for item in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("view-zone: нужны 4 числа x0,y0,x1,y1")
    return (parts[0], parts[1], parts[2], parts[3])


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
    from PIL import Image, ImageDraw  # type: ignore[import-not-found]

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

    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    draw = ImageDraw.Draw(image)
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
