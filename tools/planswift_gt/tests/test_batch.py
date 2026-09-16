"""Пакетный импорт (Р-9): несколько проектов в архиве, повторный запуск, одинаковые проекты."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from planswift_gt.batch import import_project, project_roots, shared_pages
from planswift_gt.buildconfig import TargetConfig
from planswift_gt.parser import ProjectRejectedError

ROOT_NAME = "Синтетика кладка"
TARGETS = {
    "slab": TargetConfig(kinds=("polygon",), label_patterns=("^Плита",)),
    "wall": TargetConfig(kinds=("polyline",), label_patterns=("^Стены",)),
}


class TestProjectRoots:
    def test_single_project_has_empty_suffix(self, project: Path) -> None:
        assert project_roots(project) == [("", project / ROOT_NAME)]

    def test_archive_with_several_projects_gives_one_per_project(
        self, project: Path, tmp_path: Path
    ) -> None:
        unpacked = tmp_path / "complex"
        shutil.copytree(project / ROOT_NAME, unpacked / "Корпус 1")
        shutil.copytree(project / ROOT_NAME, unpacked / "Корпус 2")
        (unpacked / "readme").mkdir()

        roots = project_roots(unpacked)

        assert roots == [
            ("korpus_1", unpacked / "Корпус 1"),
            ("korpus_2", unpacked / "Корпус 2"),
        ]

    def test_directory_without_projects_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "empty").mkdir()
        with pytest.raises(ProjectRejectedError):
            project_roots(tmp_path / "empty")


class TestImportProject:
    def test_second_run_reuses_the_written_dataset(self, project: Path, tmp_path: Path) -> None:
        root = project / ROOT_NAME
        dataset = tmp_path / "gt" / "synthetic"

        first = import_project("synthetic", root, dataset, TARGETS)
        second = import_project("synthetic", root, dataset, TARGETS)
        forced = import_project("synthetic", root, dataset, TARGETS, force=True)

        assert (first["reused"], second["reused"], forced["reused"]) == (False, True, False)
        assert first["task_annotations"] == {"slab": 1, "wall": 2}
        assert second["task_annotations"] == first["task_annotations"]
        assert first["page_formats"] == ["tiff"]
        assert (dataset / "import-state.json").is_file()


class TestSharedPages:
    def test_identical_projects_and_shared_rasters_are_reported(self) -> None:
        projects: list[dict[str, object]] = [
            {"project_key": "seliger_k", "source_fingerprint": "s1", "page_images": ["a", "b"]},
            {"project_key": "seliger_h", "source_fingerprint": "s1", "page_images": ["a", "b"]},
            {"project_key": "polkovaya_s3", "source_fingerprint": "s2", "page_images": ["c", "d"]},
            {"project_key": "polkovaya_all", "source_fingerprint": "s3", "page_images": ["d", "e"]},
            {"project_key": "doors", "status": "rejected"},
        ]

        identical, shared = shared_pages(projects)

        assert identical == [["seliger_h", "seliger_k"]]
        assert shared == {"polkovaya_all": 1, "polkovaya_s3": 1, "seliger_h": 2, "seliger_k": 2}
