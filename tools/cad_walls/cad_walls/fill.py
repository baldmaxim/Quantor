"""Заливка кладки и монолита: объединение по виду, чистка, разрешение перекрытия."""

from __future__ import annotations

from dataclasses import dataclass, field

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from cad_walls.dxfin import MIN_RING_AREA_MM2, DxfInput
from cad_walls.errors import Issue
from cad_walls.params import Params

KINDS = ("masonry", "monolith")


@dataclass
class Fill:
    """Связные куски заливки по виду; перекрытие кладки с монолитом отдано монолиту."""

    polygons: dict[str, list[Polygon]]
    issues: list[Issue] = field(default_factory=list)


def _clean(geom: BaseGeometry, p: Params) -> list[Polygon]:
    min_hole = p.num("min_hole_area_mm2")
    tol = p.num("simplify_tol_mm")
    out: list[Polygon] = []
    for part in shapely.get_parts(geom.buffer(0)):
        if not isinstance(part, Polygon) or part.is_empty:
            continue
        holes = [h for h in part.interiors if Polygon(h).area >= min_hole]
        poly = Polygon(part.exterior, holes)
        if tol > 0:
            simple = poly.simplify(tol, preserve_topology=True)
            if isinstance(simple, Polygon) and simple.is_valid and not simple.is_empty:
                poly = simple
        if poly.area >= MIN_RING_AREA_MM2:
            out.append(poly)
    out.sort(key=lambda g: (round(g.bounds[0], 1), round(g.bounds[1], 1), round(g.area, 1)))
    return out


def build_fill(dxf: DxfInput, p: Params) -> Fill:
    masonry = shapely.union_all(list(dxf.masonry_layers.values())) if dxf.masonry_layers else None
    monolith = (
        shapely.union_all(list(dxf.monolith_layers.values())) if dxf.monolith_layers else None
    )
    issues: list[Issue] = []
    if masonry is not None and monolith is not None:
        overlap = masonry.intersection(monolith).area
        if overlap > p.num("overlap_tol_mm2"):
            issues.append(
                Issue(
                    "masonry_monolith_overlap",
                    f"кладка и монолит перекрываются на {overlap / 1e6:.3f} м²: "
                    "перекрытие отнесено монолиту",
                )
            )
        masonry = masonry.difference(monolith)
    polygons = {
        "masonry": _clean(masonry, p) if masonry is not None else [],
        "monolith": _clean(monolith, p) if monolith is not None else [],
    }
    if not polygons["masonry"] and not polygons["monolith"]:
        issues.append(
            Issue("no_fill", "в DXF нет штриховок кладки и монолита по слоям из параметров")
        )
    return Fill(polygons, issues)
