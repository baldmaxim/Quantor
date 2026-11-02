"""Рукописные синтетические листы по форме вывода plangeom 0.1.0a2: без реальных данных.

Координаты в тестах пишутся в системе модели (мм, Y вверх, начало — пересечение осей), а в лист
plangeom переводятся функцией `sp`: Y вниз, начало сетки в точке (OX, OY).
"""

from __future__ import annotations

from building_model.canonical import BuildingModel
from building_model.params import Params
from building_model.pipeline import TenderArgs, build_model
from building_model.reader import Document, document_from_json

OX = 1000.0
OY = 2000.0
JsonObj = dict[str, object]


def sp(x: float, y: float) -> list[float]:
    """Точка модели -> точка листа plangeom."""
    return [x + OX, OY - y]


def axis(label: str, normal: tuple[float, float], offset: float, bubbles: int = 2) -> JsonObj:
    return {
        "label": label,
        "angle": 0.0,
        "normal": list(normal),
        "offset_mm": offset,
        "bubbles": bubbles,
    }


def default_axes() -> list[JsonObj]:
    # Вертикальная ось x = OX и горизонтальная y = OY: их пересечение — начало модели.
    return [axis("1", (1.0, 0.0), OX), axis("A", (0.0, 1.0), OY)]


def wall(
    wid: str,
    a: tuple[float, float],
    b: tuple[float, float],
    t: float = 200.0,
    role: str = "partition",
) -> JsonObj:
    half = t / 2.0
    return {
        "id": wid,
        "thickness_mm": t,
        "role": role,
        "polygon_mm": [
            sp(a[0], a[1] - half),
            sp(b[0], b[1] - half),
            sp(b[0], b[1] + half),
            sp(a[0], a[1] + half),
        ],
        "segments": [{"a": sp(*a), "b": sp(*b), "thickness_mm": t}],
    }


def door(
    did: str,
    hinge: tuple[float, float],
    end_a: tuple[float, float],
    end_b: tuple[float, float],
    opening: float,
    leaves: int = 1,
    host: str | None = None,
    gap: float | None = None,
    width: float | None = None,
) -> JsonObj:
    return {
        "id": did,
        "host_wall": host,
        "hinge_mm": sp(*hinge),
        "width_mm": width if width is not None else opening,
        "leaves": leaves,
        "opening_mm": opening,
        "gap_mm": gap,
        "end_a_mm": sp(*end_a),
        "end_b_mm": sp(*end_b),
    }


def gap_item(
    gid: str, a: tuple[float, float], b: tuple[float, float], width: float | None = None
) -> JsonObj:
    w = width if width is not None else abs(b[0] - a[0]) + abs(b[1] - a[1])
    return {"id": gid, "a_mm": sp(*a), "b_mm": sp(*b), "width_mm": w, "depth_mm": 200}


def make_sheet(page: int = 0, **overrides: object) -> JsonObj:
    base: JsonObj = {
        "plangeom_version": "0.1.0a2",
        "page": page,
        "verdict": "needs_review",
        "source": {"page": page, "width_pt": 2000.0, "height_pt": 1400.0, "page_in_volume": page},
        "scale": {"mm_per_pt": 35.0, "method": "axes+printed values", "confident": True},
        "kind": {"kind": "plan", "words": {}, "source": "title"},
        "section": "",
        "title": {"floors": [3], "level_m": 9.9},
        "floor_level": {"level_m": 9.9},
        "axes": default_axes(),
        "walls": [],
        "doors": [],
        "windows": [],
        "openings": [],
        "rooms": [],
        "stairs": [],
        "slab_outlines_mm": [],
    }
    base.update(overrides)
    return base


def document(*sheets: JsonObj, buildings: list[JsonObj] | None = None) -> Document:
    data: JsonObj = {"sheets": list(sheets), "buildings": buildings or []}
    return document_from_json(data)


def build(sheet: JsonObj, params: Params | None = None, page: int = 0) -> BuildingModel:
    return build_model(document(sheet), page, TenderArgs(), params)
