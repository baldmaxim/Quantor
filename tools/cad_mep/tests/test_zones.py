"""Тесты разметки зон помещений на синтетическом этаже: открытая планировка и дуга фасада."""

from __future__ import annotations

import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from cad_mep import zones_const as zc
from cad_mep.raster import BoolArr, IntArr
from cad_mep.zones import SCHEMA, ZoneArgs, extract_zones
from cad_mep.zones_grow import absorb_residual
from cad_mep.zones_raster import Field
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
    assert sorted(zones) == MARKS  # по одной зоне на марку; на этаже нет марок МОП
    for z in zones.values():
        assert z["kind"] == "room_apartment"
        assert z["apartment_no"] == "1011"
        assert isinstance(z["notes"], list)
    assert result["summary_mop"] == {
        "zones": 0,
        "poly_area_m2": 0.0,
        "expl_area_m2": 0.0,
        "delta_pct": None,
    }
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


# --- помещения МОП: марка с точкой -> зона room_mop ---------------------------------------------
def _run(floor: synth.Floor, folder: Path) -> dict[str, object]:
    files = synth.write_inputs(floor, folder)
    args = ZoneArgs(
        files["pdf"], 0, files["dxf"], files["scale"], files["preview"], None, folder / "z.json"
    )
    return extract_zones(args)


@pytest.fixture(scope="module")
def mop_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    floor, _ = synth.build_zones_floor(mop=True)
    return _run(floor, tmp_path_factory.mktemp("zones_mop"))


def test_mop_mark_becomes_room_mop_zone(mop_result: dict[str, object]) -> None:
    zones = _zones(mop_result)
    assert sorted(zones) == sorted([*MARKS, synth.MOP_MARK])
    mop = zones[synth.MOP_MARK]
    assert mop["kind"] == "room_mop"
    assert mop["apartment_no"] is None
    assert mop["name"] == synth.MOP_NAME  # дословно из экспликации
    ideal = (11700.0 - 300.0) * (synth.MOP_Y1 - 8000.0) / 1e6
    assert float(str(mop["poly_area_m2"])) == pytest.approx(ideal, rel=AREA_TOL)
    assert float(str(mop["expl_area_m2"])) == pytest.approx(ideal, abs=0.01)
    assert _to_building(mop["points"]).area / 1e6 == pytest.approx(ideal, rel=AREA_TOL)
    assert isinstance(mop["notes"], list)
    assert mop_result["unmatched_marks"] == []


def test_mop_summary_is_separate_from_apartments(mop_result: dict[str, object]) -> None:
    summary = mop_result["summary"]
    assert isinstance(summary, list)
    assert [s["apartment_no"] for s in summary] == ["1011"]  # МОП в квартирную сводку не входит
    assert summary[0]["zones"] == 3
    mop_summary = mop_result["summary_mop"]
    assert isinstance(mop_summary, dict)
    assert mop_summary["zones"] == 1
    zone_area = float(str(_zones(mop_result)[synth.MOP_MARK]["poly_area_m2"]))
    assert float(str(mop_summary["poly_area_m2"])) == pytest.approx(zone_area, abs=0.01)


def test_mop_does_not_change_apartment_zones(
    result: dict[str, object], mop_result: dict[str, object]
) -> None:
    before, after = _zones(result), _zones(mop_result)
    for mark in MARKS:
        assert after[mark]["kind"] == "room_apartment"
        assert after[mark]["points"] == before[mark]["points"], mark
        assert after[mark]["poly_area_m2"] == before[mark]["poly_area_m2"], mark
        assert after[mark]["apartment_no"] == before[mark]["apartment_no"], mark
    mop = _to_building(after[synth.MOP_MARK]["points"])
    for mark in MARKS:
        assert mop.intersection(_to_building(after[mark]["points"])).area / 1e6 <= zc.OVERLAP_MIN_M2


def test_mop_mark_missing_from_explication_is_unmatched(tmp_path: Path) -> None:
    floor, _ = synth.build_zones_floor(mop=True)
    floor.expl = [e for e in floor.expl if e[0] != synth.MOP_MARK]
    data = _run(floor, tmp_path)
    assert sorted(_zones(data)) == MARKS
    assert data["unmatched_marks"] == [
        {
            "room_mark": synth.MOP_MARK,
            "name": None,
            "expl_area_m2": None,
            "reason": "нет в экспликации",
        }
    ]


def test_mop_mark_absent_on_plan_is_unmatched(tmp_path: Path) -> None:
    floor, _ = synth.build_zones_floor(mop=True)
    synth.drop_labels(floor, {synth.MOP_MARK})
    data = _run(floor, tmp_path)
    assert sorted(_zones(data)) == MARKS
    unmatched = data["unmatched_marks"]
    assert isinstance(unmatched, list) and len(unmatched) == 1
    um = unmatched[0]
    assert um["room_mark"] == synth.MOP_MARK
    assert um["name"] == synth.MOP_NAME
    assert um["reason"] == "полигон не построен"


# --- добор до заливок: карманы за тонкими штрихами ---------------------------------------------
STEP_MM = 5.0
COLUMN = (300.0, 1000.0, 700.0, 1400.0)  # колонна 400 x 400 у западной стены спальни (заливка)
OUTLINE = (700.0, 1000.0, 860.0, 1400.0)  # рядом обводка 160 x 400 без заливки: пол помещения


