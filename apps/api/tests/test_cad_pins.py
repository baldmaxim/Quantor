"""Закрепление движка и генераторов CAD: pins.json совпадает с исходниками и MANIFEST.json."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app.core.config import Settings
from app.services import cad as cad_service
from app.services import cad_pins
from app.services.cad_pins import GeneratorName

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PINS_PATH = _REPO_ROOT / "tools" / "cad_engine" / "pins.json"
# Исходник движка: `CAD_ENGINE_SRC` или соседний с Quantor каталог `CAD_engine`.
ENGINE_SRC = Path(os.environ.get("CAD_ENGINE_SRC") or _REPO_ROOT.parent / "CAD_engine")
_VERSION = re.compile(r'^GENERATOR_VERSION\s*(?::[^=]+)?=\s*"([^"]+)"', re.M)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _load_tool(name: str) -> ModuleType:
    path = _REPO_ROOT / "tools" / "cad_engine" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"quantor_test_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_pins() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_PINS_PATH.read_text(encoding="utf-8"))
    return data


def _check_pin(name: GeneratorName) -> None:
    root = ENGINE_SRC / "generators" / name
    try:
        available = root.is_dir()
    except PermissionError:
        available = False
    if not available:
        pytest.skip(f"нет исходника движка {root} (задайте CAD_ENGINE_SRC)")
    pin = cad_pins.load_generator_pin(Settings(), name)
    found = _VERSION.search((root / name / "version.py").read_text("utf-8"))
    assert found is not None and found.group(1) == pin.generator_version
    raw = (root / pin.params_relpath.relative_to(name)).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pin.params_sha256
    assert cad_service.params_sha256(json.loads(raw)) == pin.params_canonical_sha256


def _build_engine_zip(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Синтетический zip-архив движка с MANIFEST.json и согласованный словарь pins."""
    worker_rel = "worker.py"
    worker_bytes = b"print('ok')\n"
    worker_sha = hashlib.sha256(worker_bytes).hexdigest()
    snapshot_sha = hashlib.sha256(b"snapshot-demo").hexdigest()
    version = f"2026.11.25+{snapshot_sha[:12]}"
    manifest = {
        "version": version,
        "source_snapshot_sha256": snapshot_sha,
        "files": [{"file": worker_rel, "sha256": worker_sha}],
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    archive_rel = f"engine/dist/Quantor_CAD_source_2026.11.25_{snapshot_sha[:12]}.zip"
    archive_path = tmp_path / archive_rel
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in ((worker_rel, worker_bytes), ("MANIFEST.json", manifest_bytes)):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(info, raw)
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    pins: dict[str, Any] = {
        "schema": "quantor.cad_engine.pins.v1",
        "runner_version": "0.1.0",
        "engine": {
            "name": "quantor-cad-legacy-ar",
            "version": version,
            "archive_name": archive_path.name,
            "archive_path": archive_rel,
            "archive_sha256": archive_sha,
            "manifest_sha256": manifest_sha,
            "source_snapshot_sha256": snapshot_sha,
            "archive_entries": 2,
            "max_unpacked_bytes": 1024 * 1024,
            "worker": worker_rel,
        },
    }
    return archive_path, pins


def test_cad_mep_pin_matches_the_engine_sources() -> None:
    _check_pin("cad_mep")


def test_cad_walls_pin_matches_the_engine_sources() -> None:
    _check_pin("cad_walls")


def test_engine_constants_match_the_pin() -> None:
    """Исполнитель сверяет манифест движка с константами cad.py — они равны pins.json."""
    engine = _load_pins()["engine"]
    assert engine["version"] == cad_service.ENGINE_VERSION
    assert engine["archive_sha256"] == cad_service.ENGINE_ARCHIVE_SHA256
    for key in ("archive_sha256", "manifest_sha256", "source_snapshot_sha256"):
        assert _SHA256.match(engine[key]), f"pins.engine.{key} не является sha256"
    # Префикс source_snapshot_sha256 входит в версию и имя архива (защита от рассинхрона b96238a).
    snapshot_prefix = engine["source_snapshot_sha256"][:12]
    assert engine["version"].endswith(f"+{snapshot_prefix}")
    assert engine["archive_name"].endswith(f"_{snapshot_prefix}.zip")
    assert engine["archive_path"].endswith(f"/{engine['archive_name']}")


def test_engine_archive_manifest_matches_the_pin() -> None:
    """pins.engine.{version,source_snapshot_sha256,manifest_sha256} совпадают с MANIFEST.json."""
    pins = _load_pins()
    archive = ENGINE_SRC / pins["engine"]["archive_path"]
    try:
        available = archive.is_file()
    except PermissionError:
        available = False
    if not available:
        pytest.skip(f"нет архива движка {archive} (задайте CAD_ENGINE_SRC)")
    pin_engine = _load_tool("pin_engine")
    runner = _load_tool("quantor_cad_runner")
    pin_engine.verify_archive(ENGINE_SRC, pins)
    verified = runner.verify_archive(archive, pins, expected_sha=cad_service.ENGINE_ARCHIVE_SHA256)
    assert verified["version"] == pins["engine"]["version"]
    assert verified["manifest_sha256"] == pins["engine"]["manifest_sha256"]
    assert verified["source_snapshot_sha256"] == pins["engine"]["source_snapshot_sha256"]


def test_pin_archive_verification_accepts_consistent_manifest(tmp_path: Path) -> None:
    archive, pins = _build_engine_zip(tmp_path)
    pin_engine = _load_tool("pin_engine")
    runner = _load_tool("quantor_cad_runner")
    pin_engine.verify_archive(tmp_path, pins)
    verified = runner.verify_archive(archive, pins, expected_sha=pins["engine"]["archive_sha256"])
    assert verified["source_snapshot_sha256"] == pins["engine"]["source_snapshot_sha256"]


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_code"),
    [
        ("source_snapshot_sha256", "0" * 64, "manifest_invalid"),
        ("manifest_sha256", "0" * 64, "manifest_sha_mismatch"),
        ("version", "2026.11.25+000000000000", "manifest_invalid"),
        ("archive_entries", 999, "archive_invalid"),
        ("archive_sha256", "0" * 64, "archive_sha_mismatch"),
    ],
)
def test_pin_archive_verification_rejects_manifest_mismatch(
    tmp_path: Path, field: str, bad_value: object, expected_code: str
) -> None:
    """Расхождение pins.json с MANIFEST.json или архивом ловится и pin_engine, и runner."""
    archive, pins = _build_engine_zip(tmp_path)
    pins["engine"][field] = bad_value
    pin_engine = _load_tool("pin_engine")
    runner = _load_tool("quantor_cad_runner")
    with pytest.raises(pin_engine.PinError):
        pin_engine.verify_archive(tmp_path, pins)
    with pytest.raises(runner.RunnerError) as exc_info:
        runner.verify_archive(archive, pins)
    assert exc_info.value.code == expected_code
