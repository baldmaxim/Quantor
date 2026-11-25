"""Пакет модели QMP v1 (ADR-0053): правила проверки на небольшом пакете в памяти.

База и хранилище не нужны: читатель частей - словарь путь → байты.
"""

from __future__ import annotations

import copy
import hashlib
import json
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from app.services import model_package as qmp

STOREY_A = "StoreyA1"
STOREY_B = "StoreyB2"


def glb(names: list[str], *, extra: dict[str, Any] | None = None) -> bytes:
    """Минимальный GLB: заголовок, JSON-блок с узлами и пустой двоичный блок."""
    doc: dict[str, Any] = {"asset": {"version": "2.0"}, "nodes": [{"name": n} for n in names]}
    doc.update(extra or {})
    body = json.dumps(doc).encode()
    body += b" " * (-len(body) % 4)
    binary = b"\x00" * 4
    total = 12 + 8 + len(body) + 8 + len(binary)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(body), 0x4E4F534A)
        + body
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode()


@dataclass(frozen=True)
class Stat:
    bytes: int
    sha256: str


class MemoryReader:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def stat(self, path: str) -> Stat | None:
        data = self.files.get(path)
        return None if data is None else Stat(len(data), hashlib.sha256(data).hexdigest())

    def head(self, path: str, size: int) -> bytes:
        return self.files[path][:size]

    def read(self, path: str) -> bytes:
        return self.files[path]

    def lines(self, path: str) -> Iterable[str]:
        return self.files[path].decode().splitlines()


def build_package() -> tuple[bytes, dict[str, bytes], dict[str, Any]]:
    storeys = [
        {"storey_key": STOREY_A, "name": "1 этаж", "elevation_mm": 0.0, "height_mm": 3000.0},
        {"storey_key": STOREY_B, "name": "2 этаж", "elevation_mm": 3000.0, "height_mm": None},
    ]
    grids = {
        "source": "IfcGrid",
        "axes": [
            {"tag": "1", "dir": "U", "p0": [0.0, 0.0], "p1": [0.0, 9000.0]},
            {"tag": "А", "dir": "V", "p0": [0.0, 0.0], "p1": [9000.0, 0.0]},
        ],
    }
    files: dict[str, bytes] = {
        "storeys.json": json.dumps(storeys).encode(),
        "grids.json": json.dumps(grids).encode(),
    }
    parts: list[dict[str, Any]] = [
        {"path": "storeys.json", "kind": "storeys"},
        {"path": "grids.json", "kind": "grids"},
    ]
    for key, ids in ((STOREY_A, ["w1", "w2"]), (STOREY_B, ["w3"])):
        geom = f"geometry/{key}__ARCH.glb"
        elems = f"elements/{key}.jsonl"
        foot = f"footprints/{key}.json"
        files[geom] = glb(ids)
        files[elems] = jsonl(
            [
                {
                    "id": i,
                    "category": "wall",
                    "discipline": "ARCH",
                    "storey_key": key,
                    "part": geom,
                    "props": {"Pset.Fire": "EI60"},
                }
                for i in ids
            ]
        )
        files[foot] = json.dumps({"storey_key": key, "z_cut_mm": 1200, "polygons": {}}).encode()
        parts += [
            {"path": geom, "kind": "geometry", "storey_key": key, "discipline": "ARCH"},
            {"path": elems, "kind": "elements", "storey_key": key},
            {"path": foot, "kind": "footprint", "storey_key": key},
        ]
    for part in parts:
        data = files[part["path"]]
        part["bytes"] = len(data)
        part["sha256"] = hashlib.sha256(data).hexdigest()
    manifest: dict[str, Any] = {
        "schema": qmp.SCHEMA,
        "generated_at": "2026-11-16T09:12:00Z",
        "generator": {"name": "test", "version": "0"},
        "source": {
            "kind": "ifc",
            "files": [{"name": "a.ifc", "bytes": 1, "sha256": "0" * 64, "discipline": "ARCH"}],
        },
        "units": {"length": "mm"},
        "frame": {"origin_offset_mm": [0, 0, 159400]},
        "disciplines": [{"code": "ARCH", "elements": 3}],
        "parts": parts,
        "counts": {"storeys": 2, "elements": 3, "triangles": 0, "parts": len(parts)},
    }
    manifest["manifest_sha256"] = qmp.manifest_digest(manifest)
    return json.dumps(manifest).encode(), files, manifest


