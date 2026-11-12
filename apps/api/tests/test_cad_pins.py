"""Закрепление генераторов CAD: pins.json репозитория совпадает с исходниками движка."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from app.services import cad as cad_service
from app.services import cad_pins
from app.services.cad_pins import GeneratorName
from tests.conftest import clean_settings

# Исходник движка: `CAD_ENGINE_SRC` или соседний с Quantor каталог `CAD_engine`.
ENGINE_SRC = Path(
    os.environ.get("CAD_ENGINE_SRC") or Path(__file__).resolve().parents[4] / "CAD_engine"
)
_VERSION = re.compile(r'^GENERATOR_VERSION\s*(?::[^=]+)?=\s*"([^"]+)"', re.M)


def _check_pin(name: GeneratorName) -> None:
    root = ENGINE_SRC / "generators" / name
    if not root.is_dir():
        pytest.skip(f"нет исходника движка {root} (задайте CAD_ENGINE_SRC)")
    pin = cad_pins.load_generator_pin(clean_settings(), name)
    found = _VERSION.search((root / name / "version.py").read_text("utf-8"))
    assert found is not None and found.group(1) == pin.generator_version
    raw = (root / pin.params_relpath.relative_to(name)).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pin.params_sha256
    assert cad_service.params_sha256(json.loads(raw)) == pin.params_canonical_sha256


def test_cad_mep_pin_matches_the_engine_sources() -> None:
    _check_pin("cad_mep")


def test_cad_walls_pin_matches_the_engine_sources() -> None:
    _check_pin("cad_walls")


def test_engine_constants_match_the_pin() -> None:
    """Исполнитель сверяет манифест движка с константами cad.py — они равны pins.json."""
    pins = Path(__file__).resolve().parents[3] / "tools" / "cad_engine" / "pins.json"
    engine = json.loads(pins.read_text(encoding="utf-8"))["engine"]
    assert engine["version"] == cad_service.ENGINE_VERSION
    assert engine["archive_sha256"] == cad_service.ENGINE_ARCHIVE_SHA256
