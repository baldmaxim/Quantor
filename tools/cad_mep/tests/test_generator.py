"""Тесты генератора трасс на синтетическом этаже (tests/synth.py)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from ezdxf.entities.polyline import Polyline
from ezdxf.filemanagement import readfile
from shapely.geometry import LineString
from shapely.ops import unary_union

from cad_mep import GENERATOR_VERSION
from cad_mep.params import canonical_sha256, load_params
from tests import synth

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "run_mep.py"
FOLDER = "p001_v01"
ELEVATION, HEIGHT = 47600, 3300
ROUTE_LAYERS = [
    "M-OV-T1",
    "M-OV-T2",
    "M-PT-VPV",
    "M-PT-AUP",
    "M-VK-V1",
    "M-VK-T3",
    "M-VK-T4",
    "M-VK-K1",
]

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    inputs: dict[str, Path],
    out: Path,
    *,
    page_index: int = 0,
    elevation: int = ELEVATION,
    height: int = HEIGHT,
    scale: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-I",
        str(RUN),
        "--pdf",
        str(inputs["pdf"]),
        "--page-index",
        str(page_index),
        "--view-dxf",
        str(inputs["dxf"]),
        "--scale",
        str(scale or inputs["scale"]),
        "--preview",
        str(inputs["preview"]),
        "--out",
        str(out),
        "--view-folder",
        FOLDER,
        "--floor-elevation-mm",
        str(elevation),
        "--floor-height-mm",
        str(height),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)


@pytest.fixture(scope="module")
def floor() -> synth.Floor:
    return synth.build_floor()


@pytest.fixture(scope="module")
def inputs(floor: synth.Floor, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return synth.write_inputs(floor, tmp_path_factory.mktemp("in"))


@pytest.fixture(scope="module")
def run_a(inputs: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("out_a")
    proc = _run(inputs, out)
    assert proc.returncode == 0, proc.stderr
    return out / "views" / FOLDER


@pytest.fixture(scope="module")
def candidate(run_a: Path) -> dict[str, object]:
    data = json.loads((run_a / "candidate.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_outputs_exist(run_a: Path) -> None:
    for name in ("mep_routes.dxf", "preview.json", "candidate.json"):
        assert (run_a / name).is_file(), name


def test_dxf_layers_and_audit(run_a: Path) -> None:
    doc = readfile(str(run_a / "mep_routes.dxf"))
    assert not doc.audit().errors
    names = {layer.dxf.name for layer in doc.layers}
    for required in [*ROUTE_LAYERS, "M-NODE", "M-RISER", "A-WALL"]:
        assert required in names, required
    polylines = [e for e in doc.modelspace() if isinstance(e, Polyline)]
    used = {e.dxf.layer for e in polylines}
    assert set(ROUTE_LAYERS) <= used
    # Z абсолютные: отопление в стяжке над отметкой пола
    heat_z = {round(p[2]) for e in polylines if e.dxf.layer == "M-OV-T1" for p in e.points()}
    assert ELEVATION + 50 in heat_z


def test_routes_do_not_cross_walls(run_a: Path, floor: synth.Floor) -> None:
    """Вне окрестности шахт (выход через их стену) трассы не заходят в стены."""
    walls = unary_union(synth.wall_union_polys(floor)).buffer(-30)
    shafts = unary_union(synth.shaft_inner_boxes(floor)).buffer(500)
    doc = readfile(str(run_a / "mep_routes.dxf"))
    checked = 0
    for e in (e for e in doc.modelspace() if isinstance(e, Polyline)):
        if e.dxf.layer not in ROUTE_LAYERS:
            continue
        pts = [(p[0], p[1]) for p in e.points()]
        if len(set(pts)) < 2:
            continue  # вертикальный стояк
        inside = LineString(pts).difference(shafts).intersection(walls)
        assert inside.length < 1.0, (e.dxf.layer, inside.wkt)
        checked += 1
    assert checked > 20


def test_every_apartment_has_entries(candidate: dict[str, object]) -> None:
    apts = candidate["apartments"]
    assert isinstance(apts, list) and len(apts) == 4
    for a in apts:
        assert a["entry_door"], a["number"]
        assert a["heat"]["shaft"], a["number"]
        assert a["water"]["shaft"], a["number"]
        assert a["lengths_own_lines"]["heating"]["plan_m"] > 0
        assert len(a["heat"]["devices"]) == 2  # спальня и кухня
    assert sorted(a["number"] for a in apts) == ["Кв 1011", "Кв 1012", "Кв 1013", "Кв 1014"]


def test_candidate_content(candidate: dict[str, object], inputs: dict[str, Path]) -> None:
    assert candidate["schema"] == "quantor.cad_mep.candidate.v1"
    prov = candidate["provenance"]
    assert isinstance(prov, dict)
    assert prov["generator_version"] == GENERATOR_VERSION == "cad_mep.v1"
    assert prov["pdf_sha256"] == _sha(inputs["pdf"])
    assert prov["view_dxf_sha256"] == _sha(inputs["dxf"])
    params = load_params(None)
    assert prov["params_sha256"] == params.sha256
    assert params.sha256 == canonical_sha256(json.loads((ROOT / "params" / "v1.json").read_text()))
    assert prov["approval_id"] is None
    elevation = candidate["elevation"]
    assert isinstance(elevation, dict)
    assert elevation["floor_elevation_mm"] == {"value": ELEVATION, "source": "operator"}
    assert elevation["floor_height_mm"] == {"value": HEIGHT, "source": "operator"}
    assert elevation["sheet_marks_mm"] == [ELEVATION]
    assert candidate["issues"] == []
    assert isinstance(candidate["assumptions"], list) and candidate["assumptions"]
    routes = candidate["routes"]
    assert isinstance(routes, dict)
    for system in ("heating", "fire", "water", "sewer"):
        assert routes["by_system"][system]["len3d_m"] > 0, system
    checks = candidate["checks"]
    assert isinstance(checks, dict)
    assert checks["tie_pdf_to_dxf"]["passed"]
    assert checks["no_wall_crossing"]["passed"]
    assert checks["apartments_count"]["passed"]
    assert checks["each_apt_has_heat_and_water"]["passed"]
    assert checks["dxf"]["audit_errors"] == 0
    # шахты: ОВ x2, ВК в МОП, ВК в квартире (канализация), ПК x2
    shafts = candidate["shafts"]
    assert isinstance(shafts, list)
    by_key = {(tuple(s["systems"]), s["place"]) for s in shafts}
    assert {(("ОВ",), "mop"), (("ВК",), "mop"), (("ВК",), "apartment"), (("ПК",), "mop")} <= by_key
    # помещения сверены с экспликацией
    rooms = candidate["rooms"]
    assert isinstance(rooms, list) and len(rooms) == 13
    assert all(r["comp"] is not None and abs(r["delta_pct"]) < 10 for r in rooms), rooms


def test_preview_same_frame(run_a: Path, inputs: dict[str, Path]) -> None:
    preview = json.loads((run_a / "preview.json").read_text(encoding="utf-8"))
    parent = json.loads(inputs["preview"].read_text(encoding="utf-8"))
    assert preview["schema"] == "quantor.cad_engine.preview.v1"
    assert preview["units"] == "mm"
    assert preview["bbox"] == parent["bbox"]
    assert preview["dxf_sha256"] == _sha(run_a / "mep_routes.dxf")
    x0, y0, x1, y1 = parent["bbox"]
    layers = preview["layers"]
    assert {"M-NODE", "M-RISER", "M-OV-T1"} <= set(layers)
    n_points = 0
    for path in preview["paths"]:
        pts = path["points"]
        assert len(pts) % 2 == 0
        assert layers[path["layer"]] in {*ROUTE_LAYERS, "M-NODE", "M-RISER"}
        if layers[path["layer"]] in ("M-NODE", "M-RISER"):
            assert path["closed"] is True
        for x, y in zip(pts[0::2], pts[1::2], strict=True):
            assert x0 <= x <= x1 and y0 <= y <= y1
        n_points += len(pts) // 2
    assert preview["points"] == n_points


def test_deterministic(
    inputs: dict[str, Path], run_a: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    out = tmp_path_factory.mktemp("out_b")
    proc = _run(inputs, out)
    assert proc.returncode == 0, proc.stderr
    b = out / "views" / FOLDER
    for name in ("mep_routes.dxf", "candidate.json", "preview.json"):
        assert _sha(run_a / name) == _sha(b / name), name


def test_elevation_mismatch_is_issue(
    inputs: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    out = tmp_path_factory.mktemp("out_elev")
    proc = _run(inputs, out, elevation=40000)
    assert proc.returncode == 0, proc.stderr
    data = json.loads((out / "views" / FOLDER / "candidate.json").read_text(encoding="utf-8"))
    assert [i["code"] for i in data["issues"]] == ["elevation_mismatch"]
    assert data["elevation"]["floor_elevation_mm"]["value"] == 40000


def _error(proc: subprocess.CompletedProcess[str]) -> dict[str, str]:
    line = proc.stderr.strip().splitlines()[-1]
    data = json.loads(line)
    assert set(data) == {"code", "message"}
    return {"code": str(data["code"]), "message": str(data["message"])}


def test_page_out_of_range(inputs: dict[str, Path], tmp_path: Path) -> None:
    proc = _run(inputs, tmp_path, page_index=5)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "page_out_of_range"


def test_height_out_of_range(inputs: dict[str, Path], tmp_path: Path) -> None:
    proc = _run(inputs, tmp_path, height=1500)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "height_invalid"


def test_frame_mismatch(inputs: dict[str, Path], tmp_path: Path) -> None:
    wrong = tmp_path / "scale_wrong.json"
    wrong.write_text(json.dumps({"scale_used_for_geometry": synth.SCALE * 1.04}), encoding="utf-8")
    proc = _run(inputs, tmp_path / "out", scale=wrong)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "frame_mismatch"


def test_missing_scale_value(inputs: dict[str, Path], tmp_path: Path) -> None:
    bad = tmp_path / "scale_bad.json"
    bad.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    proc = _run(inputs, tmp_path / "out", scale=bad)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "scale_invalid"


def test_no_shafts_means_exit_3(tmp_path: Path) -> None:
    bare = synth.build_floor(with_shafts=False)
    files = synth.write_inputs(bare, tmp_path / "in")
    proc = _run(files, tmp_path / "out")
    assert proc.returncode == 3, proc.stderr
    assert _error(proc)["code"] == "routes_not_built"
    assert not (tmp_path / "out" / "views").exists()


def test_params_file_is_complete() -> None:
    raw = json.loads((ROOT / "params" / "v1.json").read_text(encoding="utf-8"))
    for name, entry in raw.items():
        assert set(entry) == {"value", "unit", "source", "note"}, name
        assert entry["source"] in {"observed", "derived", "assumed", "algorithm"}, name
