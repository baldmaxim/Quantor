"""3D DXF этажа: слои, MESH, отметки, вырезы плиты, заголовок, детерминизм."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.mesh import Mesh
from ezdxf.filemanagement import readfile
from ezdxf.math import Vec3

from cad_walls import floor3d_dxf as f3d
from cad_walls.errors import WallsError
from run_floor3d_dxf import main

BASE = 47600
SLAB_BOTTOM = 47300
WALL_TOP = 50600
RECT_OUT = [[0, 0], [3000, 0], [3000, 3000], [0, 3000]]
RECT_IN = [[200, 200], [2800, 200], [2800, 2800], [200, 2800]]


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _model() -> dict[str, object]:
    return {
        "units": "mm",
        "generator": "cad_walls.v1.4",
        "heights": {
            "floor_elevation_mm": BASE,
            "floor_elevation_source": "drawing",
            "floor_height": {"value_mm": 3300, "source": "derived", "default_mm": 3300},
            "slab_thickness": {"value_mm": 300, "source": "manual", "default_mm": None},
            "door_height": {"value_mm": 2100, "source": "assumed", "default_mm": 2100},
            "slab_thickness_sheet_ref": "АР1.1 л. 45, разрез 4-4",
            "wall_height_mm": 3000,
            "wall_height_source": "derived",
            "evidence": None,
            "message": None,
        },
        "base_z_mm": BASE,
        "elevation_known": True,
        "slab": {
            "shell": _rect(0, 0, 10000, 8000),
            "z_bottom_mm": SLAB_BOTTOM,
            "z_top_mm": BASE,
            "area_m2": 80.0,
        },
        "slab_holes": [
            {
                "key": "a1",
                "shell": _rect(1000, 1000, 2000, 2000),
                "area_m2": 1.0,
                "state": "enabled",
            },
            {
                "key": "b2",
                "shell": _rect(4000, 1000, 5000, 2000),
                "area_m2": 1.0,
                "state": "candidate",
            },
            {
                "key": "c3",
                "shell": _rect(7000, 5000, 8000, 6000),
                "area_m2": 1.0,
                "state": "disabled",
            },
        ],
        "walls": [
            {
                "construction_key": "w-ring",
                "kind": "masonry",
                "family": "masonry",
                "thickness_nominal_mm": 200.0,
                "shell": RECT_OUT,
                "holes": [RECT_IN],
                "z_bottom_mm": BASE,
                "z_top_mm": WALL_TOP,
            },
            {
                "construction_key": "w-column",
                "kind": "column",
                "family": "monolith",
                "thickness_nominal_mm": None,
                "shell": _rect(5000, 5000, 5400, 5400),
                "holes": [],
                "z_bottom_mm": BASE,
                "z_top_mm": WALL_TOP,
            },
            {
                "construction_key": "w-no-top",
                "kind": "masonry",
                "family": "masonry",
                "thickness_nominal_mm": 100.0,
                "shell": _rect(6000, 0, 7000, 100),
                "holes": [],
                "z_bottom_mm": BASE,
                "z_top_mm": None,
            },
        ],
        "lintels": [
            {
                "opening_id": "o1",
                "kind": "door",
                "shell": _rect(1000, 0, 1900, 200),
                "z_bottom_mm": BASE + 2100,
                "z_top_mm": WALL_TOP,
                "door_height_mm": 2100,
                "door_height_source": "assumed",
            }
        ],
        "doors": [
            {
                "opening_id": "o1",
                "shell": _rect(1000, 80, 1900, 120),
                "z_bottom_mm": BASE,
                "z_top_mm": BASE + 2100,
                "door_height_mm": 2100,
                "door_height_source": "assumed",
            }
        ],
        "bbox": [0, 0, 10000, 8000],
        "warnings": [{"code": "slab_thickness_assumed", "message": "Толщина плиты - допущение."}],
    }


def _write(tmp_path: Path, model: dict[str, object], name: str = "model.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    return path


def _build(tmp_path: Path, model: dict[str, object] | None = None) -> Path:
    out = tmp_path / "floor3d.dxf"
    assert main(["--model", str(_write(tmp_path, model or _model())), "--out", str(out)]) == 0
    return out


def _meshes(path: Path) -> dict[str, list[Mesh]]:
    result: dict[str, list[Mesh]] = {}
    for entity in readfile(path).modelspace():
        if isinstance(entity, Mesh):
            result.setdefault(entity.dxf.layer, []).append(entity)
    return result


def _points(mesh: Mesh) -> list[Vec3]:
    return [Vec3(v) for v in mesh.vertices]


def _volume(mesh: Mesh) -> float:
    """Объём по замкнутой сетке (формула Гаусса): положителен, если грани смотрят наружу."""
    vertices = _points(mesh)
    total = 0.0
    for face in mesh.faces:
        for i in range(1, len(face) - 1):
            a, b, c = (vertices[face[0]], vertices[face[i]], vertices[face[i + 1]])
            total += a.dot(b.cross(c)) / 6.0
    return total


def test_layers_and_mesh_counts(tmp_path: Path) -> None:
    doc = readfile(_build(tmp_path))
    assert doc.dxfversion == "AC1032"
    assert doc.units == 4
    assert not doc.audit().errors
    colors = {name: doc.layers.get(name).dxf.color for name in f3d.LAYER_COLORS}
    assert colors == f3d.LAYER_COLORS
    assert len(set(colors.values())) == len(colors)
    counts = {layer: len(items) for layer, items in _meshes(tmp_path / "floor3d.dxf").items()}
    # Стена без высоты не выведена: кладки одна (кольцо), монолита одна (колонна).
    assert counts == {
        f3d.LAYER_SLAB: 1,
        f3d.LAYER_MASONRY: 1,
        f3d.LAYER_MONOLITH: 1,
        f3d.LAYER_LINTELS: 1,
        f3d.LAYER_DOORS: 1,
    }


def test_z_ranges_match_model(tmp_path: Path) -> None:
    meshes = _meshes(_build(tmp_path))
    expected = {
        f3d.LAYER_SLAB: (SLAB_BOTTOM, BASE),
        f3d.LAYER_MASONRY: (BASE, WALL_TOP),
        f3d.LAYER_MONOLITH: (BASE, WALL_TOP),
        f3d.LAYER_LINTELS: (BASE + 2100, WALL_TOP),
        f3d.LAYER_DOORS: (BASE, BASE + 2100),
    }
    for layer, (z0, z1) in expected.items():
        zs = {round(v.z, 6) for v in _points(meshes[layer][0])}
        assert zs == {z0, z1}, layer


def test_meshes_are_closed_and_outward(tmp_path: Path) -> None:
    for items in _meshes(_build(tmp_path)).values():
        for mesh in items:
            edges: Counter[tuple[int, int]] = Counter()
            for face in mesh.faces:
                for i, a in enumerate(face):
                    edges[(a, face[(i + 1) % len(face)])] += 1
            # Замкнутая ориентированная сетка: у каждого ребра ровно одно обратное и по одному.
            assert all(n == 1 and edges[(b, a)] == 1 for (a, b), n in edges.items())
            assert _volume(mesh) > 0


def test_slab_volume_and_cuts_only_enabled_and_candidate(tmp_path: Path) -> None:
    slab = _meshes(_build(tmp_path))[f3d.LAYER_SLAB][0]
    # Объём проверяет только тест: 10x8 м минус два выреза 1x1 м, толщина 0,3 м.
    assert _volume(slab) == pytest.approx((80_000_000 - 2_000_000) * 300)
    xy = {(round(v.x), round(v.y)) for v in _points(slab)}
    assert (1000, 1000) in xy and (5000, 2000) in xy
    assert (7000, 5000) not in xy and (8000, 6000) not in xy


def test_wall_ring_has_hole_and_column_is_monolith(tmp_path: Path) -> None:
    meshes = _meshes(_build(tmp_path))
    ring = meshes[f3d.LAYER_MASONRY][0]
    xy = {(round(v.x), round(v.y)) for v in _points(ring)}
    assert {(0, 0), (3000, 3000), (200, 200), (2800, 2800)} <= xy
    assert _volume(ring) == pytest.approx((9_000_000 - 2600 * 2600) * 3000)
    assert (6000, 0) not in {(round(v.x), round(v.y)) for v in _points(ring)}


def test_hole_outlines_on_slab_top(tmp_path: Path) -> None:
    doc = readfile(_build(tmp_path))
    outlines = [e for e in doc.modelspace() if isinstance(e, LWPolyline)]
    assert {(e.dxf.layer, e.dxf.elevation) for e in outlines} == {
        (f3d.LAYER_HOLES, BASE),
        (f3d.LAYER_HOLES_CANDIDATE, BASE),
    }
    assert all(e.closed for e in outlines)


def test_header_properties(tmp_path: Path) -> None:
    model_path = _write(tmp_path, _model())
    out = tmp_path / "floor3d.dxf"
    assert main(["--model", str(model_path), "--out", str(out)]) == 0
    props = dict(readfile(out).header.custom_vars.properties)
    assert props["QUANTOR_GENERATOR"] == "cad_floor3d_dxf.v2"
    assert props["QUANTOR_MODEL_SHA256"] == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert props["QUANTOR_FLOOR_ELEVATION_MM"] == "47600"
    assert props["QUANTOR_FLOOR_ELEVATION_SOURCE"] == "drawing"
    assert props["QUANTOR_FLOOR_HEIGHT_MM"] == "3300"
    assert props["QUANTOR_FLOOR_HEIGHT_SOURCE"] == "derived"
    assert props["QUANTOR_SLAB_THICKNESS_MM"] == "300"
    assert props["QUANTOR_SLAB_THICKNESS_SOURCE"] == "manual"
    assert props["QUANTOR_SLAB_THICKNESS_SHEET"] == "АР1.1 л. 45, разрез 4-4"
    assert props["QUANTOR_DOOR_HEIGHT_MM"] == "2100"
    assert props["QUANTOR_DOOR_HEIGHT_SOURCE"] == "assumed"
    assert props["QUANTOR_WARNINGS"] == "slab_thickness_assumed: Толщина плиты - допущение."


def test_unknown_elevation_is_marked(tmp_path: Path) -> None:
    model = _model()
    model["elevation_known"] = False
    heights = copy.deepcopy(model["heights"])
    assert isinstance(heights, dict)
    heights["floor_elevation_mm"] = None
    heights["floor_elevation_source"] = None
    model["heights"] = heights
    props = dict(readfile(_build(tmp_path, model)).header.custom_vars.properties)
    assert props["QUANTOR_FLOOR_ELEVATION_MM"] == "не определена (построено от нуля)"
    assert props["QUANTOR_FLOOR_ELEVATION_SOURCE"] == "не определён"


def test_deterministic_for_same_model(tmp_path: Path) -> None:
    model_path = _write(tmp_path, _model())
    a, b = tmp_path / "a.dxf", tmp_path / "b.dxf"
    assert main(["--model", str(model_path), "--out", str(a)]) == 0
    assert main(["--model", str(model_path), "--out", str(b)]) == 0

    def entities(path: Path) -> list[tuple[str, str, list[tuple[float, float, float]]]]:
        rows = []
        for e in readfile(path).modelspace():
            points = [(v.x, v.y, v.z) for v in _points(e)] if isinstance(e, Mesh) else []
            rows.append((e.dxftype(), e.dxf.layer, points))
        return rows

    assert entities(a) == entities(b)
    assert a.read_bytes() == b.read_bytes()


def test_entity_order_does_not_depend_on_model_order(tmp_path: Path) -> None:
    shuffled = _model()
    for key in ("walls", "slab_holes"):
        items = shuffled[key]
        assert isinstance(items, list)
        shuffled[key] = list(reversed(items))
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    a = _build(first)
    b = _build(second, shuffled)
    assert [(e.dxftype(), e.dxf.layer) for e in readfile(a).modelspace()] == [
        (e.dxftype(), e.dxf.layer) for e in readfile(b).modelspace()
    ]


def test_skips_are_reported_not_silent(tmp_path: Path) -> None:
    model = _model()
    out = tmp_path / "out.dxf"
    summary = f3d.generate(_write(tmp_path, model), out)
    assert summary["skipped"] == ["стена w-no-top: высота не определена"]
    assert summary["triangulation_mismatch"] == []
    assert summary["outlines"] == 2


def test_slab_without_thickness_is_not_built(tmp_path: Path) -> None:
    model = _model()
    slab = model["slab"]
    assert isinstance(slab, dict)
    slab["z_bottom_mm"] = None
    summary = f3d.generate(_write(tmp_path, model), tmp_path / "out.dxf")
    skipped = summary["skipped"]
    assert isinstance(skipped, list)
    assert "плита: толщина не определена" in skipped
    assert f3d.LAYER_SLAB not in _meshes(tmp_path / "out.dxf")


def test_hole_outside_slab_is_not_cut(tmp_path: Path) -> None:
    model = _model()
    holes = model["slab_holes"]
    assert isinstance(holes, list)
    holes.append(
        {"key": "z9", "shell": _rect(9500, 7500, 11000, 9000), "area_m2": 1.0, "state": "enabled"}
    )
    summary = f3d.generate(_write(tmp_path, model), tmp_path / "out.dxf")
    skipped = summary["skipped"]
    assert isinstance(skipped, list)
    assert any("z9" in row for row in skipped)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(units="m"),
        lambda m: m.update(base_z_mm="x"),
        lambda m: m.update(walls=[{"construction_key": "k", "family": "wood"}]),
        lambda m: m.update(slab_holes=[{"key": "k", "state": "maybe", "shell": []}]),
    ],
)
def test_bad_model_is_rejected(tmp_path: Path, mutate: object) -> None:
    model = _model()
    assert callable(mutate)
    mutate(model)
    with pytest.raises(WallsError) as info:
        f3d.generate(_write(tmp_path, model), tmp_path / "out.dxf")
    assert info.value.code == "bad_model"


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert main(["--model", str(broken), "--out", str(tmp_path / "o.dxf")]) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "bad_model"
    assert main(["--model", str(tmp_path / "none.json"), "--out", str(tmp_path / "o.dxf")]) == 2
    with pytest.raises(SystemExit) as info:
        main(["--out", str(tmp_path / "o.dxf")])
    assert info.value.code == 2


def test_model_without_doors_key_has_no_door_layer_meshes(tmp_path: Path) -> None:
    """Модель прежней версии API (без `doors`) строится; полотен нет."""
    model = _model()
    del model["doors"]
    meshes = _meshes(_build(tmp_path, model))
    assert f3d.LAYER_DOORS not in meshes
    assert f3d.LAYER_LINTELS in meshes
