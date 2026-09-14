from __future__ import annotations

from pathlib import Path

import pytest

from tests import synthetic


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return synthetic.build(tmp_path / "unpacked")
