"""Разбор синтетического проекта и формат planswift-gt-v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planswift_gt.cli import main
from planswift_gt.manifest import ANNOTATIONS, MANIFEST, compare_expectations, validate
from planswift_gt.parser import Annotation, ParseResult, parse_project
from tests.synthetic import GUIDS, HEIGHT, PAGE_GUID, WIDTH


def _by_id(result: ParseResult) -> dict[str, Annotation]:
    return {item.id: item for item in result.annotations}


class TestParse:
    def test_accepted_kinds_and_objects(self, project: Path) -> None:
        result = parse_project(project)
        found = _by_id(result)

        assert set(found) == {GUIDS.linear, GUIDS.duplicate, GUIDS.area, GUIDS.hole, GUIDS.count}
        assert found[GUIDS.linear].kind == "polyline"
        assert found[GUIDS.area].kind == "polygon"
        assert found[GUIDS.hole].kind == "polygon_hole"
        # Секция счёта с тремя точками — три объекта, а не один.
        assert found[GUIDS.count].object_count == 3

    def test_every_bad_section_is_rejected_with_a_reason(self, project: Path) -> None:
        reasons = {item.guid: item.reason for item in parse_project(project).rejections}

        assert reasons[GUIDS.placeholder_area] == "placeholder_coordinates"
        assert reasons[GUIDS.orphan_hole] == "hole_parent_rejected"
        assert reasons[GUIDS.empty_count] == "no_points"
        assert reasons[GUIDS.outside] == "outside_image"
        assert "forbidden_dtd" in reasons.values()

    def test_hole_inherits_page_and_parent(self, project: Path) -> None:
        hole = _by_id(parse_project(project))[GUIDS.hole]

        assert hole.page_guid == PAGE_GUID
        assert hole.page_guid_inherited is True
        assert hole.parent_annotation_id == GUIDS.area

    def test_points_normalized_against_the_source_raster(self, project: Path) -> None:
        line = _by_id(parse_project(project))[GUIDS.linear]

        assert line.points_source_px == [[100.0, 100.0], [500.5, 100.0], [900.0, 300.0]]
        assert line.points_normalized == [
            [100 / WIDTH, 100 / HEIGHT],
            [500.5 / WIDTH, 100 / HEIGHT],
            [900 / WIDTH, 300 / HEIGHT],
        ]
        # Точки дуги сохраняются в порядке и с исходным типом.
        assert line.point_types == ["Normal", "ArcChild", "Arc"]

    def test_semantic_names_come_from_xml_not_truncated_directories(self, project: Path) -> None:
        result = parse_project(project)
        line = _by_id(result)[GUIDS.linear]

        assert line.label_raw == "Стены [толщина 250]"
        assert line.label_path == ["Кладка", "Стены [толщина 250]"]
        assert result.pages[0].name == "Лист 1 — план типового этажа"

    def test_scale_is_kept_as_raw_evidence(self, project: Path) -> None:
        page = parse_project(project).pages[0]

        assert (page.scale_x, page.scale_y, page.scale_units) == (
            "102,381983542659",
            "102,342626577818",
            "M",
        )

    def test_encoding_fallback_is_counted(self, project: Path) -> None:
        counters = parse_project(project).counters

        # Кириллица есть в пяти файлах: корень, лист, три позиции. Секции — ASCII и честный UTF-8.
        assert counters["xml_cp1251_fallback"] == 5
        assert counters["xml_encoding_utf-8"] >= 1


class TestFormat:
    def _convert(self, project: Path, out: Path) -> None:
        code = main(
            [
                "convert",
                str(project),
                "--project-key",
                "synthetic",
                "--out",
                str(out),
                "--allow-inside-repo",
            ]
        )
        assert code == 0

    def test_convert_then_validate(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "gt"
        self._convert(project, out)

        root = project / "Синтетика кладка"
        assert validate(out, source_root=root) == []
        manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
        assert manifest["format"] == "planswift-gt-v1"
        assert manifest["summary"]["annotations_by_kind"] == {
            "count": 1,
            "polygon": 1,
            "polygon_hole": 1,
            "polyline": 2,
        }

    def test_repeated_import_is_byte_identical(self, project: Path, tmp_path: Path) -> None:
        self._convert(project, tmp_path / "first")
        self._convert(project, tmp_path / "second")

        for name in ("manifest.json", "pages.jsonl", "annotations.jsonl", "rejections.jsonl"):
            assert (tmp_path / "first" / name).read_bytes() == (
                tmp_path / "second" / name
            ).read_bytes()

    def test_annotation_line_follows_the_contract(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "gt"
        self._convert(project, out)
        rows = [
            json.loads(line)
            for line in (out / ANNOTATIONS).read_text(encoding="utf-8").splitlines()
        ]
        hole = next(row for row in rows if row["annotation"]["kind"] == "polygon_hole")

        assert hole["source"] == "planswift"
        assert hole["page"] == {
            "page_guid": PAGE_GUID,
            "image_sha256": hole["page"]["image_sha256"],
            "width_px": WIDTH,
            "height_px": HEIGHT,
        }
        assert hole["annotation"]["parent_annotation_id"] == GUIDS.area
        assert len(hole["annotation"]["source_xml_sha256"]) == 64

    def test_tampered_output_fails_validation(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "gt"
        self._convert(project, out)
        path = out / ANNOTATIONS
        path.write_text(
            path.read_text(encoding="utf-8").replace("0.05", "1.05", 1), encoding="utf-8"
        )

        problems = validate(out)
        assert any("SHA-256" in problem.message for problem in problems)

    def test_changed_raster_is_detected(self, project: Path, tmp_path: Path) -> None:
        out = tmp_path / "gt"
        self._convert(project, out)
        root = project / "Синтетика кладка"
        raster = next(root.rglob("*.tiff"))
        raster.write_bytes(raster.read_bytes() + b"\0")

        assert any("растра" in problem.message for problem in validate(out, source_root=root))

    def test_refuses_to_write_inside_a_git_worktree(self, project: Path, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)

        code = main(["convert", str(project), "--project-key", "k", "--out", str(repo / "gt")])

        assert code == 2
        assert not (repo / "gt").exists()


class TestExpectations:
    @pytest.mark.parametrize(("actual", "within"), [(2540, True), (2400, False)])
    def test_expectations_compare_with_tolerance(self, actual: int, within: bool) -> None:
        rows = compare_expectations(
            {"pages": 16, "annotations_by_kind": {"polyline": actual}},
            {
                "summary:pages": {"expected": 16},
                "annotations:polyline": {"expected": 2540, "tolerance": 50},
            },
        )

        assert {row.metric: row.within for row in rows} == {
            "annotations:polyline": within,
            "summary:pages": True,
        }
