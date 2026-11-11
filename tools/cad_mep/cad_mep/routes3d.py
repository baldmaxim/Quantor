"""routes3d.json (cad_mep_routes3d.v1): 3D-полилинии трасс и стояков с Z от отметки этажа."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cad_mep.result import Result

ROUTES3D_SCHEMA = "cad_mep_routes3d.v1"
ROUTES3D_FRAME = "view_dxf_mm"


@dataclass(frozen=True)
class Routes3d:
    floor_elevation_mm: int
    floor_height_mm: int
    polylines: list[tuple[str, list[tuple[int, int, int]]]]


def build(
    res: Result,
    shift: tuple[float, float],
    floor_elevation_mm: float,
    floor_height_mm: float,
) -> Routes3d:
    """Те же линии и в тех же координатах (мм DXF вида), что пишет dxfout в mep_routes.dxf.

    z_rel - высота над отметкой этажа (верх плиты = чистый пол).
    """
    sx, sy = shift
    polylines: list[tuple[str, list[tuple[int, int, int]]]] = []
    for ln in res.lines:
        if len(ln.pts) < 2:  # как в dxfout: вырожденные линии в DXF не попадают
            continue
        pts = [(round(x + sx), round(y + sy), round(z - floor_elevation_mm)) for x, y, z in ln.pts]
        polylines.append((ln.layer, pts))
    return Routes3d(round(floor_elevation_mm), round(floor_height_mm), polylines)


def write(path: Path, routes: Routes3d) -> None:
    """Шапка и по одной полилинии на строку: файл крупный, построчно читается и сравнивается."""
    head = {
        "schema": ROUTES3D_SCHEMA,
        "frame": ROUTES3D_FRAME,
        "floor_elevation_mm": routes.floor_elevation_mm,
        "floor_height_mm": routes.floor_height_mm,
    }
    rows = ",\n".join(
        json.dumps(
            {"layer": layer, "pts": [list(p) for p in pts]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for layer, pts in routes.polylines
    )
    head_text = json.dumps(head, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f'{head_text[:-1]},"polylines":[\n{rows}\n]}}\n', encoding="utf-8")
