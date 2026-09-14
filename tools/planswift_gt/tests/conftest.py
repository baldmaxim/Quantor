from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests import synthetic


@pytest.fixture(scope="session")
def project_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synthetic.build(tmp_path_factory.mktemp("template") / "unpacked")


@pytest.fixture
def project(project_template: Path, tmp_path: Path) -> Path:
    # Копия на тест: тесты портят растр и XML, шаблон остаётся нетронутым.
    target = tmp_path / "unpacked"
    shutil.copytree(project_template, target)
    return target
