"""Сборка пакета из синтетического IFC и самопроверка по разделу 9."""

from __future__ import annotations

import json
import shutil
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from synth_ifc import SynthModel, make_arch_ifc

from model_package.qmp_build import IfcInput, build_package
from model_package.qmp_check import check_package, format_report, read_glb


def _rows(pkg: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted((pkg / "elements").glob("*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows


def _node_bounds(glb: Path, name: str) -> tuple[np.ndarray, np.ndarray]:
    """min/max вершин узла по его аксессору POSITION и сами вершины из двоичного блока."""
    data = glb.read_bytes()
    doc = read_glb(data)
    jlen = struct.unpack_from("<I", data, 12)[0]
    binary = data[20 + jlen + 8 :]
    node = next(n for n in doc["nodes"] if n["name"] == name)
    acc = doc["accessors"][doc["meshes"][node["mesh"]]["primitives"][0]["attributes"]["POSITION"]]
    view = doc["bufferViews"][acc["bufferView"]]
    start = view["byteOffset"] + acc["byteOffset"]
    verts = np.frombuffer(binary, dtype="<f4", count=acc["count"] * 3, offset=start).reshape(-1, 3)
    assert np.allclose(verts.min(axis=0), acc["min"]) and np.allclose(verts.max(axis=0), acc["max"])
    return verts.min(axis=0), verts.max(axis=0)


@pytest.fixture(scope="module")
def package(arch: SynthModel, pl_ifc: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    out = tmp_path_factory.mktemp("pkg") / "qmp"
    return build_package([IfcInput(arch.path), IfcInput(pl_ifc)], out)


def test_build_passes_check(package: Any) -> None:
    report = check_package(package.out_dir)
    assert report.ok, format_report(report)
    assert not report.warnings, format_report(report)


def test_storeys_merged_by_elevation(package: Any, arch: SynthModel) -> None:
    storeys = json.loads((package.out_dir / "storeys.json").read_text(encoding="utf-8"))
    keys = [arch.storeys["Этаж 1"].replace("$", "-"), arch.storeys["Этаж 2"].replace("$", "-")]
    assert [s["storey_key"] for s in storeys] == keys
    assert [s["elevation_mm"] for s in storeys] == [0.0, 3000.0]
    assert [s["height_mm"] for s in storeys] == [3000.0, None]
    assert storeys[0]["bbox_mm"] == [-200.0, 0.0, 12000.0, 8000.0]
    assert package.manifest["frame"]["origin_offset_mm"] == [0.0, 0.0, 100000.0]


def test_grids_merged(package: Any) -> None:
    grids = json.loads((package.out_dir / "grids.json").read_text(encoding="utf-8"))
    pairs = [(a["tag"], a["dir"]) for a in grids["axes"]]
    assert pairs == [("1", "U"), ("2", "U"), ("3", "U"), ("А", "V"), ("Б", "V")]
    assert grids["axes"][1]["p0"] == [6000.0, -1500.0]


def test_elements_parts_and_categories(package: Any, arch: SynthModel) -> None:
    rows = {r["id"]: r for r in _rows(package.out_dir)}
    assert arch.opening_id not in rows
    assert rows[arch.curtain_id]["part"] is None and rows[arch.curtain_id]["bbox_mm"] is None
    assert sorted(rows[p]["category"] for p in arch.part_ids) == ["member", "member", "plate"]
    assert all(rows[p]["part"] for p in arch.part_ids)
    pipe = next(r for r in rows.values() if r["ifc_class"] == "IfcPipeSegment")
    assert pipe["category"] == "pipe" and pipe["discipline"] == "PL"
    assert pipe["storey_key"] == arch.storeys["Этаж 2"].replace("$", "-")
    assert pipe["part"].endswith("__PL.glb")
    disciplines = {d["code"]: d["elements"] for d in package.manifest["disciplines"]}
    assert disciplines == {"ARCH": 8, "PL": 1}


def test_glb_frame_is_metres_y_up(package: Any, arch: SynthModel) -> None:
    row = next(r for r in _rows(package.out_dir) if r["id"] == arch.column_id)
    assert row["bbox_mm"] == [5800.0, 3800.0, 3000.0, 6200.0, 4200.0, 6000.0]
    lo, hi = _node_bounds(package.out_dir / row["part"], arch.column_id)
    assert np.allclose(lo, [5.8, 3.0, -4.2], atol=1e-5)
    assert np.allclose(hi, [6.2, 6.0, -3.8], atol=1e-5)


def test_footprint_groups(package: Any, arch: SynthModel) -> None:
    key = arch.storeys["Этаж 1"].replace("$", "-")
    fp = json.loads((package.out_dir / "footprints" / f"{key}.json").read_text(encoding="utf-8"))
    assert fp["z_cut_mm"] == 1200.0
    assert set(fp["polygons"]) == {"walls", "curtain"}
    for ring in fp["polygons"]["walls"]:
        assert ring[0] != ring[-1]
    xs = sorted(min(p[0] for p in ring) for ring in fp["polygons"]["walls"])
    assert xs == [-200.0, 3000.0]  # проём 2000–3000 разрезал стену


def test_rebuild_is_deterministic(arch: SynthModel, pl_ifc: Path, tmp_path: Path) -> None:
    inputs = [IfcInput(arch.path), IfcInput(pl_ifc)]
    a = build_package(inputs, tmp_path / "a", now=datetime(2026, 1, 1, tzinfo=UTC))
    b = build_package(inputs, tmp_path / "b", now=datetime(2026, 11, 16, tzinfo=UTC))
    assert a.manifest["generated_at"] != b.manifest["generated_at"]
    assert a.manifest["manifest_sha256"] == b.manifest["manifest_sha256"]
    for part in a.manifest["parts"]:
        rel = part["path"]
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes(), rel


def test_large_storey_split_into_parts(arch: SynthModel, tmp_path: Path) -> None:
    result = build_package([IfcInput(arch.path)], tmp_path / "pkg", part_limit=2600)
    geometry = [p["path"] for p in result.manifest["parts"] if p["kind"] == "geometry"]
    assert any(p.endswith("__ARCH.1.glb") for p in geometry)
    assert any(p.endswith("__ARCH.2.glb") for p in geometry)
    report = check_package(result.out_dir)
    assert report.ok, format_report(report)


def test_duplicate_input_and_discipline(arch: SynthModel, tmp_path: Path) -> None:
    copy = tmp_path / "copy.ifc"
    shutil.copy(arch.path, copy)
    result = build_package([IfcInput(arch.path), IfcInput(copy, "STR")], tmp_path / "pkg")
    assert len(result.manifest["source"]["files"]) == 1
    assert result.manifest["source"]["files"][0]["discipline"] == "ARCH"
    assert any("тот же sha256" in w for w in result.warnings)


def test_only_storey(arch: SynthModel, tmp_path: Path) -> None:
    result = build_package([IfcInput(arch.path)], tmp_path / "pkg", only_storey="этаж 2")
    storeys = json.loads((result.out_dir / "storeys.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in storeys] == ["Этаж 2"]
    assert result.manifest["counts"]["elements"] == 2
    assert check_package(result.out_dir).ok


def test_out_dir_with_foreign_files_refused(arch: SynthModel, tmp_path: Path) -> None:
    out = tmp_path / "pkg"
    out.mkdir()
    (out / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(Exception, match="посторонние"):
        build_package([IfcInput(arch.path)], out)


def test_ifc2x3_source(tmp_path: Path) -> None:
    model = make_arch_ifc(tmp_path / "OLD_ARCH.ifc", schema="IFC2X3")
    result = build_package([IfcInput(model.path)], tmp_path / "pkg")
    report = check_package(result.out_dir)
    assert report.ok, format_report(report)
    assert result.manifest["source"]["ifc_schema"] == "IFC2X3"
    assert result.manifest["counts"]["elements"] == 8


def test_heavy_openings_are_not_subtracted(arch: SynthModel) -> None:
    import ifcopenshell

    from model_package.tessellate import opening_faces, tessellate

    model = ifcopenshell.open(str(arch.path))
    wall = next(w for w in model.by_type("IfcWall") if w.HasOpenings)
    assert opening_faces(wall) == 1
    cut, heavy = tessellate(model, [wall], (0.0, 0.0, 100000.0))
    assert not heavy
    whole, heavy = tessellate(model, [wall], (0.0, 0.0, 100000.0), heavy_limit=0)
    assert heavy == [wall]
    assert len(whole[wall.id()].faces) < len(cut[wall.id()].faces)
