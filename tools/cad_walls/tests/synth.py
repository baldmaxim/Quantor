"""Синтетические DXF и PDF для тестов: никаких клиентских данных."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import pymupdf
from ezdxf.document import Drawing
from ezdxf.filemanagement import new
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from cad_walls.pipeline import Args, build

MASONRY = "01_КЛАДКА_И_ПЕРЕГОРОДКИ"
MONOLITH = "02_МОНОЛИТ"
DOORS = "03_ДВЕРИ_БЛОКИ"

Pts = Sequence[tuple[float, float]]


def new_doc() -> tuple[Drawing, Modelspace]:
    doc = new("R2018")
    doc.header["$INSUNITS"] = 4
    for layer in (MASONRY, MONOLITH, DOORS):
        doc.layers.add(layer)
    return doc, doc.modelspace()


def add_hatch(msp: Modelspace, layer: str, outer: Pts, holes: Sequence[Pts] = ()) -> None:
    hatch = msp.add_hatch(dxfattribs={"layer": layer})
    hatch.paths.add_polyline_path(list(outer), is_closed=True, flags=1)
    for hole in holes:
        hatch.paths.add_polyline_path(list(hole), is_closed=True, flags=0)


def add_poly(msp: Modelspace, layer: str, poly: Polygon) -> None:
    """Штриховка по полигону shapely: внешний контур и отверстия."""
    add_hatch(
        msp,
        layer,
        list(poly.exterior.coords)[:-1],
        [list(h.coords)[:-1] for h in poly.interiors],
    )


def add_rect(msp: Modelspace, layer: str, x0: float, y0: float, x1: float, y1: float) -> None:
    add_hatch(msp, layer, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def add_union(msp: Modelspace, layer: str, *boxes: tuple[float, float, float, float]) -> Polygon:
    """Один связный полигон из прямоугольников (Г-образная, Т-образная стена и т. п.)."""
    poly = unary_union([box(*b) for b in boxes])
    assert isinstance(poly, Polygon)
    add_poly(msp, layer, poly)
    return poly


def add_round_end_wall(msp: Modelspace, layer: str, length: float, thick: float) -> None:
    """Стена с полукруглым торцом: контур из линий и дуги (edge-путь штриховки)."""
    r = thick / 2
    hatch = msp.add_hatch(dxfattribs={"layer": layer})
    edges = hatch.paths.add_edge_path(flags=1)
    edges.add_line((0, 0), (length, 0))
    edges.add_arc((length, r), r, -90, 90, ccw=True)
    edges.add_line((length, thick), (0, thick))
    edges.add_line((0, thick), (0, 0))


def add_door(
    doc: Drawing, msp: Modelspace, name: str, x0: float, y0: float, x1: float, y1: float
) -> None:
    """Блок двери: прямоугольник bbox (с дугой открывания) и одна вставка."""
    block = doc.blocks.new(name)
    block.add_lwpolyline([(0, 0), (x1 - x0, 0), (x1 - x0, y1 - y0), (0, y1 - y0)], close=True)
    msp.add_blockref(name, (x0, y0), dxfattribs={"layer": DOORS})


def run(
    tmp_path: Path, doc: Drawing, pdf: Path | None = None, page: int | None = None
) -> dict[str, object]:
    path = tmp_path / "plan.dxf"
    doc.saveas(str(path))
    return build(
        Args(dxf=path, params=None, out=tmp_path / "walls.json", pdf=pdf, page=page)
    ).document


def arc_area(length: float, thick: float) -> float:
    return length * thick + math.pi * (thick / 2) ** 2 / 2


FONT = pymupdf.Font("helv")


def make_pdf(path: Path, titles: Sequence[str]) -> Path:
    """PDF с одним заголовком плана на странице."""
    doc = pymupdf.open()
    for text in titles:
        page = doc.new_page(width=900, height=500)
        tw = pymupdf.TextWriter(page.rect)
        tw.append((100.0, 450.0), text, font=FONT, fontsize=8)
        tw.write_text(page)
    doc.save(str(path))
    doc.close()
    return path