def _bedroom_area(tmp_path: Path, outline: bool) -> tuple[float, Polygon, list[object]]:
    floor, _ = synth.build_zones_floor()
    floor.walls.append(COLUMN)
    if outline:
        floor.outlines.append(OUTLINE)
    files = synth.write_inputs(floor, tmp_path)
    out = tmp_path / "zones.json"
    args = ZoneArgs(files["pdf"], 0, files["dxf"], files["scale"], files["preview"], None, out)
    zone = _zones(extract_zones(args))["1-1/1"]
    notes = zone["notes"]
    assert isinstance(notes, list)
    return float(str(zone["poly_area_m2"])), _to_building(zone["points"]), notes


def test_outline_next_to_column_joins_zone(tmp_path: Path) -> None:
    base, _, base_notes = _bedroom_area(tmp_path / "plain", outline=False)
    area, poly, notes = _bedroom_area(tmp_path / "outline", outline=True)
    centre = Point((OUTLINE[0] + OUTLINE[2]) / 2, (OUTLINE[1] + OUTLINE[3]) / 2)
    assert poly.contains(centre)  # без добора обводка осталась бы вырезом зоны
    assert area == pytest.approx(base, abs=0.02)
    assert not any("дорощено" in str(n) for n in base_notes)
    assert any(str(n).startswith("дорощено до заливок: 1 карманов") for n in notes)


def _field(
    height: int = 30,
    width: int = 30,
    west: str = "soft",
    soft_cells: int = 1,
    east: str = "fill",
    east_cells: int = 1,
    outside: bool = False,
) -> tuple[Field, BoolArr]:
    """Зона 1 слева, карман height x width клеток, барьеры по бокам; сверху и снизу — заливки.

    west/east — барьер слева и справа: «soft» (тонкий штрих), «fill» (заливка), «zone» (зона 2
    за штрихом); east_cells — толщина восточного барьера. outside — за восточным барьером
    свободная область выходит на край растра (улица). Клетка тонкого растра — STEP_MM.
    """
    ny, nx = height + 4, 60 + soft_cells + width + east_cells + 40
    obst: BoolArr = np.zeros((ny, nx), dtype=np.bool_)
    fill: BoolArr = np.zeros((ny, nx), dtype=np.bool_)
    g: IntArr = np.full((ny + 2, nx + 2), -1, dtype=np.int32)
    inner = g[1:-1, 1:-1]
    inner[:] = 0
    wx0 = 60  # первая клетка западного барьера
    px0 = wx0 + soft_cells  # первая клетка кармана
    ex0 = px0 + width  # первая клетка восточного барьера
    inner[:, :wx0] = 1
    fill[:2, wx0:] = True
    fill[-2:, wx0:] = True
    if not outside:
        fill[:, -1] = True
    for kind, c0, cells in ((west, wx0, soft_cells), (east, ex0, east_cells)):
        if kind == "fill":
            fill[:, c0 : c0 + cells] = True
        else:
            obst[2:-2, c0 : c0 + cells] = True
    if east == "zone":
        inner[:, ex0 + east_cells : -1] = 2
    obst |= fill
    inner[obst & (inner == 0)] = -1
    return Field(STEP_MM, 1, nx, ny, obst, fill, g), fill


def test_residual_pocket_joins_zone_with_soft_cells_only() -> None:
    fld, fill = _field()
    gi = fld.gi
    before_fill = gi[fill].copy()
    added = absorb_residual(fld)
    assert len(added) == 1
    assert added[0].zone == 1
    assert added[0].area_m2 == pytest.approx((30 * 30 + 30) * STEP_MM**2 / 1e6)
    assert (gi[2:-2, 60:91] == 1).all()  # карман и штрих между ним и зоной
    assert (gi[fill] == before_fill).all()  # заливки не тронуты
    assert absorb_residual(fld) == []  # повторный вызов ничего не меняет


def test_residual_closed_pocket_behind_fill_stays() -> None:
    fld, _ = _field(west="fill")
    snapshot = fld.g.copy()
    assert absorb_residual(fld) == []
    assert (fld.g == snapshot).all()


def test_residual_big_pocket_stays() -> None:
    height, width = 120, 210  # 25200 клеток = 0,63 м² > RESIDUAL_MAX_M2
    assert height * width * STEP_MM**2 / 1e6 > zc.RESIDUAL_MAX_M2
    fld, _ = _field(height=height, width=width)
    assert absorb_residual(fld) == []
    assert (fld.gi[2:-2, 61 : 61 + width] == 0).all()


def test_residual_short_contact_or_thick_stroke_stays() -> None:
    short, _ = _field(height=int(zc.RESIDUAL_CONTACT_MIN_MM / STEP_MM) - 5)
    assert absorb_residual(short) == []
    thick, _ = _field(soft_cells=zc.RESIDUAL_SOFT_CELLS + 1)
    assert absorb_residual(thick) == []


def test_residual_tie_goes_to_smaller_zone_id() -> None:
    fld, _ = _field(east="zone")
    added = absorb_residual(fld)
    assert [a.zone for a in added] == [1]
    assert (fld.gi[2:-2, 60:91] == 1).all()
    assert (fld.gi[2:-2, 91:92] == -1).all()  # штрих у зоны 2 не отдан


def test_residual_window_niche_near_exterior_stays() -> None:
    # оконный проём: за нишей только тонкий штрих и улица (свободная область у края растра)
    window, _ = _field(east="soft", outside=True)
    assert absorb_residual(window) == []
    assert (window.gi[2:-2, 61:91] == 0).all()
    # колонна у фасада: стена толще RESIDUAL_EXTERIOR_MM отделяет карман от улицы
    thick = int(zc.RESIDUAL_EXTERIOR_MM / STEP_MM) + 10
    column, _ = _field(east="fill", east_cells=thick, outside=True)
    assert [a.zone for a in absorb_residual(column)] == [1]
