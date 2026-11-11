"""Сборка walls.json: DXF -> заливка -> конструкции -> проёмы -> итоги и проверки."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from cad_walls.constructions import Construction, build_constructions
from cad_walls.dxfin import read_dxf
from cad_walls.errors import Issue
from cad_walls.fill import build_fill
from cad_walls.framed import extract_frame_partitions
from cad_walls.heights import resolve_heights
from cad_walls.legend import Legend, MaterialHint, material_hints, read_legend
from cad_walls.openings import Opening, build_openings
from cad_walls.params import Params, load_params
from cad_walls.slab import SlabData, build_slab, lintel_shell
from cad_walls.version import GENERATOR_VERSION, SCHEMA

KIND_ORDER = ("masonry", "monolith_wall", "monolith_pylon", "monolith_column")


@dataclass(frozen=True)
class Built:
    """Готовый документ walls.json и сводка для stdout."""

    document: dict[str, object]
    constructions: int
    openings: int
    residue_ratio: float
    warnings: int


@dataclass(frozen=True)
class Args:
    dxf: Path
    params: Path | None
    out: Path
    pdf: Path | None = None
    page: int | None = None


def _r(x: float) -> float:
    return round(x, 1) + 0.0  # +0.0 убирает «-0.0»


def _ring(coords: Sequence[tuple[float, float]]) -> list[list[float]]:
    """Кольцо без повторного замыкающего узла."""
    return [[_r(x), _r(y)] for x, y in list(coords)[:-1]]


def _polygon(poly: Polygon) -> dict[str, object]:
    oriented = orient(poly, 1.0)
    clean = oriented.simplify(0.05, preserve_topology=True)
    if isinstance(clean, Polygon) and clean.is_valid and not clean.is_empty:
        oriented = orient(clean, 1.0)
    return {
        "shell": _ring(oriented.exterior.coords),
        "holes": [_ring(h.coords) for h in oriented.interiors],
    }


def _construction(c: Construction, hint: MaterialHint | None = None) -> dict[str, object]:
    cx, cy = c.polygon.centroid.x, c.polygon.centroid.y
    x0, y0, x1, y1 = c.polygon.bounds
    item: dict[str, object] = {
        "id": c.id,
        "kind": c.kind,
        "source_layers": c.source_layers,
        "polygon": _polygon(c.polygon),
        "area_plan_mm2": _r(c.polygon.area),
        "thickness_measured_mm": _r(c.thickness_measured),
        "thickness_nominal_mm": c.thickness_nominal,
        "thickness_status": "matched" if c.thickness_nominal is not None else "check",
        "length_axis_mm": _r(c.length_axis),
        "axis": [[[_r(x), _r(y)] for x, y in line] for line in c.axis],
        "centroid": [_r(cx), _r(cy)],
        "bbox": [_r(x0), _r(y0), _r(x1), _r(y1)],
    }
    if hint is not None:
        item["material_hint"] = hint.to_json()
    return item


def _lintel(o: Opening) -> list[list[float]] | None:
    shell = lintel_shell(o.axis_point or o.center, o.direction, o.width, o.thickness)
    return None if shell is None else [[_r(x), _r(y)] for x, y in shell]


def _slab(data: SlabData) -> dict[str, object] | None:
    if data.shell is None:
        return None
    return {
        "shell": _ring(data.shell.exterior.coords),
        "area_mm2": _r(data.shell.area),
        "close_radius_mm": _r(data.close_radius),
    }


def _slab_holes(data: SlabData) -> list[dict[str, object]]:
    return [
        {
            "id": f"h{i}",
            "shell": _ring(h.exterior.coords),
            "area_mm2": _r(h.area),
            "status": "candidate",
            "reason": "enclosed_no_door",
        }
        for i, h in enumerate(data.holes, start=1)
    ]


def _opening(o: Opening) -> dict[str, object]:
    return {
        "id": o.id,
        "kind": o.kind,
        "status": o.status,
        "host_id": o.host_id,
        "adjacent_ids": o.adjacent_ids,
        "width_mm": _r(o.width),
        "width_source": o.width_source,
        "thickness_mm": None if o.thickness is None else _r(o.thickness),
        "block_name": o.block_name,
        "handle": o.handle,
        "center": [_r(o.center[0]), _r(o.center[1])],
        "direction": None if o.direction is None else [o.direction[0], o.direction[1]],
        "lintel": _lintel(o),
    }


def _totals(cons: list[Construction]) -> list[dict[str, object]]:
    groups: dict[tuple[str, float | None], list[Construction]] = defaultdict(list)
    for c in cons:
        groups[(c.kind, c.thickness_nominal)].append(c)

    def order(key: tuple[str, float | None]) -> tuple[int, int, float]:
        kind, nominal = key
        return (KIND_ORDER.index(kind), 1 if nominal is None else 0, nominal or 0.0)

    return [
        {
            "kind": kind,
            "thickness_nominal_mm": nominal,
            "count": len(items),
            "area_plan_mm2": _r(sum(c.polygon.area for c in items)),
            "length_axis_mm": _r(sum(c.length_axis for c in items)),
        }
        for (kind, nominal), items in sorted(groups.items(), key=lambda kv: order(kv[0]))
    ]


def _legend(pdf: Path | None, page: int | None) -> Legend:
    """Легенда листа; без PDF или без текстового слоя — пустая (подсказки `no_legend`)."""
    if pdf is None or page is None:
        return Legend()
    return read_legend(pdf, page)


def build(args: Args) -> Built:
    params: Params = load_params(args.params)
    dxf = read_dxf(args.dxf, params)
    fill = build_fill(dxf, params)
    cons = build_constructions(
        fill, {"masonry": dxf.masonry_layers, "monolith": dxf.monolith_layers}, params
    )
    openings = build_openings(cons, dxf.doors, params)
    heights = resolve_heights(args.pdf, args.page, params)
    legend = _legend(args.pdf, args.page)
    hints = material_hints(cons, legend, params.num("legend_tolerance_mm"))
    frames = extract_frame_partitions(
        args.dxf,
        params,
        params.texts("frame_partition_layers"),
        params.nums("frame_partition_nominals_mm"),
    )

    area_union = sum(p.area for polys in fill.polygons.values() for p in polys)
    area_cons = sum(c.polygon.area for c in cons)
    residue = abs(area_union - area_cons) / area_union if area_union > 0 else 0.0
    slab = build_slab([p for polys in fill.polygons.values() for p in polys], params)
    issues: list[Issue] = [*fill.issues, *slab.issues]
    if residue > params.num("residue_tol"):
        issues.append(
            Issue(
                "area_residue",
                f"сумма площадей конструкций расходится с объединением на {residue:.4%}",
            )
        )
    document: dict[str, object] = {
        "schema": SCHEMA,
        "generator": GENERATOR_VERSION,
        "params_version": params.version,
        "params_sha256": params.sha256,
        "dxf_sha256": dxf.dxf_sha256,
        "units": "mm",
        "heights": heights,
        "legend": legend.to_json(),
        "constructions": [_construction(c, hints.get(c.id)) for c in cons],
        "frame_partitions": [_construction(c) for c in frames],
        "openings": [_opening(o) for o in openings],
        "slab": _slab(slab),
        "slab_holes": _slab_holes(slab),
        "totals": _totals(cons),
        "checks": {
            "area_union_mm2": _r(area_union),
            "area_constructions_mm2": _r(area_cons),
            "residue_ratio": round(residue, 6),
            "warnings": [{"code": i.code, "message": i.message} for i in issues],
        },
    }
    return Built(document, len(cons), len(openings), round(residue, 6), len(issues))


def generate(args: Args) -> dict[str, object]:
    """Строит walls.json и пишет его; возвращает краткую сводку для stdout."""
    built = build(args)
    text = json.dumps(built.document, ensure_ascii=False, separators=(",", ":")) + "\n"
    args.out.write_text(text, encoding="utf-8")
    return {
        "generator": GENERATOR_VERSION,
        "constructions": built.constructions,
        "openings": built.openings,
        "residue_ratio": built.residue_ratio,
        "warnings": built.warnings,
    }