def set_storeys(files: dict[str, bytes], manifest: dict[str, Any], rows: list[Any]) -> None:
    """Подменить storeys.json и его размер и sha256 в манифесте (манифест не пересчитан)."""
    data = json.dumps(rows, ensure_ascii=False).encode()
    files["storeys.json"] = data
    for part in manifest["parts"]:
        if part["path"] == "storeys.json":
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()


def two_building_package() -> tuple[bytes, dict[str, bytes], dict[str, Any]]:
    """Тот же пакет, этажи в двух корпусах (раздел 4): сначала корпус 1 - этаж B на +3000,
    затем корпус 2 - этаж A на 0. По отметке порядок был бы обратным."""
    _, files, manifest = build_package()
    a, b = json.loads(files["storeys.json"])
    b |= {"building_key": "K1", "building_name": "Корпус 1"}
    a |= {"building_key": "K2", "building_name": "Корпус 2", "height_mm": None}
    set_storeys(files, manifest, [b, a])
    reseal(manifest)
    return json.dumps(manifest).encode(), files, manifest


def run(manifest: dict[str, Any], files: dict[str, bytes]) -> qmp.Report:
    report, _ = qmp.validate_package(json.dumps(manifest).encode(), MemoryReader(files))
    return report


def codes(report: qmp.Report, level: str = "error") -> set[str]:
    return {i.code for i in report.issues if i.level == level}


