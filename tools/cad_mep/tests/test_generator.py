"""Тесты генератора трасс на синтетическом этаже (tests/synth.py)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
from ezdxf.entities.polyline import Polyline
from ezdxf.filemanagement import readfile
from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

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
    elevation: int | None = None,
    height: int | None = None,
    scale: Path | None = None,
    params: Path | None = None,
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
    ]
    if elevation is not None:
        cmd += ["--floor-elevation-mm", str(elevation)]
    if height is not None:
        cmd += ["--floor-height-mm", str(height)]
    if params is not None:
        cmd += ["--params", str(params)]
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
        assert len(a["heat"]["devices"]) == 4  # спальня и кухня, по два модуля остекления
    assert sorted(a["number"] for a in apts) == ["Кв 1011", "Кв 1012", "Кв 1013", "Кв 1014"]


def test_candidate_content(candidate: dict[str, object], inputs: dict[str, Path]) -> None:
    assert candidate["schema"] == "quantor.cad_mep.candidate.v1"
    prov = candidate["provenance"]
    assert isinstance(prov, dict)
    assert prov["generator_version"] == GENERATOR_VERSION == "cad_mep.v3"
    assert prov["pdf_sha256"] == _sha(inputs["pdf"])
    assert prov["view_dxf_sha256"] == _sha(inputs["dxf"])
    params = load_params(None)
    assert prov["params_sha256"] == params.sha256
    assert params.sha256 == canonical_sha256(json.loads((ROOT / "params" / "v1.json").read_text()))
    assert prov["approval_id"] is None
    elevation = candidate["elevation"]
    assert isinstance(elevation, dict)
    # без ручного ввода: отметка - из заголовка плана, высота - по соседним этажам
    assert elevation["floor_elevation_mm"] == {"value": ELEVATION, "source": "observed"}
    assert elevation["floor_height_mm"] == {"value": HEIGHT, "source": "derived"}
    assert elevation["sheet_marks_mm"] == [ELEVATION]
    assert prov["floor_elevation"] == {
        "value_mm": ELEVATION,
        "source": "observed",
        "evidence": f'стр. 1: "{synth.PLAN_TITLE}"',
    }
    assert prov["floor_height"] == {
        "value_mm": HEIGHT,
        "source": "derived",
        "evidence": "стр. 1 +47,600 → стр. 2 +50,900",
    }
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
    assert checks["each_apt_has_heat_and_water"] == {
        "passed": True,
        "apartments_without_shaft": [],
        "heated_rooms_without_device": [],
    }
    assert checks["heat_beams_are_trees"]["passed"]
    assert checks["aup_coverage"]["passed"]
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


def _candidate_of(out: Path) -> dict[str, object]:
    data = json.loads((out / "views" / FOLDER / "candidate.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_elevation_mismatch_is_issue(
    inputs: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    out = tmp_path_factory.mktemp("out_elev")
    proc = _run(inputs, out, elevation=40000)
    assert proc.returncode == 0, proc.stderr
    data = _candidate_of(out)
    issues = data["issues"]
    assert isinstance(issues, list)
    assert [i["code"] for i in issues] == ["elevation_mismatch"]
    assert "+40,000" in issues[0]["message"] and "+47,600" in issues[0]["message"]
    prov = data["provenance"]
    assert isinstance(prov, dict)
    assert prov["floor_elevation"]["source"] == "operator"
    assert prov["floor_elevation"]["value_mm"] == 40000
    assert prov["floor_height"]["source"] == "derived"


def test_manual_values_equal_to_document_have_no_issues(
    inputs: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    out = tmp_path_factory.mktemp("out_manual")
    proc = _run(inputs, out, elevation=ELEVATION, height=HEIGHT)
    assert proc.returncode == 0, proc.stderr
    data = _candidate_of(out)
    assert data["issues"] == []
    prov = data["provenance"]
    assert isinstance(prov, dict)
    assert prov["floor_height"] == {
        "value_mm": HEIGHT,
        "source": "operator",
        "evidence": "введено вручную",
    }


def test_height_mismatch_is_issue(
    inputs: dict[str, Path], tmp_path_factory: pytest.TempPathFactory
) -> None:
    out = tmp_path_factory.mktemp("out_height")
    proc = _run(inputs, out, height=3000)
    assert proc.returncode == 0, proc.stderr
    issues = _candidate_of(out)["issues"]
    assert isinstance(issues, list)
    assert [i["code"] for i in issues] == ["floor_height_mismatch"]


def test_no_title_asks_for_manual_elevation(tmp_path: Path) -> None:
    files = synth.write_inputs(synth.build_floor(), tmp_path / "in", None, ())
    proc = _run(files, tmp_path / "out")
    assert proc.returncode == 2
    err = _error(proc)
    assert err["code"] == "elevation_not_found"
    assert "вручную" in err["message"]
    assert not (tmp_path / "out" / "views").exists()
    # отметку ввели, высоты в документации нет - просим высоту
    proc = _run(files, tmp_path / "out2", elevation=ELEVATION)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "floor_height_not_found"
    # обе введены - документация не нужна
    proc = _run(files, tmp_path / "out3", elevation=ELEVATION, height=HEIGHT)
    assert proc.returncode == 0, proc.stderr


def _error(proc: subprocess.CompletedProcess[str]) -> dict[str, str]:
    line = proc.stderr.strip().splitlines()[-1]
    data = json.loads(line)
    assert set(data) == {"code", "message"}
    return {"code": str(data["code"]), "message": str(data["message"])}


def test_page_out_of_range(inputs: dict[str, Path], tmp_path: Path) -> None:
    proc = _run(inputs, tmp_path, page_index=5, elevation=ELEVATION, height=HEIGHT)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "page_out_of_range"


def test_height_out_of_range(inputs: dict[str, Path], tmp_path: Path) -> None:
    proc = _run(inputs, tmp_path, elevation=ELEVATION, height=1500)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "height_invalid"


def test_frame_mismatch(inputs: dict[str, Path], tmp_path: Path) -> None:
    wrong = tmp_path / "scale_wrong.json"
    wrong.write_text(json.dumps({"scale_used_for_geometry": synth.SCALE * 1.04}), encoding="utf-8")
    proc = _run(inputs, tmp_path / "out", scale=wrong, elevation=ELEVATION, height=HEIGHT)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "frame_mismatch"


def test_missing_scale_value(inputs: dict[str, Path], tmp_path: Path) -> None:
    bad = tmp_path / "scale_bad.json"
    bad.write_text(json.dumps({"status": "passed"}), encoding="utf-8")
    proc = _run(inputs, tmp_path / "out", scale=bad, elevation=ELEVATION, height=HEIGHT)
    assert proc.returncode == 2
    assert _error(proc)["code"] == "scale_invalid"


@pytest.mark.parametrize(
    ("wall_layer", "issue_codes", "has_underlay"),
    [
        # движок с 2026.11.10 переименовал слой контуров стен: имя есть в параметрах
        (synth.WALL_LAYER_AUX, [], True),
        # имени нет в параметрах: привязка по всем полилиниям DXF и замечание
        ("XX_НОВОЕ_ИМЯ_СТЕН", ["dxf_wall_layers_unknown"], False),
    ],
)
def test_wall_layer_names_of_other_engine_versions(
    floor: synth.Floor, tmp_path: Path, wall_layer: str, issue_codes: list[str], has_underlay: bool
) -> None:
    files = synth.write_inputs(floor, tmp_path / "in", wall_layer=wall_layer)
    proc = _run(files, tmp_path / "out")
    assert proc.returncode == 0, proc.stderr
    data = _candidate_of(tmp_path / "out")
    issues = data["issues"]
    assert isinstance(issues, list)
    assert [i["code"] for i in issues] == issue_codes
    checks = data["checks"]
    assert isinstance(checks, dict)
    assert checks["tie_pdf_to_dxf"]["passed"]
    assert checks["tie_pdf_to_dxf"]["err_median_mm"] < 1.0
    assert (checks["dxf"]["wall_entities_view"] > 0) is has_underlay
    routes = data["routes"]
    assert isinstance(routes, dict)
    assert routes["by_system"]["heating"]["len3d_m"] > 0


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


# ---------- приборы по модулям остекления, комнаты без марок, лучи-деревья, АУП (cad_mep.v3)


def _local(d: dict[str, object]) -> tuple[float, float]:
    """Координаты прибора в мм здания (без сдвига DXF)."""
    xy = d["device_dxf_mm"]
    assert isinstance(xy, list)
    return (float(xy[0]) - synth.SHIFT[0], float(xy[1]) - synth.SHIFT[1])


def _apartments(data: dict[str, object]) -> dict[str, dict[str, object]]:
    apts = data["apartments"]
    assert isinstance(apts, list)
    return {a["number"]: a for a in apts}


def _heat(apartment: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    """Раздел отопления квартиры: списки комнат и приборов."""
    heat = apartment["heat"]
    assert isinstance(heat, dict)
    return {"rooms": list(heat["rooms"]), "devices": list(heat["devices"])}


def _heat_counts(apartment: dict[str, object]) -> tuple[int, int, int]:
    """(отапливаемых комнат, из них с приборами, приборов)."""
    heat = apartment["heat"]
    assert isinstance(heat, dict)
    return (heat["heated_rooms"], heat["rooms_with_devices"], heat["devices_count"])


def _issue_codes(data: dict[str, object]) -> list[str]:
    issues = data["issues"]
    assert isinstance(issues, list)
    return [i["code"] for i in issues]


def _variant(tmp_path: Path, floor: synth.Floor) -> dict[str, object]:
    files = synth.write_inputs(floor, tmp_path / "in")
    proc = _run(files, tmp_path / "out")
    assert proc.returncode == 0, proc.stderr
    return _candidate_of(tmp_path / "out")


def _no_loops(dxf: Path) -> None:
    """Подача и обратка всего этажа не образуют замкнутых контуров."""
    doc = readfile(str(dxf))
    for layer in ("M-OV-T1", "M-OV-T2"):
        lines = []
        for e in (e for e in doc.modelspace() if isinstance(e, Polyline)):
            pts = [(p[0], p[1]) for p in e.points()]
            if e.dxf.layer == layer and len(set(pts)) > 1:
                lines.append(LineString(pts))
        assert lines
        assert sum(face.area for face in polygonize(unary_union(lines))) < 100.0, layer


def test_device_on_every_glazing_module(candidate: dict[str, object], run_a: Path) -> None:
    """Фасад с простенками через 3 м: на каждом участке остекления — один прибор в середине."""
    spans = synth.glazing_spans()
    seen: Counter[tuple[bool, int]] = Counter()
    for number, a in _apartments(candidate).items():
        heat = a["heat"]
        assert isinstance(heat, dict)
        assert _heat_counts(a) == (2, 2, 4), number
        assert Counter(d["room_id"] for d in heat["devices"]).most_common() == [
            (r["room_id"], 2) for r in heat["rooms"]
        ]
        assert all(r["status"] == "ok" and r["placed_by"] == "label" for r in heat["rooms"])
        for d in heat["devices"]:
            x, y = _local(d)
            north = y > synth.H / 2
            k = next(i for i, (a0, a1) in enumerate(spans) if a0 < x < a1)  # не у простенка
            seen[(north, k)] += 1
            # линия приборов — 650 мм от наружной грани (полоса фасада 450 + отступ 200)
            assert min(y, synth.H - y) == pytest.approx(650, abs=50)
            assert d["modules_assumed"] is False
            assert d["path_from_collector_m"] > 0
            # кухня юго-западной квартиры: модуль укорочен коробом стояка, прибор сдвинут
            if not (number == "Кв 1011" and k == 3):
                assert x == pytest.approx(sum(spans[k]) / 2, abs=100), (number, k)
    assert seen == Counter({(north, k): 1 for north in (False, True) for k in range(len(spans))})
    _no_loops(run_a / "mep_routes.dxf")


def test_solid_facade_assumes_module_pitch(tmp_path: Path) -> None:
    """Остекление не найдено (сплошная стена): приборы по шагу модулей и замечание."""
    data = _variant(tmp_path, synth.build_floor(glazing=False))
    assert set(_issue_codes(data)) == {"glazing_modules_assumed"}
    assert len(_issue_codes(data)) == 8  # спальня и кухня каждой из четырёх квартир
    for a in _apartments(data).values():
        assert _heat_counts(a) == (2, 2, 4)  # стена 4,8–5,9 м при шаге 3,3 м — по два прибора
        assert all(d["modules_assumed"] for d in _heat(a)["devices"])
    checks = data["checks"]
    assert isinstance(checks, dict)
    assert checks["each_apt_has_heat_and_water"]["passed"]


def test_rooms_without_labels_are_assigned_by_area(tmp_path: Path) -> None:
    """Марок трёх комнат на плане нет: кухня за дверью, спальня без двери, кухня без стены
    с прихожей. Все три находятся по остатку площади и получают приборы."""
    floor = synth.build_floor(closed_bedroom=2, open_kitchen=3)
    synth.drop_labels(floor, {"1-1/3", "1-2/1", "1-3/3"})
    data = _variant(tmp_path, floor)
    issues = data["issues"]
    assert isinstance(issues, list)
    assert [i["code"] for i in issues] == ["room_assigned_by_area"] * 3
    text = {i["apartment"]: i["message"] for i in issues}
    assert "1-1/3 Кухня" in text["Кв 1011"] and "14,35 м²" in text["Кв 1011"]
    assert "без двери" in text["Кв 1012"] and "24,15 м²" in text["Кв 1012"]
    assert "общее с 1-3/2" in text["Кв 1013"]
    rooms = data["rooms"]
    assert isinstance(rooms, list)
    by_id = {r["room_id"]: r for r in rooms}
    for rid in ("1-1/3", "1-2/1", "1-3/3"):
        assert by_id[rid]["assigned_by_area"] and by_id[rid]["plan_labels"] == 0
        assert by_id[rid]["comp"] is not None
    assert sum(1 for r in rooms if r["assigned_by_area"]) == 3
    # кухня без стены с прихожей: одно помещение, наружная стена принадлежит кухне
    assert by_id["1-3/3"]["comp"] == by_id["1-3/2"]["comp"]
    apts = _apartments(data)
    for number, a in apts.items():
        assert _heat_counts(a) == (2, 2, 4), number
    by_area = [
        str(r["room_id"])
        for a in apts.values()
        for r in _heat(a)["rooms"]
        if r["placed_by"] == "area"
    ]
    assert sorted(by_area) == ["1-1/3", "1-2/1", "1-3/3"]
    # спальня без двери присоединена к своей квартире, к ней проложен проход
    assert apts["Кв 1012"]["detached_groups"]
    openings = data["virtual_openings"]
    assert isinstance(openings, list) and len(openings) == 1
    checks = data["checks"]
    assert isinstance(checks, dict)
    assert checks["rooms_count"]["missing_ids"] == []
    assert checks["rooms_count"]["assigned_by_area"] == ["1-1/3", "1-2/1", "1-3/3"]
    assert checks["each_apt_has_heat_and_water"]["passed"]
    assert checks["heat_beams_are_trees"] == {
        "passed": True,
        "apartments_not_tree": [],
        "loops_area_m2": 0.0,
        "points_in_other_apartments": 0,
    }
    assert checks["no_wall_crossing"]["passed"]
    _no_loops(tmp_path / "out" / "views" / FOLDER / "mep_routes.dxf")


def test_heated_room_criterion_and_completeness(tmp_path: Path) -> None:
    """Названия вне списков и комната, которой нет на плане: замечания и FAIL проверки полноты."""
    floor = synth.build_floor()
    rename = {"1-3/1": "Кладовая", "1-4/3": "Игровая"}
    # площадь кухни 1-1/3 в экспликации не сходится с планом: по площади её не найти
    floor.expl = [
        (rid, rename.get(rid, name), 30.0 if rid == "1-1/3" else area)
        for rid, name, area in floor.expl
    ]
    synth.drop_labels(floor, {"1-1/3"})
    data = _variant(tmp_path, floor)
    issues = data["issues"]
    assert isinstance(issues, list)
    by_code: dict[str, list[str]] = {}
    for i in issues:
        by_code.setdefault(i["code"], []).append(i["message"])
    assert sorted(by_code) == ["heated_room_without_device", "room_heating_assumed"]
    # помещение без марки с остеклением и «Игровая» приняты отапливаемыми
    assert len(by_code["room_heating_assumed"]) == 2
    assert any("Игровая" in m for m in by_code["room_heating_assumed"])
    assert any("без названия" in m for m in by_code["room_heating_assumed"])
    assert len(by_code["heated_room_without_device"]) == 1
    assert "1-1/3 Кухня" in by_code["heated_room_without_device"][0]
    apts = _apartments(data)
    assert {n: _heat_counts(a) for n, a in apts.items()} == {
        "Кв 1011": (3, 2, 4),  # спальня, кухня без прибора и помещение без марки
        "Кв 1012": (2, 2, 4),
        "Кв 1013": (1, 1, 2),  # «Кладовая» — исключение: без прибора и без замечания
        "Кв 1014": (2, 2, 4),
    }
    status = {r["room_id"]: (r["heating"], r["status"]) for r in _heat(apts["Кв 1011"])["rooms"]}
    assert status["1-1/3"] == ("listed", "not_on_plan")
    assert ("assumed", "ok") in status.values()
    checks = data["checks"]
    assert isinstance(checks, dict)
    assert checks["each_apt_has_heat_and_water"] == {
        "passed": False,
        "apartments_without_shaft": [],
        "heated_rooms_without_device": ["Кв 1011: 1-1/3"],
    }


def test_aup_branch_covers_lift_hall(tmp_path: Path) -> None:
    """Лифтовой холл за дверью в торце коридора: ветка АУП заходит в него, покрытие — в файле."""
    data = _variant(tmp_path, synth.build_floor(hall=True))
    assert data["issues"] == []
    checks = data["checks"]
    assert isinstance(checks, dict)
    cover = checks["aup_coverage"]
    assert cover["passed"]
    rooms = {tuple(r["names"]): r for r in cover["rooms"]}
    assert set(rooms) == {("Коридор",), ("Лифтовой холл",)}
    assert all(r["covered_share"] >= cover["min_share"] for r in rooms.values())
    routes = data["routes"]
    assert isinstance(routes, dict)
    assert routes["fire"]["aup_coverage"] == cover["rooms"]
    # линия АУП доходит до дальней части холла, а не кончается у его двери
    doc = readfile(str(tmp_path / "out" / "views" / FOLDER / "mep_routes.dxf"))
    xs = [
        p[0] - synth.SHIFT[0]
        for e in doc.modelspace()
        if isinstance(e, Polyline) and e.dxf.layer == "M-PT-AUP"
        for p in e.points()
    ]
    assert min(xs) < synth.HALL_X - 1000


def test_aup_low_coverage_is_reported(inputs: dict[str, Path], tmp_path: Path) -> None:
    """Ветка не проложена (дальних точек с таким отступом от стен нет): покрытие 0 и замечания."""
    raw = json.loads((ROOT / "params" / "v1.json").read_text(encoding="utf-8"))
    raw["aup_end_clearance_mm"]["value"] = 5000
    custom = tmp_path / "params.json"
    custom.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    proc = _run(inputs, tmp_path / "out", params=custom)
    assert proc.returncode == 0, proc.stderr
    data = _candidate_of(tmp_path / "out")
    assert _issue_codes(data) == ["fire_aup_no_ends", "aup_coverage_low"]
    checks = data["checks"]
    assert isinstance(checks, dict)
    assert checks["aup_coverage"]["passed"] is False
    assert [r["covered_share"] for r in checks["aup_coverage"]["rooms"]] == [0.0]
