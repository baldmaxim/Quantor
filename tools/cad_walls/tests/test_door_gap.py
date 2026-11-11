"""Двери v1.4: торец с Т-примыканием, поиск разрыва вдоль оси, перемычка по сечениям, полотно."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from shapely.geometry import Polygon

from tests import synth

Obj = dict[str, object]
Pt = list[float]


def _f(value: object) -> float:
    assert isinstance(value, int | float)
    return float(value)


def _poly(ring: object) -> Polygon:
    return Polygon([(_f(p[0]), _f(p[1])) for p in cast(list[Pt], ring)])


def _cons_union(doc: Obj) -> Polygon:
    polys = [
        Polygon([(_f(p[0]), _f(p[1])) for p in cast(list[Pt], cast(Obj, c["polygon"])["shell"])])
        for c in cast(list[Obj], doc["constructions"])
    ]
    union = polys[0]
    for p in polys[1:]:
        union = union.union(p)
    return union


def test_door_beside_perpendicular_wall_uses_gap(tmp_path: Path) -> None:
    """Разрыв ограничен перпендикулярной стеной (Т-примыкание): дверь по разрыву, не по блоку."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 200)
    synth.add_rect(msp, synth.MONOLITH, 2900, -1500, 3100, 1500)
    synth.add_rect(msp, synth.MASONRY, 3100, 0, 5000, 200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_T", 1900, -500, 2800, 500)
    out = synth.run(tmp_path, doc)
    (op,) = [o for o in cast(list[Obj], out["openings"]) if o["kind"] == "door"]
    assert (op["status"], op["width_source"]) == ("ok", "gap")
    assert _f(op["width_mm"]) == pytest.approx(900, abs=2)
    lintel = _poly(op["lintel"])
    assert lintel.area == pytest.approx(900 * 200, rel=0.01)
    assert lintel.intersection(_cons_union(out)).area < 1.0
    assert op["leaf"] is not None


def test_door_on_solid_wall_has_no_gap_lintel_or_leaf(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 5000, 200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_S", 2000, -400, 2900, 600)
    out = synth.run(tmp_path, doc)
    (op,) = cast(list[Obj], out["openings"])
    assert (op["kind"], op["status"]) == ("door", "no_data")
    assert op["lintel"] is None and op["leaf"] is None
    checks = cast(Obj, out["checks"])
    codes = [w["code"] for w in cast(list[dict[str, str]], checks["warnings"])]
    assert codes.count("door_without_gap") == 1


def test_door_finds_nearest_free_gap_along_axis(tmp_path: Path) -> None:
    """Блок двери стоит на сплошной стене рядом с настоящим разрывом: перемычка — над разрывом."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 200)
    synth.add_rect(msp, synth.MONOLITH, 2900, -1500, 3100, 1500)
    synth.add_rect(msp, synth.MASONRY, 3100, 0, 6000, 200)
    # центр блока (2900) лежит на торце монолита, оба конца разрыва 2000..2900 — у bbox блока
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_N", 2300, -400, 3500, 600)
    out = synth.run(tmp_path, doc)
    (op,) = [o for o in cast(list[Obj], out["openings"]) if o["kind"] == "door"]
    assert (op["status"], op["width_source"]) == ("ok", "gap")
    assert _f(op["width_mm"]) == pytest.approx(900, abs=2)
    lintel = _poly(op["lintel"])
    assert lintel.centroid.x == pytest.approx(2450, abs=2)
    assert lintel.intersection(_cons_union(out)).area < 1.0


def test_lintel_covers_both_faces_with_offset_faces(tmp_path: Path) -> None:
    """Правая стена толще и выступает за грань левой: перемычка закрывает обе грани."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 2900, -20, 5000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_O", 2000, -400, 2900, 500)
    out = synth.run(tmp_path, doc)
    (op,) = cast(list[Obj], out["openings"])
    assert op["status"] == "ok"
    x0, y0, x1, y1 = _poly(op["lintel"]).bounds
    assert (x0, x1) == pytest.approx((2000, 2900), abs=1)
    assert (y0, y1) == pytest.approx((-20, 100), abs=1)


def test_leaf_is_thin_rect_along_gap_axis(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 2900, 0, 5000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_L", 2000, -400, 2900, 500)
    out = synth.run(tmp_path, doc)
    (op,) = cast(list[Obj], out["openings"])
    leaf = _poly(op["leaf"])
    assert leaf.exterior.is_ccw
    x0, y0, x1, y1 = leaf.bounds
    assert (x0, x1) == pytest.approx((2000, 2900), abs=1)
    assert (y0, y1) == pytest.approx((30, 70), abs=0.2)


def test_gap_opening_has_lintel_but_no_leaf(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 3500, 0, 5500, 100)
    out = synth.run(tmp_path, doc)
    (op,) = cast(list[Obj], out["openings"])
    assert op["kind"] == "gap"
    assert op["lintel"] is not None
    assert op["leaf"] is None


def test_end_of_returns_none_when_axis_misses_polygon() -> None:
    """Ось не пересекает полигон участка: пересечение — пустая линия, торца нет (не ошибка)."""
    import numpy as np
    from shapely.geometry import box

    from cad_walls.openings import _end_of

    axis = np.array([[0.0, 0.0], [1000.0, 0.0]])
    assert _end_of(axis, False, 100.0, box(5000, 5000, 6000, 6000)) is None