def reseal(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["manifest_sha256"] = qmp.manifest_digest(manifest)
    return manifest


def test_valid_package_has_no_errors() -> None:
    data, files, _ = build_package()
    report, manifest = qmp.validate_package(data, MemoryReader(files))
    assert report.ok, report.errors
    assert manifest is not None and manifest.counts.elements == 3
    assert not report.warnings


def test_digest_ignores_time_and_own_field() -> None:
    _, _, manifest = build_package()
    other = copy.deepcopy(manifest)
    other["generated_at"] = "2027-01-01T00:00:00Z"
    other["manifest_sha256"] = "f" * 64
    assert qmp.manifest_digest(other) == manifest["manifest_sha256"]
    other["counts"]["triangles"] = 5
    assert qmp.manifest_digest(other) != manifest["manifest_sha256"]


def test_manifest_hash_mismatch_is_an_error() -> None:
    _, files, manifest = build_package()
    manifest["counts"]["triangles"] = 7
    assert "MANIFEST_HASH" in codes(run(manifest, files))


def test_changed_part_is_rejected_by_hash() -> None:
    _, files, manifest = build_package()
    files[f"elements/{STOREY_A}.jsonl"] += b" "
    assert "PART_HASH" in codes(run(manifest, files))


def test_declared_part_must_be_uploaded() -> None:
    _, files, manifest = build_package()
    del files["grids.json"]
    assert "PART_MISSING" in codes(run(manifest, files))


@pytest.mark.parametrize("path", ["../x.json", "/abs.json", "a b.json", "geometry//x.glb", ".hid"])
def test_bad_paths_are_rejected(path: str) -> None:
    _, files, manifest = build_package()
    manifest["parts"][1]["path"] = path
    assert "PART_PATH" in codes(run(reseal(manifest), files))


def test_path_must_fit_the_kind() -> None:
    _, files, manifest = build_package()
    manifest["parts"][1]["path"] = "elements/x.jsonl"
    assert "PART_KIND_PATH" in codes(run(reseal(manifest), files))


def test_two_storey_parts_are_rejected() -> None:
    _, files, manifest = build_package()
    manifest["parts"].append(copy.deepcopy(manifest["parts"][0]))
    manifest["counts"]["parts"] += 1
    assert {"STOREYS_PART", "PART_DUPLICATE"} <= codes(run(reseal(manifest), files))


def test_storeys_must_ascend() -> None:
    _, files, manifest = build_package()
    storeys = json.loads(files["storeys.json"])
    storeys[1]["elevation_mm"] = -5.0
    files["storeys.json"] = json.dumps(storeys).encode()
    data = files["storeys.json"]
    for part in manifest["parts"]:
        if part["path"] == "storeys.json":
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    assert "STOREY_ORDER" in codes(run(reseal(manifest), files))


def test_duplicate_element_ids_are_rejected() -> None:
    _, files, manifest = build_package()
    rows = [json.loads(x) for x in files[f"elements/{STOREY_B}.jsonl"].decode().splitlines()]
    rows[0]["id"] = "w1"
    data = jsonl(rows)
    files[f"elements/{STOREY_B}.jsonl"] = data
    for part in manifest["parts"]:
        if part["path"] == f"elements/{STOREY_B}.jsonl":
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    assert "ELEMENT_ID" in codes(run(reseal(manifest), files))


def test_element_without_glb_node_is_rejected() -> None:
    _, files, manifest = build_package()
    data = glb(["w1"])
    path = f"geometry/{STOREY_A}__ARCH.glb"
    files[path] = data
    for part in manifest["parts"]:
        if part["path"] == path:
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    assert "ELEMENT_NODE" in codes(run(reseal(manifest), files))


@pytest.mark.parametrize(
    "extra",
    [{"textures": [{}]}, {"animations": [{}]}, {"extensionsUsed": ["KHR_draco_mesh_compression"]}],
)
def test_forbidden_glb_content(extra: dict[str, Any]) -> None:
    _, files, manifest = build_package()
    data = glb(["w1", "w2"], extra=extra)
    path = f"geometry/{STOREY_A}__ARCH.glb"
    files[path] = data
    for part in manifest["parts"]:
        if part["path"] == path:
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    assert "GLB_CONTENT" in codes(run(reseal(manifest), files))


def test_not_a_glb() -> None:
    _, files, manifest = build_package()
    data = b"not a glb file at all, just text of some length"
    path = f"geometry/{STOREY_A}__ARCH.glb"
    files[path] = data
    for part in manifest["parts"]:
        if part["path"] == path:
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    assert "GLB_HEADER" in codes(run(reseal(manifest), files))


def test_storeys_ascend_within_each_building() -> None:
    data, files, manifest = two_building_package()
    report, checked = qmp.validate_package(data, MemoryReader(files))
    assert report.ok, report.errors
    assert not report.warnings
    assert checked is not None
    storeys = qmp.check_storeys(files["storeys.json"], qmp.Report())
    assert [(s.building_key, s.building_name) for s in storeys] == [
        ("K1", "Корпус 1"),
        ("K2", "Корпус 2"),
    ]
    rows = json.loads(files["storeys.json"])
    rows[1] |= {"building_key": "K1", "building_name": "Корпус 1"}  # 0 после +3000 в корпусе 1
    set_storeys(files, manifest, rows)
    assert "STOREY_ORDER" in codes(run(reseal(manifest), files))


@pytest.mark.parametrize(
    "patch",
    [{"building_key": "K 1"}, {"building_name": None}, {"building_name": "Другое имя"}],
)
def test_building_fields_are_checked(patch: dict[str, Any]) -> None:
    _, files, manifest = build_package()
    rows = json.loads(files["storeys.json"])
    for row in rows:
        row |= {"building_key": "K1", "building_name": "Корпус 1"}
    rows[1] |= patch
    set_storeys(files, manifest, rows)
    assert "STOREY_BUILDING" in codes(run(reseal(manifest), files))


def test_counts_must_match() -> None:
    _, files, manifest = build_package()
    manifest["counts"]["elements"] = 4
    assert "COUNT_ELEMENTS" in codes(run(reseal(manifest), files))


def test_missing_grids_and_odd_storey_are_warnings_only() -> None:
    _, files, manifest = build_package()
    manifest["parts"] = [p for p in manifest["parts"] if p["kind"] != "grids"]
    manifest["counts"]["parts"] = len(manifest["parts"])
    storeys = json.loads(files["storeys.json"])
    storeys[0]["height_mm"] = 100.0
    data = json.dumps(storeys).encode()
    files["storeys.json"] = data
    for part in manifest["parts"]:
        if part["path"] == "storeys.json":
            part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    report = run(reseal(manifest), files)
    assert report.ok, report.errors
    assert {"NO_GRIDS", "STOREY_HEIGHT"} <= codes(report, "warning")


def test_units_other_than_mm_are_rejected() -> None:
    _, files, manifest = build_package()
    manifest["units"] = {"length": "m"}
    assert "UNITS" in codes(run(reseal(manifest), files))


def test_manifest_schema_and_json_errors() -> None:
    report = qmp.Report()
    assert qmp.parse_manifest(b"{broken", report)[0] is None
    assert qmp.parse_manifest(b"[]", report)[0] is None
    assert qmp.parse_manifest(json.dumps({"schema": "other"}).encode(), report)[0] is None
    assert {"MANIFEST_JSON", "MANIFEST_SCHEMA"} <= {i.code for i in report.issues}


def test_unknown_manifest_fields_are_ignored() -> None:
    _, files, manifest = build_package()
    manifest["extra_note"] = "x"
    report = run(reseal(manifest), files)
    assert report.ok, report.errors
