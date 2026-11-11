"""Данные 3D-вида: контур плиты, отверстия-кандидаты, перемычки проёмов (ADR-0039)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import cast

import pytest
from ezdxf.layouts.layout import Modelspace
from shapely.geometry import Polygon

from cad_walls.pipeline import Args, build
from tests import synth

Doc = dict[str, object]
Obj = dict[str, object]
Pt = list[float]

T = 200.0  # толщина стен синтетического этажа


def _f(value: object) -> float:
    assert isinstance(value, int | float)
    return float(value)


def _poly(ring: object) -> Polygon:
    return Polygon([(_f(p[0]), _f(p[1])) for p in cast(list[Pt], ring)])


def _outer_walls(msp: Modelspace, gap: tuple[float, float] | None = None) -> None:
    """Прямоугольный этаж 10 x 8 м; в южной стене по желанию разрыв `gap` (x0, x1)."""
    add = synth.add_rect
    layer = synth.MASONRY
    add(msp, layer, 0, 8000 - T, 10000, 8000)  # север
    add(msp, layer, 0, 0, T, 8000)  # запад
    add(msp, layer, 10000 - T, 0, 10000, 8000)  # восток
    if gap is None:
        add(msp, layer, 0, 0, 10000, T)
    else:
        add(msp, layer, 0, 0, gap[0], T)
        add(msp, layer, gap[1], 0, 10000, T)


def _slab(doc: Doc) -> Obj:
    slab = doc["slab"]
    assert isinstance(slab, dict)
    return cast(Obj, slab)


def _holes(doc: Doc) -> list[Obj]:
    return cast(list[Obj], doc["slab_holes"])


def test_slab_closes_facade_gap(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    _outer_walls(msp, gap=(4000, 5200))  # разрыв 1200 мм
    out = synth.run(tmp_path, doc)
    slab = _slab(out)
    shell = _poly(slab["shell"])
    assert shell.is_valid
    assert _f(slab["area_mm2"]) == pytest.approx(10000 * 8000, rel=1e-3)
    assert _f(slab["close_radius_mm"]) == 1500
    assert shell.area == pytest.approx(_f(slab["area_mm2"]), abs=1.0)
    assert _holes(out) == []


def test_slab_has_no_inner_rings_and_is_ccw(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    _outer_walls(msp)
    out = synth.run(tmp_path, doc)
    shell = _poly(_slab(out)["shell"])
    assert shell.exterior.is_ccw
    assert not list(shell.interiors)


def test_enclosed_shaft_is_one_hole(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    _outer_walls(msp)
    # шахта 1 x 1 м в свету, стены 200 мм, замкнутая без двери
    synth.add_poly(
        msp,
        synth.MONOLITH,
        Polygon(
            [(4000, 3000), (5400, 3000), (5400, 4400), (4000, 4400)],
            [[(4200, 3200), (5200, 3200), (5200, 4200), (4200, 4200)]],
        ),
    )
    out = synth.run(tmp_path, doc)
    (hole,) = _holes(out)
    assert hole["id"] == "h1"
    assert hole["status"] == "candidate"
    assert hole["reason"] == "enclosed_no_door"
    assert _f(hole["area_mm2"]) == pytest.approx(1_000_000, rel=1e-3)
    assert _poly(hole["shell"]).within(_poly(_slab(out)["shell"]))
    # внешний контур плиты не получает отверстий
    assert not list(_poly(_slab(out)["shell"]).interiors)


def test_room_with_door_is_not_hole(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    _outer_walls(msp)
    # комната 1 x 1 м в свету: южная стена комнаты прервана дверью 800 мм
    layer = synth.MASONRY
    synth.add_rect(msp, layer, 4000, 3000, 4200, 4400)
    synth.add_rect(msp, layer, 5200, 3000, 5400, 4400)
    synth.add_rect(msp, layer, 4200, 4200, 5200, 4400)
    synth.add_rect(msp, layer, 4200, 3000, 4500, 3200)
    synth.add_rect(msp, layer, 5000, 3000, 5200, 3200)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_020", 4500, 2800, 5000, 3400)
    out = synth.run(tmp_path, doc)
    assert _holes(out) == []


def test_no_walls_gives_null_slab_and_warning(tmp_path: Path) -> None:
    doc, _ = synth.new_doc()
    out = synth.run(tmp_path, doc)
    assert out["slab"] is None
    assert out["slab_holes"] == []
    checks = cast(Obj, out["checks"])
    codes = [w["code"] for w in cast(list[Obj], checks["warnings"])]
    assert "slab_missing" in codes


def _door_doc(tmp_path: Path, *, vertical: bool) -> Obj:
    doc, msp = synth.new_doc()
    if vertical:
        synth.add_rect(msp, synth.MASONRY, 0, 0, 100, 2000)
        synth.add_rect(msp, synth.MASONRY, 0, 2900, 100, 5000)
        synth.add_door(doc, msp, "AR_DOOR_BLOCK_030", -400, 2000, 500, 2900)
    else:
        synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
        synth.add_rect(msp, synth.MASONRY, 2900, 0, 5000, 100)
        synth.add_door(doc, msp, "AR_DOOR_BLOCK_030", 2000, -400, 2900, 500)
    out = synth.run(tmp_path, doc)
    (op,) = cast(list[Obj], out["openings"])
    return op


@pytest.mark.parametrize("vertical", [False, True])
def test_lintel_matches_width_and_thickness(tmp_path: Path, vertical: bool) -> None:
    op = _door_doc(tmp_path, vertical=vertical)
    dx, dy = (_f(v) for v in cast(Pt, op["direction"]))
    assert math.hypot(dx, dy) == pytest.approx(1.0, abs=1e-5)
    assert dx > 0 or (dx == 0 and dy > 0)
    expected = (0.0, 1.0) if vertical else (1.0, 0.0)
    assert (dx, dy) == pytest.approx(expected, abs=1e-5)
    pts = [(_f(p[0]), _f(p[1])) for p in cast(list[Pt], op["lintel"])]
    assert len(pts) == 4
    width, thick = _f(op["width_mm"]), _f(op["thickness_mm"])
    along = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    across = math.hypot(pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
    assert along == pytest.approx(width, abs=0.2)
    assert across == pytest.approx(thick, abs=0.2)
    cx, cy = (_f(v) for v in cast(Pt, op["center"]))
    assert sum(p[0] for p in pts) / 4 == pytest.approx(cx, abs=0.2)
    assert sum(p[1] for p in pts) / 4 == pytest.approx(cy, abs=0.2)
    assert Polygon(pts).exterior.is_ccw


def test_lintel_null_without_thickness(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    synth.add_rect(msp, synth.MASONRY, 0, 0, 2000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_031", 9000, 9000, 9900, 9900)  # вдали от стен
    out = synth.run(tmp_path, doc)
    (op,) = cast(list[Obj], out["openings"])
    assert op["thickness_mm"] is None
    assert op["lintel"] is None


def test_slab_output_is_deterministic(tmp_path: Path) -> None:
    doc, msp = synth.new_doc()
    _outer_walls(msp, gap=(4000, 5200))
    synth.add_poly(
        msp,
        synth.MONOLITH,
        Polygon(
            [(6000, 3000), (7400, 3000), (7400, 4400), (6000, 4400)],
            [[(6200, 3200), (7200, 3200), (7200, 4200), (6200, 4200)]],
        ),
    )
    path = tmp_path / "plan.dxf"
    doc.saveas(str(path))
    texts = [
        json.dumps(build(Args(dxf=path, params=None, out=tmp_path / "w.json")).document)
        for _ in range(2)
    ]
    assert texts[0] == texts[1]
    assert '"slab_holes":[{"id":"h1"' in texts[0].replace(" ", "")
