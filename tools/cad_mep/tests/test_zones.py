"""Тесты разметки зон помещений на синтетическом этаже: открытая планировка и дуга фасада."""

from __future__ import annotations

import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from cad_mep import zones_const as zc
from cad_mep.zones import SCHEMA, ZoneArgs, extract_zones
from tests import synth

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run_zones.py"
PAGE_W, PAGE_H = 900.0, 500.0  # размер страницы синтетического PDF, пт
AREA_TOL = 0.03  # допуск площади зоны к идеальной области по граням стен
MARKS = ["1-1/1", "1-1/2", "1-1/3"]


@pytest.fixture(scope="module")
def inputs(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Path], synth.ZoneTruth]:
    floor, truth = synth.build_zones_floor()
    folder = tmp_path_factory.mktemp("zones_in")
    return synth.write_inputs(floor, folder), truth


@pytest.fixture(scope="module")
def result(
    inputs: tuple[dict[str, Path], synth.ZoneTruth], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, object]:
    files, _ = inputs
    out = tmp_path_factory.mktemp("zones_out") / "zones.json"
    args = ZoneArgs(files["pdf"], 0, files["dxf"], files["scale"], files["preview"], None, out)
    return extract_zones(args)


def _zones(result: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = result["zones"]
    assert isinstance(raw, list)
    return {str(z["room_mark"]): z for z in raw}


def _to_building(points: object) -> Polygon:
    """Нормализованные вершины -> мм здания (обратно к synth._pt)."""
    assert isinstance(points, list)
    ring = []
    for nx, ny in points:
        px, py = nx * PAGE_W, ny * PAGE_H
        ring.append(
            (
                (px - synth.OX_PT) * synth.SCALE - synth.SHIFT[0],
                (synth.OY_PT - py) * synth.SCALE - synth.SHIFT[1],
            )
        )
    return Polygon(ring)


def test_schema_and_marks(result: dict[str, object]) -> None:
    assert result["schema"] == SCHEMA
    assert result["page_index"] == 0
    assert result["scale_mm_per_pt"] == synth.SCALE
    assert result["unmatched_marks"] == []
    zones = _zones(result)
    assert sorted(zones) == MARKS  # по одной зоне на марку, МОП не размечается
    for z in zones.values():
        assert z["kind"] == "room_apartment"
        assert z["apartment_no"] == "1011"
        assert isinstance(z["notes"], list)
    summary = result["summary"]
    assert isinstance(summary, list)
    assert [s["apartment_no"] for s in summary] == ["1011"]
    assert summary[0]["zones"] == 3


def test_polygons_valid_single_ring(result: dict[str, object]) -> None:
    for z in _zones(result).values():
        points = z["points"]
        assert isinstance(points, list)
        assert 3 <= len(points) <= zc.MAX_POINTS
        assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in points)
        assert all(round(v, 6) == v for pt in points for v in pt)
        poly = Polygon([(x * PAGE_W, y * PAGE_H) for x, y in points])
        assert poly.is_valid
        assert len(poly.interiors) == 0


def test_no_overlaps(result: dict[str, object]) -> None:
    polys = {m: _to_building(z["points"]) for m, z in _zones(result).items()}
    for (ma, a), (mb, b) in combinations(polys.items(), 2):
        overlap = a.intersection(b).area / 1e6
        assert overlap <= zc.OVERLAP_MIN_M2, (ma, mb, overlap)


def test_areas_match_walls_and_explication(
    result: dict[str, object], inputs: tuple[dict[str, Path], synth.ZoneTruth]
) -> None:
    _, truth = inputs
    for mark, z in _zones(result).items():
        ideal = truth.shapes[mark].area / 1e6
        area = float(str(z["poly_area_m2"]))
        assert area == pytest.approx(ideal, rel=AREA_TOL), mark
        assert float(str(z["expl_area_m2"])) == pytest.approx(ideal, abs=0.01)
        # площадь в JSON и по вершинам совпадают
        assert _to_building(z["points"]).area / 1e6 == pytest.approx(area, rel=0.005)


def test_open_plan_pair_split_by_thin_line(
    result: dict[str, object], inputs: tuple[dict[str, Path], synth.ZoneTruth]
) -> None:
    _, truth = inputs
    zones = _zones(result)
    kitchen, hall = _to_building(zones["1-1/3"]["points"]), _to_building(zones["1-1/2"]["points"])
    # граница пары — линия плана y = SPLIT_Y: кухня южнее, прихожая севернее
    assert kitchen.bounds[3] == pytest.approx(synth.SPLIT_Y, abs=30.0)
    assert hall.bounds[1] == pytest.approx(synth.SPLIT_Y, abs=30.0)
    for mark in ("1-1/2", "1-1/3"):
        poly = _to_building(zones[mark]["points"])
        iou = poly.intersection(truth.shapes[mark]).area / poly.union(truth.shapes[mark]).area
        assert iou > 0.95, mark


def test_curved_corner_follows_arc(result: dict[str, object]) -> None:
    kitchen = _to_building(_zones(result)["1-1/3"]["points"])
    cx, cy = synth.ARC_CENTER
    centre = Point(cx, cy)
    on_arc = [
        p
        for p in kitchen.exterior.coords
        if abs(Point(p).distance(centre) - synth.ARC_R_IN) < 40.0 and p[0] > cx and p[1] < cy
    ]
    assert len(on_arc) >= 6  # дуга передана вершинами, а не срезана хордой
    assert all(p[0] <= 11700.0 + 30.0 for p in kitchen.exterior.coords)


def test_cli_writes_json(inputs: tuple[dict[str, Path], synth.ZoneTruth], tmp_path: Path) -> None:
    files, _ = inputs
    out = tmp_path / "zones.json"
    cmd = [
        sys.executable,
        "-I",
        str(RUN),
        "--pdf",
        str(files["pdf"]),
        "--page-index",
        "0",
        "--view-dxf",
        str(files["dxf"]),
        "--scale",
        str(files["scale"]),
        "--preview",
        str(files["preview"]),
        "--out",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["ok"] is True
    assert summary["zones"] == 3
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA


def test_cli_json_error(inputs: tuple[dict[str, Path], synth.ZoneTruth], tmp_path: Path) -> None:
    files, _ = inputs
    cmd = [sys.executable, "-I", str(RUN), "--pdf", str(files["pdf"] / "нет.pdf")]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
    assert proc.returncode == 2
    assert json.loads(proc.stderr.strip().splitlines()[-1])["code"] == "bad_arguments"
    bad = [
        sys.executable,
        "-I",
        str(RUN),
        "--pdf",
        str(tmp_path / "нет.pdf"),
        "--page-index",
        "0",
        "--view-dxf",
        str(files["dxf"]),
        "--scale",
        str(files["scale"]),
        "--preview",
        str(files["preview"]),
        "--out",
        str(tmp_path / "z.json"),
    ]
    proc = subprocess.run(bad, capture_output=True, text=True, check=False, timeout=60)
    assert proc.returncode == 2
    assert json.loads(proc.stderr)["code"] == "pdf_unreadable"
