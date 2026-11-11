"""Чтение DXF вида: штриховки кладки и монолита по слоям и блоки дверей.

Штриховка читается вместе с контурами-отверстиями по чётно-нечётному правилу вложенности:
флаги external/outermost в выходе движка и в чужих DXF расставлены непоследовательно, а
вложенность однозначна. Дуги границы спрямляются с допуском из params.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf.bbox
import ezdxf.path
import shapely
from ezdxf.entities.hatch import Hatch
from ezdxf.entities.insert import Insert
from ezdxf.filemanagement import readfile
from ezdxf.lldxf.const import DXFError
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from cad_walls.errors import WallsError
from cad_walls.params import Params

MIN_RING_AREA_MM2 = 1.0


@dataclass(frozen=True)
class Door:
    """Блок двери: центр и размеры bbox (включает дугу открывания)."""

    block_name: str
    handle: str
    center: tuple[float, float]
    width: float
    height: float

    @property
    def max_side(self) -> float:
        return max(self.width, self.height)


@dataclass
class DxfInput:
    """Содержимое DXF: геометрия по слоям (объединение штриховок слоя) и двери."""

    dxf_sha256: str
    masonry_layers: dict[str, BaseGeometry] = field(default_factory=dict)
    monolith_layers: dict[str, BaseGeometry] = field(default_factory=dict)
    doors: list[Door] = field(default_factory=list)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ring(points: list[tuple[float, float]]) -> Polygon | None:
    if len(points) < 3:
        return None
    poly = Polygon(points)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area < MIN_RING_AREA_MM2:
        return None
    if poly.geom_type != "Polygon":
        poly = max(shapely.get_parts(poly), key=lambda g: g.area)
    return poly if isinstance(poly, Polygon) else None


def even_odd(rings: list[Polygon]) -> BaseGeometry:
    """Заливка по чётно-нечётному правилу: чётная вложенность — материал, нечётная — дыра."""
    if not rings:
        return Polygon()
    rings = sorted(rings, key=lambda r: (-r.area, r.bounds))
    probes = [r.representative_point() for r in rings]
    depth = [sum(1 for j in range(i) if rings[j].contains(probes[i])) for i in range(len(rings))]
    result: BaseGeometry = Polygon()
    for level in range(max(depth) + 1):
        group = [r for r, d in zip(rings, depth, strict=True) if d == level]
        merged = shapely.union_all(group)
        result = result.union(merged) if level % 2 == 0 else result.difference(merged)
    return result


def _hatch_geometry(hatch: Hatch, arc_tol: float) -> BaseGeometry:
    ocs = hatch.ocs()
    elevation = float(hatch.dxf.elevation.z)
    rings: list[Polygon] = []
    for boundary in hatch.paths:
        path = ezdxf.path.from_hatch_boundary_path(boundary, ocs=ocs, elevation=elevation)
        for sub in path.sub_paths():
            pts = [(float(v.x), float(v.y)) for v in sub.flattening(arc_tol)]
            ring = _ring(pts)
            if ring is not None:
                rings.append(ring)
    return even_odd(rings)


def _door(entity: Insert) -> Door | None:
    box = ezdxf.bbox.extents([entity])
    if not box.has_data:
        return None
    ext = box.extmax - box.extmin
    mid = (box.extmin + box.extmax) / 2
    return Door(
        block_name=str(entity.dxf.name),
        handle=str(entity.dxf.handle),
        center=(float(mid.x), float(mid.y)),
        width=float(ext.x),
        height=float(ext.y),
    )


def read_dxf(path: Path, params: Params) -> DxfInput:
    """Читает DXF; нечитаемый файл — ошибка входа."""
    try:
        doc = readfile(str(path))
    except (OSError, DXFError) as exc:
        raise WallsError("dxf_unreadable", f"DXF не читается: {exc}") from exc
    if int(doc.header.get("$INSUNITS", 4)) not in (0, 4):
        raise WallsError("dxf_units", "единицы DXF не миллиметры ($INSUNITS)")
    masonry = set(params.texts("layers_masonry"))
    monolith = set(params.texts("layers_monolith"))
    doors_layers = set(params.texts("layers_doors"))
    arc_tol = params.num("arc_tolerance_mm")
    out = DxfInput(dxf_sha256=file_sha256(path))
    parts: dict[str, dict[str, list[BaseGeometry]]] = {"masonry": {}, "monolith": {}}
    for entity in doc.modelspace():
        layer = str(entity.dxf.layer)
        if isinstance(entity, Hatch) and (layer in masonry or layer in monolith):
            geom = _hatch_geometry(entity, arc_tol)
            if not geom.is_empty:
                bucket = parts["masonry" if layer in masonry else "monolith"]
                bucket.setdefault(layer, []).append(geom)
        elif isinstance(entity, Insert) and layer in doors_layers:
            door = _door(entity)
            if door is not None:
                out.doors.append(door)
    for layer in sorted(parts["masonry"]):
        out.masonry_layers[layer] = shapely.union_all(parts["masonry"][layer])
    for layer in sorted(parts["monolith"]):
        out.monolith_layers[layer] = shapely.union_all(parts["monolith"][layer])
    out.doors.sort(key=lambda d: (d.handle, d.block_name))
    return out
