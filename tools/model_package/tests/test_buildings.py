"""Этажи по зданиям (раздел 4): корпуса одного IFC не сводятся по отметке (объект 346)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from synth_ifc import make_arch_ifc, make_k2_str_ifc, make_pl_ifc, make_two_buildings_ifc

from model_package.qmp_build import IfcInput, build_package
from model_package.qmp_check import check_package, manifest_digest

BUILDINGS = ("Корпус 1", "Корпус 2")
LEVELS = ("1 этаж", "2 этаж", "Кровля")
Ids = dict[str, dict[str, str]]


def _key(global_id: str) -> str:
    return global_id.replace("$", "-")


def _storeys(out: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads((out / "storeys.json").read_text(encoding="utf-8"))
    return rows


def _elements(out: Path, storey_key: str) -> list[dict[str, Any]]:
    text = (out / "elements" / f"{storey_key}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def two(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Ids]:
    path = tmp_path_factory.mktemp("ifc_two") / "02_SYNTH_UD_ARCH.ifc"
    return path, make_two_buildings_ifc(path)


@pytest.fixture(scope="module")
def two_pkg(two: tuple[Path, Ids], tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("two_pkg") / "qmp"
    build_package([IfcInput(two[0])], out)
    return out


def test_storeys_stay_in_their_building(two: tuple[Path, Ids], two_pkg: Path) -> None:
    ids = two[1]
    rows = _storeys(two_pkg)
    assert [(r["building_name"], r["name"], r["elevation_mm"], r["height_mm"]) for r in rows] == [
        ("Корпус 1", "1 этаж", 0.0, 3000.0),
        ("Корпус 1", "2 этаж", 3000.0, 3000.0),
        ("Корпус 1", "Кровля", 6000.0, None),
        ("Корпус 2", "1 этаж", 0.0, 3000.0),
        ("Корпус 2", "2 этаж", 3000.0, 2950.0),
        ("Корпус 2", "Кровля", 5950.0, None),
    ]
    assert [r["storey_key"] for r in rows] == [_key(ids[b][s]) for b in BUILDINGS for s in LEVELS]
    assert len({r["building_key"] for r in rows}) == 2
    for building in BUILDINGS:
        for level, global_id in ids[building].items():
            names = [e["name"] for e in _elements(two_pkg, _key(global_id))]
            assert names == [f"{building} {level}"]


def test_two_building_package_passes_check_without_height_warnings(two_pkg: Path) -> None:
    report = check_package(two_pkg)
    assert report.ok, [str(issue) for issue in report.errors]
    noisy = {"STOREY_HEIGHT", "EXTRA_FIELDS"}
    assert not [str(issue) for issue in report.warnings if issue.code in noisy]
    assert report.stats["buildings"] == 2
    assert report.stats["storeys"] == 6


def test_other_file_joins_its_building_by_name(two: tuple[Path, Ids], tmp_path: Path) -> None:
    str_ifc = tmp_path / "03_SYNTH_UD_STR.ifc"
    beam = make_k2_str_ifc(str_ifc)
    result = build_package([IfcInput(two[0]), IfcInput(str_ifc)], tmp_path / "qmp")
    assert len(_storeys(result.out_dir)) == 6
    k2_level2 = _key(two[1]["Корпус 2"]["2 этаж"])
    assert beam in {e["id"] for e in _elements(result.out_dir, k2_level2)}
    assert check_package(result.out_dir).ok


def test_one_building_package_keeps_the_old_shape(tmp_path: Path) -> None:
    arch = make_arch_ifc(tmp_path / "00_SYNTH_UD_ARCH.ifc")
    pl = make_pl_ifc(tmp_path / "01_SYNTH_UD_PL.ifc")
    result = build_package([IfcInput(arch.path), IfcInput(pl)], tmp_path / "qmp")
    rows = _storeys(result.out_dir)
    assert [(r["elevation_mm"], r["height_mm"]) for r in rows] == [(0.0, 3000.0), (3000.0, None)]
    assert all(not {"building_key", "building_name"} & r.keys() for r in rows)
    assert "buildings" not in check_package(result.out_dir).stats


def _rewrite_storeys(pkg: Path, rows: list[dict[str, Any]]) -> None:
    """Подменить storeys.json и пересчитать sha256 части и манифеста."""
    data = (json.dumps(rows, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    (pkg / "storeys.json").write_bytes(data)
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    part = next(p for p in manifest["parts"] if p["path"] == "storeys.json")
    part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    manifest["manifest_sha256"] = manifest_digest(manifest)
    (pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_storeys_must_ascend_within_a_building(two_pkg: Path, tmp_path: Path) -> None:
    pkg = Path(shutil.copytree(two_pkg, tmp_path / "qmp"))
    rows = _storeys(pkg)
    rows[1], rows[2] = rows[2], rows[1]  # кровля корпуса 1 раньше его второго этажа
    _rewrite_storeys(pkg, rows)
    assert "STOREY_ORDER" in {issue.code for issue in check_package(pkg).errors}


@pytest.mark.parametrize(
    "patch",
    [{"building_key": "bad key"}, {"building_name": None}, {"building_name": "Другое имя"}],
)
def test_building_fields_are_checked(two_pkg: Path, tmp_path: Path, patch: dict[str, Any]) -> None:
    pkg = Path(shutil.copytree(two_pkg, tmp_path / "qmp"))
    rows = _storeys(pkg)
    rows[1].update(patch)
    rows[1] = {k: v for k, v in rows[1].items() if v is not None or k != "building_name"}
    _rewrite_storeys(pkg, rows)
    assert "STOREY_BUILDING" in {issue.code for issue in check_package(pkg).errors}
