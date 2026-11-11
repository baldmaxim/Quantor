"""Зоны помещений: необязательный вход контура плиты (`--zones`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from ezdxf.layouts.layout import Modelspace
from shapely.geometry import Point, Polygon

from cad_walls.cli import main
from cad_walls.pipeline import Args, build
from tests import synth

T = 200.0


def _walls_with_wide_gap(msp: Modelspace) -> None:
    """Этаж 10 x 8 м; в южной стене разрыв 5 м (лоджия), который замыкание 1,5 м не берёт."""
    add = synth.add_rect
    layer = synth.MASONRY
    add(msp, layer, 0, 8000 - T, 10000, 8000)
    add(msp, layer, 0, 0, T, 8000)
    add(msp, layer, 10000 - T, 0, 10000, 8000)
    add(msp, layer, 0, 0, 3000, T)
    add(msp, layer, 8000, 0, 10000, T)


def _zones_file(tmp_path: Path, items: list[dict[str, object]]) -> Path:
    path = tmp_path / "zones.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def _slab(doc: dict[str, object]) -> Polygon:
    slab = cast(dict[str, object], doc["slab"])
    return Polygon([(p[0], p[1]) for p in cast(list[list[float]], slab["shell"])])


def _build(tmp_path: Path, zones: Path | None) -> dict[str, object]:
    doc, msp = synth.new_doc()
    _walls_with_wide_gap(msp)
    path = tmp_path / "plan.dxf"
    doc.saveas(str(path))
    return build(Args(dxf=path, params=None, out=tmp_path / "w.json", zones=zones)).document


def test_zone_closes_loggia_that_closing_cannot(tmp_path: Path) -> None:
    probe = Point(5500, 1000)
    assert not _slab(_build(tmp_path, None)).contains(probe)
    room = [[200, 200], [9800, 200], [9800, 7800], [200, 7800]]
    loggia = [[3000, -1000], [8000, -1000], [8000, 200], [3000, 200]]
    zones = _zones_file(
        tmp_path,
        [
            {"kind": "room_apartment", "shell": room},
            {"kind": "room_mop", "shell": loggia},
        ],
    )
    slab = _slab(_build(tmp_path, zones))
    assert slab.contains(probe)
    assert slab.is_valid


def test_door_zones_are_ignored(tmp_path: Path) -> None:
    room = [[200, 200], [9800, 200], [9800, 7800], [200, 7800]]
    zones = _zones_file(tmp_path, [{"kind": "door", "shell": room}])
    assert not _slab(_build(tmp_path, zones)).contains(Point(5500, 1000))


def test_zones_without_input_keep_previous_slab(tmp_path: Path) -> None:
    a = _slab(_build(tmp_path, None))
    b = _slab(_build(tmp_path, _zones_file(tmp_path, [])))
    assert a.equals(b)


def test_cli_rejects_broken_zones(tmp_path: Path, capsys: object) -> None:
    doc, msp = synth.new_doc()
    _walls_with_wide_gap(msp)
    dxf = tmp_path / "plan.dxf"
    doc.saveas(str(dxf))
    zones = _zones_file(tmp_path, [{"kind": "room_mop", "shell": [[0, 0], [1, 1]]}])
    code = main(["--dxf", str(dxf), "--out", str(tmp_path / "w.json"), "--zones", str(zones)])
    assert code == 2
