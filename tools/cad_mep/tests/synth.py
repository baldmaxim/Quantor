"""Синтетический этаж для тестов: PDF (заливки стен, подписи, экспликация) и DXF вида движка.

Здание 24 x 12 м: сквозной коридор шириной 1,88 м, по две квартиры (спальня, прихожая, кухня)
с каждой стороны, шахты ОВ/ВК и шкафы ПК на стене коридора, канализационная шахта ВК в квартире.
Данные придуманы, к чертежам заказчика отношения не имеют.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from ezdxf.filemanagement import new as new_dxf
from shapely.geometry import Polygon, box

SCALE = 70.0  # мм на пункт PDF
OX_PT, OY_PT = 40.0, 420.0  # начало DXF на листе (пт)
SHIFT = (1000.0, 2000.0)  # здание в DXF смещено от начала координат
WALL_FILL = (0.75, 0.75, 0.75)
T = 120.0  # толщина перегородки, мм
W, H = 24000.0, 12000.0

Rect = tuple[float, float, float, float]


def mx(x: float) -> float:
    return W - x


def my(y: float) -> float:
    return H - y


@dataclass
class Door:
    hinge: tuple[float, float]
    tip: tuple[float, float]


@dataclass
class Floor:
    walls: list[Rect] = field(default_factory=list)
    doors: list[Door] = field(default_factory=list)
    # подписи: (текст, x, y) в мм здания
    labels: list[tuple[str, float, float]] = field(default_factory=list)
    shaft_inner: list[Rect] = field(default_factory=list)


def _hwall(floor: Floor, y: float, x0: float, x1: float, gaps: list[tuple[float, float]]) -> None:
    edges = [x0]
    for g0, g1 in sorted(gaps):
        edges += [g0, g1]
    edges.append(x1)
    for a, b in zip(edges[::2], edges[1::2], strict=True):
        if b > a:
            floor.walls.append((a, y - T / 2, b, y + T / 2))


def _vwall(floor: Floor, x: float, y0: float, y1: float, gaps: list[tuple[float, float]]) -> None:
    edges = [y0]
    for g0, g1 in sorted(gaps):
        edges += [g0, g1]
    edges.append(y1)
    for a, b in zip(edges[::2], edges[1::2], strict=True):
        if b > a:
            floor.walls.append((x - T / 2, a, x + T / 2, b))


def _shaft(
    floor: Floor,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    sides: str = "WENS",
    t_we: float = T,
) -> None:
    """Короб шахты: стены по сторонам sides (боковые толщиной t_we) и его внутренняя область."""
    if "W" in sides:
        floor.walls.append((x0, y0, x0 + t_we, y1))
    if "E" in sides:
        floor.walls.append((x1 - t_we, y0, x1, y1))
    if "S" in sides:
        floor.walls.append((x0, y0, x1, y0 + T))
    if "N" in sides:
        floor.walls.append((x0, y1 - T, x1, y1))
    floor.shaft_inner.append(
        (
            x0 + (t_we if "W" in sides else 0.0),
            y0 + (T if "S" in sides else 0.0),
            x1 - (t_we if "E" in sides else 0.0),
            y1 - (T if "N" in sides else 0.0),
        )
    )


def build_floor(with_shafts: bool = True) -> Floor:
    f = Floor()
    # наружные стены
    f.walls += [(0, 0, W, 500), (0, H - 500, W, H), (0, 0, 500, H), (W - 500, 0, W, H)]
    # стены коридора (с проёмами входных дверей)
    gaps = [(8550.0, 9450.0), (mx(9450.0), mx(8550.0))]
    _hwall(f, 5000, 500, W - 500, gaps)
    _hwall(f, 7000, 500, W - 500, gaps)
    # границы между квартирами
    _vwall(f, 12000, 500, 4940, [])
    _vwall(f, 12000, 7060, H - 500, [])
    # южные квартиры: перегородки с дверями; северные — зеркально по y, восточные — по x
    for flip_x in (False, True):
        for flip_y in (False, True):
            fx = mx if flip_x else (lambda v: v)
            fy = my if flip_y else (lambda v: v)
            x_part = fx(6000.0)
            y_lo, y_hi = (500.0, 4940.0) if not flip_y else (my(4940.0), my(500.0))
            door_y = (3800.0, 4700.0)
            gy = (fy(door_y[0]), fy(door_y[1]))
            _vwall(f, x_part, y_lo, y_hi, [(min(gy), max(gy))])
            hx0, hx1 = (6060.0, 11940.0) if not flip_x else (mx(11940.0), mx(6060.0))
            gx = (fx(8550.0), fx(9450.0))
            _hwall(f, fy(3000.0), hx0, hx1, [(min(gx), max(gx))])
            f.doors.append(Door((x_part, fy(door_y[0])), (x_part, fy(door_y[1]))))
            f.doors.append(Door((fx(8550.0), fy(3000.0)), (fx(9450.0), fy(3000.0))))
            f.doors.append(Door((fx(8550.0), fy(5000.0)), (fx(9450.0), fy(5000.0))))
    if with_shafts:
        # ОВ и ПК — на северной стене коридора, ВК и ПК рядом с ним — на южной; короб выступает
        # в коридор на 0,4 м, боковые стены толще (300 мм), чтобы выход шахты был строго в коридор
        for x0, x1 in ((1500.0, 2500.0), (3300.0, 4300.0), (21500.0, 22500.0)):
            _shaft(f, x0, 6540, x1, 6940, sides="WES", t_we=300)
        for x0, x1 in ((12300.0, 13300.0), (13000.0, 14000.0)):
            _shaft(f, x0, 5060, x1, 5460, sides="WEN", t_we=300)
            f.walls.append((x0, 4740, x1, 4940))  # утолщение стены со стороны квартиры
        # канализационный стояк в кухне юго-западной квартиры (стена снизу — наружная)
        _shaft(f, 10800, 500, 11400, 1100, sides="WEN")
        for text, (x0, y0, x1, y1) in zip(
            ["ОВ", "ПК", "ОВ", "ВК", "ПК", "ВК"], f.shaft_inner, strict=True
        ):
            f.labels.append((text, (x0 + x1) / 2, (y0 + y1) / 2))
    # марки помещений: квартиры 1..4 (юг-запад, юг-восток, север-запад, север-восток), коридор
    marks: dict[int, list[tuple[float, float]]] = {
        1: [(3000, 2700), (9000, 4000), (9000, 1700)],
        2: [(mx(3000), 2700), (mx(9000), 4000), (mx(9000), 1700)],
        3: [(3000, my(2700)), (9000, my(4000)), (9000, my(1700))],
        4: [(mx(3000), my(2700)), (mx(9000), my(4000)), (mx(9000), my(1700))],
    }
    for k, pts in marks.items():
        for n, (x, y) in enumerate(pts, start=1):
            f.labels.append((f"1-{k}/{n}", x, y))
    f.labels.append(("1-0.1", 7000.0, 6000.0))
    return f


EXPL_NAMES = {1: "Спальня", 2: "Прихожая", 3: "Кухня"}
EXPL_AREAS = {1: 24.15, 2: 11.05, 3: 14.35}


def _pt(x_mm: float, y_mm: float) -> tuple[float, float]:
    """Миллиметры здания -> пункты листа."""
    return (OX_PT + (x_mm + SHIFT[0]) / SCALE, OY_PT - (y_mm + SHIFT[1]) / SCALE)


FONT = pymupdf.Font("helv")  # встроенный шрифт с кириллицей: base-14 через insert_text её теряет


def _text(tw: pymupdf.TextWriter, text: str, x: float, y: float) -> None:
    """Текст с левым краем в x и базовой линией y."""
    tw.append((x, y), text, font=FONT, fontsize=6)


def _put(tw: pymupdf.TextWriter, text: str, cx: float, cy: float) -> None:
    """Текст с центром в (cx, cy)."""
    width = FONT.text_length(text, fontsize=6)
    _text(tw, text, cx - width / 2, cy + 2.0)


def write_pdf(floor: Floor, path: Path, elevation_text: str | None = "+47,600") -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=900, height=500)
    for x0, y0, x1, y1 in floor.walls:
        a, b = _pt(x0, y1), _pt(x1, y0)
        page.draw_rect(pymupdf.Rect(a[0], a[1], b[0], b[1]), color=None, fill=WALL_FILL)
    tw = pymupdf.TextWriter(page.rect)
    for text, x, y in floor.labels:
        px, py = _pt(x, y)
        _put(tw, text, px, py)
    # номера квартир на поле листа
    for k in range(1, 5):
        px, py = _pt(2000.0 + 5000.0 * k, H + 600.0)
        _text(tw, "Кв", px, py)
        _text(tw, f"101{k}", px + 12, py)
    if elevation_text:
        px, py = _pt(20000.0, H + 600.0)
        _text(tw, elevation_text, px, py)
    # экспликация правее плана
    y = 60.0
    for k in range(1, 5):
        for n in (1, 2, 3):
            _text(tw, f"1-{k}/{n}", 450, y)
            _text(tw, EXPL_NAMES[n], 500, y)
            _text(tw, f"{EXPL_AREAS[n]:.2f}".replace(".", ","), 580, y)
            y += 10.0
    _text(tw, "1-0.1", 450, y)
    _text(tw, "Коридор", 500, y)
    _text(tw, "41,30", 580, y)
    tw.write_text(page)
    doc.save(str(path))
    doc.close()


def write_view_dxf(floor: Floor, path: Path) -> None:
    doc = new_dxf("R2018")
    doc.units = 4
    doc.layers.new("01_КОНТУРЫ_СТЕН")
    doc.layers.new("03_ДВЕРИ_БЛОКИ")
    msp = doc.modelspace()
    sx, sy = SHIFT
    for x0, y0, x1, y1 in floor.walls:
        pts = [(x0 + sx, y0 + sy), (x1 + sx, y0 + sy), (x1 + sx, y1 + sy), (x0 + sx, y1 + sy)]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "01_КОНТУРЫ_СТЕН"})
    for i, d in enumerate(floor.doors):
        name = f"AR_DOOR_BLOCK_{i:03d}"
        blk = doc.blocks.new(name)
        blk.add_line((0, 0), (0, 900))
        arc = [
            (900 * math.cos(math.radians(a)), 900 * math.sin(math.radians(a)))
            for a in range(0, 91, 10)
        ]
        blk.add_lwpolyline(arc)
        ux, uy = d.tip[0] - d.hinge[0], d.tip[1] - d.hinge[1]
        angle = math.degrees(math.atan2(uy, ux))
        msp.add_blockref(
            name,
            (d.hinge[0] + sx, d.hinge[1] + sy),
            dxfattribs={"layer": "03_ДВЕРИ_БЛОКИ", "rotation": angle},
        )
    doc.saveas(str(path))


def write_inputs(
    floor: Floor, folder: Path, elevation_text: str | None = "+47,600"
) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    pdf, dxf = folder / "floor.pdf", folder / "plan_candidates.dxf"
    write_pdf(floor, pdf, elevation_text)
    write_view_dxf(floor, dxf)
    scale = folder / "scale.json"
    scale.write_text(
        json.dumps({"status": "passed", "scale_used_for_geometry": SCALE}), encoding="utf-8"
    )
    bbox = [SHIFT[0] - 200.0, SHIFT[1] - 200.0, SHIFT[0] + W + 200.0, SHIFT[1] + H + 200.0]
    preview = folder / "preview.json"
    preview.write_text(
        json.dumps(
            {
                "schema": "quantor.cad_engine.preview.v1",
                "units": "mm",
                "bbox": bbox,
                "layers": ["01_КОНТУРЫ_СТЕН"],
                "paths": [],
                "points": 0,
                "flatten_mm": 5.0,
                "skipped": {},
                "truncated": False,
                "dxf": "views/p001_v01/plan_candidates.dxf",
                "dxf_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )
    return {"pdf": pdf, "dxf": dxf, "scale": scale, "preview": preview}


def wall_union_polys(floor: Floor) -> list[Polygon]:
    sx, sy = SHIFT
    return [box(x0 + sx, y0 + sy, x1 + sx, y1 + sy) for x0, y0, x1, y1 in floor.walls]


def shaft_inner_boxes(floor: Floor) -> list[Polygon]:
    sx, sy = SHIFT
    return [box(x0 + sx, y0 + sy, x1 + sx, y1 + sy) for x0, y0, x1, y1 in floor.shaft_inner]
