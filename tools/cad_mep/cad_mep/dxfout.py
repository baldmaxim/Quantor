"""3D DXF R2018 (мм): 3D-полилинии трасс + 2D-подложка стен (A-WALL из DXF вида, A-WALL-PDF)."""

from __future__ import annotations

from pathlib import Path

from ezdxf._options import options
from ezdxf.document import Drawing
from ezdxf.entities import Hatch, PolylinePath
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.filemanagement import new, readfile
from shapely.geometry import Polygon

from cad_mep.layers import (
    ANNO_LAYER,
    MARK_LAYERS,
    ROUTE_LAYERS,
    WALL_LAYER,
    WALL_PDF_LAYER,
)
from cad_mep.params import Params
from cad_mep.result import Result
from cad_mep.rooms import Model

DXF_UNITS_MM = 4


def write(
    m: Model,
    res: Result,
    path: Path,
    view_doc: Drawing,
    wall_polys: list[Polygon],
    params: Params,
    shift: tuple[float, float],
    floor_mm: float,
) -> dict[str, int]:
    """Записывает mep_routes.dxf в системе координат DXF вида (локальный сдвиг прибавляется)."""
    # фиксированные метаданные: файл воспроизводим побайтно при тех же входах
    options.write_fixed_meta_data_for_testing = True
    sx, sy = shift
    doc = new("R2018")
    doc.units = DXF_UNITS_MM
    doc.layers.new(WALL_LAYER, dxfattribs={"color": 8})
    doc.layers.new(WALL_PDF_LAYER, dxfattribs={"color": 9})
    for name, (_system, aci) in ROUTE_LAYERS.items():
        doc.layers.new(name, dxfattribs={"color": aci})
    for name, aci in MARK_LAYERS.items():
        doc.layers.new(name, dxfattribs={"color": aci})
    doc.layers.new(ANNO_LAYER, dxfattribs={"color": 7})
    msp = doc.modelspace()
    wall_layers = set(params.texts("dxf_wall_layers"))
    hatch_layers = set(params.texts("dxf_underlay_hatch_layers"))
    n_wall = 0
    for e in view_doc.modelspace():
        if isinstance(e, LWPolyline) and e.dxf.layer in wall_layers:
            pts = [(float(p[0]), float(p[1])) for p in e.get_points()]
            msp.add_lwpolyline(
                pts, close=bool(e.closed), dxfattribs={"layer": WALL_LAYER, "elevation": floor_mm}
            )
            n_wall += 1
        elif isinstance(e, Hatch) and e.dxf.layer in hatch_layers:
            for p in e.paths:
                if not isinstance(p, PolylinePath):
                    continue
                pts = [(float(v[0]), float(v[1])) for v in p.vertices]
                if len(pts) >= 3:
                    msp.add_lwpolyline(
                        pts, close=True, dxfattribs={"layer": WALL_LAYER, "elevation": floor_mm}
                    )
                    n_wall += 1
    n_pdf = 0
    for poly in wall_polys:
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        ring = [(x + sx, y + sy) for x, y in list(poly.exterior.coords)[:-1]]
        msp.add_lwpolyline(
            ring, close=True, dxfattribs={"layer": WALL_PDF_LAYER, "elevation": floor_mm}
        )
        n_pdf += 1
    n_lines = 0
    for ln in res.lines:
        if len(ln.pts) < 2:
            continue
        msp.add_polyline3d(
            [(round(x + sx, 1), round(y + sy, 1), round(z, 1)) for x, y, z in ln.pts],
            dxfattribs={"layer": ln.layer},
        )
        n_lines += 1
    for nd in res.nodes:
        radius = 60 if nd.layer == "M-RISER" else (90 if nd.kind == "meter" else 70)
        msp.add_circle((nd.xy[0] + sx, nd.xy[1] + sy, nd.z), radius, dxfattribs={"layer": nd.layer})
    text_h_apt, text_h_shaft = params.num("anno_height_apt_mm"), params.num("anno_height_shaft_mm")
    for ap in m.apts.values():
        pts = [m.comps[c].centroid for c in ap.comps]
        msp.add_text(
            ap.number,
            height=text_h_apt,
            dxfattribs={
                "layer": ANNO_LAYER,
                "insert": (
                    sum(p[0] for p in pts) / len(pts) + sx,
                    sum(p[1] for p in pts) / len(pts) + sy,
                    floor_mm,
                ),
            },
        )
    for sh in m.shafts:
        if sh.place == "mop" and any(s in sh.systems for s in ("ОВ", "ВК", "ПК")):
            msp.add_text(
                "/".join(sh.systems) + " " + sh.id,
                height=text_h_shaft,
                dxfattribs={
                    "layer": ANNO_LAYER,
                    "insert": (sh.centroid[0] + sx, sh.centroid[1] + sy, floor_mm),
                },
            )
    # ezdxf берёт классы из множества строк (порядок зависит от хеш-seed): фиксируем порядок заранее
    for name in sorted(doc.entitydb.dxf_types_in_use()):
        doc.classes.add_class(name)
    doc.classes.add_required_classes(doc.dxfversion)
    doc.saveas(str(path))
    reread = readfile(str(path))
    return {
        "audit_errors": len(reread.audit().errors),
        "wall_entities_view": n_wall,
        "wall_entities_pdf": n_pdf,
        "route_polylines": n_lines,
        "entities_total": len(reread.modelspace()),
    }
