"""Привязка листа plangeom к PDF: поворот страницы и совпадение контуров стен с объектами PDF.

Команда запускается в окружении оценки (pypdfium2 есть, Pydantic может не быть), поэтому модуль
не импортирует Pydantic-модели пакета: вход читается как обычный JSON. Печатаются только числа.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

Pt = tuple[float, float]
Box = tuple[float, float, float, float]  # l, b, r, t в пользовательских координатах страницы

ROTATIONS = (0, 90, 180, 270)
MATCH_TOL_PT = 3.0
DIMS_TOL_PT = 1.0


@dataclass(frozen=True)
class PageGeometry:
    rotate: int
    mediabox: Box
    cropbox: Box
    boxes_depth0: list[Box]
    boxes_all: list[Box]


def read_raw_sheet(input_path: Path, page: int) -> dict[str, object]:
    with input_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    sheets = data["sheets"] if isinstance(data, dict) and "sheets" in data else [data]
    for sheet in sheets:
        if isinstance(sheet, dict) and sheet.get("page") == page:
            return {str(k): v for k, v in sheet.items()}
    raise ValueError(f"в комплекте нет страницы {page}")


def read_pdf_page(pdf_path: Path, page_index: int) -> PageGeometry:
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[page_index]
    boxes_all: list[Box] = []
    boxes_depth0: list[Box] = []
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_PATH], max_depth=15):
        left, bottom, right, top = obj.get_bounds()
        box = (float(left), float(bottom), float(right), float(top))
        boxes_all.append(box)
        if getattr(obj, "level", 0) == 0:
            boxes_depth0.append(box)
    media = page.get_mediabox()
    crop = page.get_cropbox()
    return PageGeometry(
        rotate=int(page.get_rotation()),
        mediabox=(float(media[0]), float(media[1]), float(media[2]), float(media[3])),
        cropbox=(float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3])),
        boxes_depth0=boxes_depth0,
        boxes_all=boxes_all,
    )


def sheet_to_user(u: float, v: float, rotation: int, crop: Box) -> Pt:
    """Точка листа plangeom (pt, Y вниз от левого верхнего угла вида) -> координаты страницы.

    rotation — на сколько по часовой стрелке вид повёрнут относительно неповёрнутой страницы.
    """
    x0, y0, x1, y1 = crop
    w, _h = x1 - x0, y1 - y0
    if rotation == 0:
        return (x0 + u, y1 - v)
    if rotation == 90:
        return (x0 + v, y0 + u)
    if rotation == 180:
        return (x0 + w - u, y0 + v)
    return (x0 + w - v, y1 - u)


def user_to_display(x: float, y: float, rotate: int, crop: Box) -> Pt:
    """Координаты страницы -> вид, как его рисует отрисовщик с учётом /Rotate (pt, Y вниз)."""
    x0, y0, x1, y1 = crop
    w, h = x1 - x0, y1 - y0
    xp, yp = x - x0, y1 - y
    if rotate == 0:
        return (xp, yp)
    if rotate == 90:
        return (h - yp, xp)
    if rotate == 180:
        return (w - xp, h - yp)
    return (yp, w - xp)


def view_size(rotation: int, crop: Box) -> Pt:
    w, h = crop[2] - crop[0], crop[3] - crop[1]
    return (w, h) if rotation in (0, 180) else (h, w)


class BoxIndex:
    """Сетка угловых точек рамок: поиск рамки, совпадающей с заданной по всем четырём сторонам."""

    def __init__(self, boxes: list[Box], tol: float) -> None:
        self._tol = tol
        self._cells: dict[tuple[int, int], list[Box]] = defaultdict(list)
        for box in boxes:
            self._cells[(math.floor(box[0] / tol), math.floor(box[1] / tol))].append(box)

    def has_match(self, box: Box) -> bool:
        cx, cy = math.floor(box[0] / self._tol), math.floor(box[1] / self._tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for cand in self._cells.get((cx + dx, cy + dy), ()):
                    if all(abs(cand[i] - box[i]) <= self._tol for i in range(4)):
                        return True
        return False


def wall_polygons_pt(sheet: dict[str, object]) -> list[list[Pt]]:
    scale = sheet.get("scale")
    mm_per_pt = scale.get("mm_per_pt") if isinstance(scale, dict) else None
    walls = sheet.get("walls")
    if not isinstance(mm_per_pt, (int, float)) or not mm_per_pt or not isinstance(walls, list):
        raise ValueError("у листа нет масштаба или стен")
    result: list[list[Pt]] = []
    for wall in walls:
        poly = wall.get("polygon_mm") if isinstance(wall, dict) else None
        if isinstance(poly, list) and len(poly) >= 3:
            result.append([(float(p[0]) / mm_per_pt, float(p[1]) / mm_per_pt) for p in poly])
    return result


def match_share(polygons: list[list[Pt]], rotation: int, crop: Box, index: BoxIndex) -> float:
    if not polygons:
        return 0.0
    hits = 0
    for poly in polygons:
        pts = [sheet_to_user(u, v, rotation, crop) for u, v in poly]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if index.has_match((min(xs), min(ys), max(xs), max(ys))):
            hits += 1
    return hits / len(polygons)


def evaluate_rotations(
    sheet: dict[str, object], geometry: PageGeometry
) -> tuple[dict[int, float], list[list[Pt]]]:
    polygons = wall_polygons_pt(sheet)
    index = BoxIndex(geometry.boxes_all, MATCH_TOL_PT)
    shares = {r: match_share(polygons, r, geometry.cropbox, index) for r in ROTATIONS}
    return shares, polygons


def _size(box: Box) -> Pt:
    return (box[2] - box[0], box[3] - box[1])


def best_rotation(shares: dict[int, float], default: int) -> int:
    top = max(shares.values())
    if top <= 0.0:
        return default
    return min((r for r, s in shares.items() if s == top), key=lambda r: (r != default, r))


def check_binding(input_path: Path, page: int, pdf_path: Path) -> int:
    sheet = read_raw_sheet(input_path, page)
    source = sheet.get("source")
    if not isinstance(source, dict):
        raise ValueError("у листа нет source")
    page_index = int(source.get("page_in_volume", page))
    geometry = read_pdf_page(pdf_path, page_index)
    shares, polygons = evaluate_rotations(sheet, geometry)
    width_pt, height_pt = float(source["width_pt"]), float(source["height_pt"])
    cw, ch = _size(geometry.cropbox)
    mw, mh = _size(geometry.mediabox)
    scale = sheet.get("scale")
    mm_per_pt = scale.get("mm_per_pt") if isinstance(scale, dict) else None
    print(f"страница комплекта: {page}, индекс в PDF: {page_index}")
    print(f"лист plangeom: {width_pt:.1f} x {height_pt:.1f} pt, mm_per_pt={mm_per_pt}")
    print(f"/Rotate: {geometry.rotate}")
    print(f"mediabox: {mw:.1f} x {mh:.1f} pt; cropbox: {cw:.1f} x {ch:.1f} pt")
    print(f"cropbox совпадает с mediabox: {geometry.cropbox == geometry.mediabox}")
    for label, (a, b) in (
        ("без поворота", (cw, ch)),
        ("с поворотом на 90", (ch, cw)),
    ):
        ok = abs(width_pt - a) <= DIMS_TOL_PT and abs(height_pt - b) <= DIMS_TOL_PT
        print(f"размер листа plangeom == размер вида {label}: {ok}")
    print(
        f"векторных объектов-путей: {len(geometry.boxes_all)} "
        f"(на верхнем уровне {len(geometry.boxes_depth0)})"
    )
    print(f"стен с контуром проверено: {len(polygons)}; допуск {MATCH_TOL_PT} pt")
    for r in ROTATIONS:
        vw, vh = view_size(r, geometry.cropbox)
        dims = abs(width_pt - vw) <= DIMS_TOL_PT and abs(height_pt - vh) <= DIMS_TOL_PT
        print(f"поворот {r:>3}: доля совпавших стен {shares[r]:.3f}; размер вида сходится: {dims}")
    best = best_rotation(shares, geometry.rotate)
    if shares[best] <= 0.0:
        print("совпавший поворот: ни один не дал совпадений")
    else:
        print(f"совпавший поворот: {best}; равен /Rotate: {best == geometry.rotate}")
    return 0
