"""Самопроверка: испорченный пакет даёт понятные ошибки."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from synth_ifc import SynthModel

from model_package.qmp_build import IfcInput, build_package
from model_package.qmp_check import check_package, manifest_digest


@pytest.fixture(scope="module")
def clean(arch: SynthModel, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("clean") / "qmp"
    build_package([IfcInput(arch.path)], out)
    return out


def _copy(clean: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "qmp"
    shutil.copytree(clean, dst)
    return dst


def _rehash(pkg: Path, edit: Callable[[dict[str, Any]], None] | None = None) -> None:
    """Пересчитать sha256 частей и манифеста после правки, чтобы проверить одно правило."""
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    for part in manifest["parts"]:
        data = (pkg / part["path"]).read_bytes()
        part["bytes"], part["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    if edit:
        edit(manifest)
    manifest["manifest_sha256"] = manifest_digest(manifest)
    (pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _codes(pkg: Path) -> set[str]:
    return {i.code for i in check_package(pkg).errors}


def test_tampered_part(clean: Path, tmp_path: Path) -> None:
    pkg = _copy(clean, tmp_path)
    glb = next((pkg / "geometry").glob("*.glb"))
    data = bytearray(glb.read_bytes())
    data[-1] ^= 0xFF
    glb.write_bytes(bytes(data))
    assert "PART_HASH" in _codes(pkg)


def test_manifest_hash_and_generated_at(clean: Path, tmp_path: Path) -> None:
    pkg = _copy(clean, tmp_path)
    manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    manifest["generated_at"] = "2030-01-01T00:00:00Z"
    (pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert check_package(pkg).ok  # время выгрузки в хеш не входит
    manifest["counts"]["triangles"] += 1
    (pkg / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    assert "MANIFEST_HASH" in _codes(pkg)


def test_element_without_node_and_bad_storey_order(clean: Path, tmp_path: Path) -> None:
    pkg = _copy(clean, tmp_path)
    path = next((pkg / "elements").glob("*.jsonl"))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    with_part = next(r for r in rows if r["part"])
    with_part["id"] = "NoSuchNode$1"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    storeys = json.loads((pkg / "storeys.json").read_text(encoding="utf-8"))
    (pkg / "storeys.json").write_text(json.dumps(storeys[::-1], ensure_ascii=False), "utf-8")
    _rehash(pkg)
    codes = _codes(pkg)
    assert {"ELEMENT_NODE", "STOREY_ORDER"} <= codes


def test_bad_paths_and_missing_fields(clean: Path, tmp_path: Path) -> None:
    pkg = _copy(clean, tmp_path)

    def edit(m: dict[str, Any]) -> None:
        m["parts"][0]["path"] = "../escape.json"
        del m["counts"]["triangles"]

    _rehash(pkg, edit)
    codes = _codes(pkg)
    assert {"PART_PATH", "SCHEMA"} <= codes


def test_not_a_glb(clean: Path, tmp_path: Path) -> None:
    pkg = _copy(clean, tmp_path)
    glb = next((pkg / "geometry").glob("*.glb"))
    glb.write_bytes(b"not a glb at all, just text bytes")
    _rehash(pkg)
    assert "GLB" in _codes(pkg)


def test_missing_manifest(tmp_path: Path) -> None:
    assert "MANIFEST" in _codes(tmp_path)
