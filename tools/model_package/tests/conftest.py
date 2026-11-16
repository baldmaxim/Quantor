"""Общие фикстуры: синтетические IFC собираются один раз на сеанс тестов."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synth_ifc import SynthModel, make_arch_ifc, make_pl_ifc


@pytest.fixture(scope="session")
def arch(tmp_path_factory: pytest.TempPathFactory) -> SynthModel:
    return make_arch_ifc(tmp_path_factory.mktemp("ifc") / "SYNTH_UD_ARCH_1 (20261116).ifc")


@pytest.fixture(scope="session")
def pl_ifc(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_pl_ifc(tmp_path_factory.mktemp("ifc_pl") / "SYNTH_UD_PL.ifc")
