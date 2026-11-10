"""DXF вида из движка: контуры стен (для привязки и подложки) и дверные блоки."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from ezdxf.document import Drawing
from ezdxf.entities.insert import Insert
from ezdxf.entities.line import Line
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.filemanagement import readfile
from ezdxf.lldxf.const import DXFError
from ezdxf.math import Matrix44
from numpy.typing import NDArray
from shapely.geometry import LineString, Polygon

from cad_mep.errors import MepError
from cad_mep.params import Params

Arr2 = NDArray[np.float64]


@dataclass
class Door:
    """Дверь: отрезок проёма от петли (a) до кончика закрытого полотна (b)."""

    id: str
    a: tuple[float, float]
    b: tuple[float, float]
    note: str = ""

    @property
    def mid(self) -> tuple[float, float]:
        return ((self.a[0] + self.b[0]) / 2, (self.a[1] + self.b[1]) / 2)

    @property
    def width(self) -> float:
        return float(np.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1]))

    def normal(self) -> tuple[float, float]:
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        n = float(np.hypot(dx, dy)) or 1.0
        return (-dy / n, dx / n)

    def barrier(self, pad: float = 0.0, half_t: float = 90.0) -> Polygon:
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        n = float(np.hypot(dx, dy)) or 1.0
        ux, uy = dx / n, dy / n
        a = (self.a[0] - ux * pad, self.a[1] - uy * pad)
        b = (self.b[0] + ux * pad, self.b[1] + uy * pad)
        poly = LineString([a, b]).buffer(half_t, cap_style="flat")
        if not isinstance(poly, Polygon):
            raise TypeError("барьер двери — не многоугольник")
        return poly


def read_dxf(path: Path) -> Drawing:
    try:
        return readfile(str(path))
    except (OSError, DXFError) as exc:
        raise MepError("dxf_unreadable", f"DXF вида не читается: {exc}") from exc


def wall_points(doc: Drawing, params: Params) -> Arr2:
    """Вершины контуров стен в мм DXF — для привязки к векторам PDF."""
    layers = set(params.texts("dxf_wall_layers"))
    pts: list[tuple[float, float]] = []
    for e in doc.modelspace():
        if isinstance(e, LWPolyline) and e.dxf.layer in layers:
            pts += [(float(p[0]), float(p[1])) for p in e.get_points()]
    return np.array(pts, dtype=np.float64).reshape(-1, 2)


def _fit_circle(pts: Arr2) -> tuple[Arr2, float]:
    a = np.c_[2 * pts[:, 0], 2 * pts[:, 1], np.ones(len(pts))]
    b = (pts**2).sum(1)
    sol = np.linalg.lstsq(a, b, rcond=None)[0]
    c = sol[:2]
    return c, float(np.sqrt(sol[2] + c @ c))


def load_doors(doc: Drawing, params: Params, shift: tuple[float, float]) -> list[Door]:
    """Двери из блоков: центр дуги — петля, конец дуги вдали от полотна — кончик закрытой двери.

    Координаты возвращаются в локальной системе (сдвиг shift вычитается).
    """
    near_mm = params.num("door_leaf_near_mm")
    min_arc_pts = params.count("door_arc_min_points")
    doors: list[Door] = []
    for e in doc.modelspace():
        if not isinstance(e, Insert):
            continue
        blk = doc.blocks[e.dxf.name]
        m = e.matrix44()

        def to_local(x: float, y: float, _m: Matrix44 = m) -> tuple[float, float]:
            v = _m.transform((x, y, 0))
            return (float(v.x) - shift[0], float(v.y) - shift[1])

        leaf_pts: list[tuple[float, float]] = []
        for x in blk:
            if isinstance(x, Line):
                leaf_pts += [(x.dxf.start.x, x.dxf.start.y), (x.dxf.end.x, x.dxf.end.y)]
        leaf = np.array(leaf_pts, dtype=np.float64).reshape(-1, 2)
        arcs = [x for x in blk if isinstance(x, LWPolyline) and len(x) >= min_arc_pts]
        for k, arc in enumerate(arcs):
            pts = np.array([(p[0], p[1]) for p in arc.get_points()], dtype=np.float64)
            c, _ = _fit_circle(pts)
            ends = [pts[0], pts[-1]]
            dist = [float(np.hypot(*(leaf - q).T).min()) if len(leaf) else 1e9 for q in ends]
            near = [d < near_mm for d in dist]
            if near[0] == near[1]:
                tip = ends[0] if dist[0] > dist[1] else ends[1]
                note = "ambiguous_leaf"
            else:
                tip = ends[1] if near[0] else ends[0]
                note = ""
            doors.append(
                Door(
                    f"{e.dxf.name}#{k}",
                    to_local(float(c[0]), float(c[1])),
                    to_local(float(tip[0]), float(tip[1])),
                    note,
                )
            )
    return doors
