"""Перемычка v1.6: прямоугольник по соосным сторонам, выбор разрыва двери, материал перемычки."""

from __future__ import annotations

import math
from pathlib import Path
from typing import cast

import pytest
from shapely.geometry import Polygon

from cad_walls.openings import lintel_material
from tests import synth

Obj = dict[str, object]
Pt = list[float]


def _f(value: object) -> float:
    assert isinstance(value, int | float)
    return float(value)


def _poly(ring: object) -> Polygon:
    return Polygon([(_f(p[0]), _f(p[1])) for p in cast(list[Pt], ring)])


def _door(out: Obj) -> Obj:
    (op,) = [o for o in cast(list[Obj], out["openings"]) if o["kind"] == "door"]
    return op


def _assert_rect_along(op: Obj) -> None:
    pts = [(_f(p[0]), _f(p[1])) for p in cast(list[Pt], op["lintel"])]
    assert len(pts) == 4
    dx, dy = (_f(v) for v in cast(Pt, op["direction"]))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True):
        length = math.hypot(x1 - x0, y1 - y0)
        cos_d = abs((x1 - x0) * dx + (y1 - y0) * dy) / length
        cos_n = abs((x1 - x0) * -dy + (y1 - y0) * dx) / length
        assert max(cos_d, cos_n) == pytest.approx(1.0, abs=1e-6)
    rect = Polygon(pts)
    assert rect.area == pytest.approx(rect.minimum_rotated_rectangle.area, rel=1e-6)
    assert rect.exterior.is_ccw


def test_stub_wall_across_opening_does_not_widen_lintel(tmp_path: Path) -> None:
    """Сверху проём ограничен тонким обрезком поперёк оси: глубина — по соосной стене (250)."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 250, 2000)
    synth.add_rect(msp, synth.MASONRY, -1000, 3080, 1250, 3130)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_STUB", -400, 2000, 650, 3080)
    op = _door(synth.run(tmp_path, doc))
    assert (op["status"], op["width_source"]) == ("ok", "gap")
    assert _f(op["width_mm"]) == pytest.approx(1080, abs=2)
    _assert_rect_along(op)
    x0, y0, x1, y1 = _poly(op["lintel"]).bounds
    assert (x0, x1) == pytest.approx((0, 250), abs=1)
    assert (y0, y1) == pytest.approx((2000, 3080), abs=1)
    leaf = _poly(op["leaf"]).bounds
    assert (leaf[0] + leaf[2]) / 2 == pytest.approx(125, abs=1)


def test_lintel_is_rectangle_for_offset_coaxial_faces(tmp_path: Path) -> None:
    """Обе стороны соосны, грани смещены: полоса — объединение сечений, стороны параллельны оси."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_rect(msp, synth.MASONRY, 2900, -20, 5000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_R", 2000, -400, 2900, 500)
    op = _door(synth.run(tmp_path, doc))
    _assert_rect_along(op)
    x0, y0, x1, y1 = _poly(op["lintel"]).bounds
    assert (x0, y0, x1, y1) == pytest.approx((2000, -20, 2900, 100), abs=1)


def test_gap_wider_than_door_is_not_taken(tmp_path: Path) -> None:
    """Разрыв 2000 при блоке 900x900: шире двери и её допуска — дверь без разрыва."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 200)
    synth.add_rect(msp, synth.MASONRY, 4000, 0, 6000, 200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_WIDE", 2550, -300, 3450, 600)
    op = _door(synth.run(tmp_path, doc))
    assert (op["status"], op["width_source"]) == ("no_data", "block_bbox")
    assert op["lintel"] is None
    assert op["lintel_material"] is None


def test_gap_far_from_door_bbox_is_not_taken(tmp_path: Path) -> None:
    """Разрыв подходящей ширины, но его концы далеко от bbox блока: не дверь."""
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 200)
    synth.add_rect(msp, synth.MASONRY, 2900, 0, 5000, 200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_FAR", 4000, -300, 4900, 600)
    op = _door(synth.run(tmp_path, doc))
    assert op["status"] == "no_data"


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (synth.MONOLITH, synth.MONOLITH, "monolith"),
        (synth.MASONRY, synth.MONOLITH, "masonry"),
        (synth.MONOLITH, synth.MASONRY, "masonry"),
        (synth.MASONRY, synth.MASONRY, "masonry"),
    ],
)
def test_lintel_material_by_adjacent_walls(
    tmp_path: Path, left: str, right: str, expected: str
) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, left, 0, 0, 2000, 200)
    synth.add_rect(msp, right, 2900, 0, 5000, 200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_M", 2000, -400, 2900, 600)
    op = _door(synth.run(tmp_path, doc))
    assert op["lintel"] is not None
    assert op["lintel_material"] == expected


def test_lintel_material_without_lintel_is_null(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 5000, 200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_S", 2000, -400, 2900, 600)
    op = _door(synth.run(tmp_path, doc))
    assert op["lintel"] is None and op["lintel_material"] is None


def test_lintel_material_function_rules() -> None:
    kinds = {"a": "monolith_wall", "b": "monolith_pylon", "c": "frame_partition", "d": "masonry"}
    assert lintel_material(["a", "b"], kinds) == "monolith"
    assert lintel_material(["a", "c"], kinds) == "frame_partition"
    assert lintel_material(["c", "d"], kinds) == "frame_partition"
    assert lintel_material(["d", "a"], kinds) == "masonry"
    assert lintel_material(["x"], kinds) is None
    assert lintel_material([], kinds) is None
