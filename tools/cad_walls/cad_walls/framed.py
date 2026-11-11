"""Каркасные перегородки из гипсокартона (система C112) как вид конструкции `frame_partition`.

Движок кладёт их в слои `07_C112_*`: обшивка (ГКЛВ) и каркасная зона — отдельные штриховки одной
перегородки. Штриховки читаются так же, как у кладки (dxfin), склеиваются в связные участки и
разбиваются на конструкции кодом кладки (constructions); отличаются только номиналы толщин и вид.
Поля результата те же, что у кладки: id, ось, толщина измеренная и номинальная, длина по оси.
"""

from __future__ import annotations

import fnmatch
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import shapely
from ezdxf.document import Drawing
from ezdxf.entities.hatch import Hatch
from ezdxf.filemanagement import readfile
from ezdxf.lldxf.const import DXFError
from shapely.geometry.base import BaseGeometry

from cad_walls.constructions import Construction, _stable_id, build_constructions
from cad_walls.dxfin import DxfInput, _hatch_geometry
from cad_walls.errors import WallsError
from cad_walls.fill import build_fill
from cad_walls.params import JsonValue, Params

KIND = "frame_partition"
DEFAULT_LAYER_PATTERNS: tuple[str, ...] = ("07_C112_*",)
DEFAULT_NOMINALS_MM: tuple[float, ...] = (75, 100, 125, 150, 175, 200)
UNION_LAYER = "frame_partition"


class _FramedParams(Params):
    """Параметры кладки с подменой номиналов и допуска толщины на значения каркасных перегородок."""

    def __init__(self, base: Params, nominals: tuple[float, ...], tolerance: float) -> None:
        super().__init__({}, base.sha256, base.version)
        self._base = base
        self._nominals = nominals
        self._tolerance = tolerance

    def _v(self, name: str) -> JsonValue:
        if name == "nominals_masonry_mm":
            return list(self._nominals)
        if name == "tolerance_masonry_mm":
            return self._tolerance
        return self._base._v(name)


def _load(source: Path | Drawing) -> Drawing:
    if isinstance(source, Drawing):
        doc = source
    else:
        try:
            doc = readfile(str(source))
        except (OSError, DXFError) as exc:
            raise WallsError("dxf_unreadable", f"DXF не читается: {exc}") from exc
    if int(doc.header.get("$INSUNITS", 4)) not in (0, 4):
        raise WallsError("dxf_units", "единицы DXF не миллиметры ($INSUNITS)")
    return doc


def read_frame_layers(
    source: Path | Drawing, params: Params, layer_patterns: Sequence[str]
) -> dict[str, BaseGeometry]:
    """Геометрия слоёв по шаблонам fnmatch: объединение штриховок каждого слоя."""
    doc = _load(source)
    arc_tol = params.num("arc_tolerance_mm")
    parts: dict[str, list[BaseGeometry]] = defaultdict(list)
    for entity in doc.modelspace():
        layer = str(entity.dxf.layer)
        if isinstance(entity, Hatch) and any(
            fnmatch.fnmatchcase(layer, pattern) for pattern in layer_patterns
        ):
            geom = _hatch_geometry(entity, arc_tol)
            if not geom.is_empty:
                parts[layer].append(geom)
    return {layer: shapely.union_all(parts[layer]) for layer in sorted(parts)}


def _close_gaps(geom: BaseGeometry, tol: float) -> BaseGeometry:
    """Смыкает зазоры шума CAD между соседними штриховками одной перегородки."""
    if tol <= 0:
        return geom
    return geom.buffer(tol, join_style="mitre").buffer(-tol, join_style="mitre")


def extract_frame_partitions(
    source: Path | Drawing,
    params: Params,
    layer_patterns: Sequence[str] = DEFAULT_LAYER_PATTERNS,
    nominals_mm: tuple[float, ...] = DEFAULT_NOMINALS_MM,
    tolerance_mm: float | None = None,
) -> list[Construction]:
    """Каркасные перегородки: штриховки слоёв -> связные участки -> конструкции `frame_partition`.

    Допуск толщины по умолчанию — как у кладки (`tolerance_masonry_mm`); номинал не найден —
    `thickness_nominal=None` (статус «check», как у кладки). Id содержат вид и не пересекаются с id
    кладки; одинаковые ключи получают суффикс `-N`.
    """
    layers = read_frame_layers(source, params, layer_patterns)
    if not layers:
        return []
    tol = params.num("tolerance_masonry_mm") if tolerance_mm is None else tolerance_mm
    joined = _close_gaps(shapely.union_all(list(layers.values())), params.num("simplify_tol_mm"))
    dxf = DxfInput(dxf_sha256="", masonry_layers={UNION_LAYER: joined})
    fill = build_fill(dxf, params)
    framed_params = _FramedParams(params, nominals_mm, tol)
    cons = build_constructions(fill, {"masonry": layers, "monolith": {}}, framed_params)
    used: dict[str, int] = {}
    for c in cons:
        c.kind = KIND
        c.family = KIND
        base = _stable_id(c)
        n = used.get(base, 0)
        used[base] = n + 1
        c.id = base if n == 0 else f"{base}-{n + 1}"
    return cons
