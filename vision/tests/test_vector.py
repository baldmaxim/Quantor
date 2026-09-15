"""Промт 16: маска → многоугольник с отверстиями, сшивка тайлов, метрики, запуск по листам."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
import torch

from quantor_vision.cli import VISION_ROOT
from quantor_vision.slab.evaluation import write_mask
from quantor_vision.vector.issue_codes import GeometryIssueCode
from quantor_vision.vector.metrics import VectorMetrics, net_area
from quantor_vision.vector.polygonize import (
    PageFrame,
    VectorConfig,
    signed_area,
    vectorize_mask,
)
from quantor_vision.vector.run import VectorizeRefusedError, vectorize_run
from quantor_vision.vector.stitch import TileMask, stitch
from quantor_vision.vector.validity import validate_polygon

SIZE = 64
FRAME = PageFrame(downsample=1, source_width=SIZE, source_height=SIZE)
CONFIG = VectorConfig(min_component_px=4, min_hole_px=1)


def _mask(width: int = SIZE, height: int = SIZE) -> torch.Tensor:
    return torch.zeros(height, width, dtype=torch.bool)


def _area_px(ring: list[list[float]]) -> float:
    return abs(signed_area([(x * SIZE, y * SIZE) for x, y in ring]))


def _net_px(polygon_outer: list[list[float]], holes: list[list[list[float]]]) -> float:
    return _area_px(polygon_outer) - sum(_area_px(hole) for hole in holes)


class TestPolygonize:
    def test_rectangle(self) -> None:
        mask = _mask()
        mask[3:9, 2:12] = True

        vectors = vectorize_mask(mask, FRAME, CONFIG)

        assert len(vectors.polygons) == 1
        polygon = vectors.polygons[0]
        assert polygon.status == "valid"
        assert polygon.holes == []
        assert len(polygon.outer) == 4
        assert polygon.net_area_px == pytest.approx(60)
        assert _area_px(polygon.outer) == pytest.approx(60)
        xs = sorted({x * SIZE for x, _ in polygon.outer})
        assert xs == pytest.approx([2, 12])

    def test_concave_polygon_keeps_every_corner(self) -> None:
        mask = _mask()
        mask[0:4, 0:10] = True
        mask[4:10, 0:4] = True

        polygon = vectorize_mask(mask, FRAME, CONFIG).polygons[0]

        assert len(polygon.outer) == 6
        assert polygon.net_area_px == pytest.approx(64)

    def test_one_and_many_holes(self) -> None:
        mask = _mask()
        mask[10:30, 10:30] = True
        mask[14:20, 14:20] = False
        one = vectorize_mask(mask, FRAME, CONFIG).polygons[0]
        assert len(one.holes) == 1
        assert _net_px(one.outer, one.holes) == pytest.approx(400 - 36)

        mask[22:27, 22:28] = False
        many = vectorize_mask(mask, FRAME, CONFIG).polygons[0]
        assert many.status == "valid"
        assert len(many.holes) == 2
        assert _net_px(many.outer, many.holes) == pytest.approx(400 - 36 - 30)

    def test_hole_one_pixel_from_edge_stays_valid(self) -> None:
        mask = _mask()
        mask[2:22, 2:22] = True
        mask[3:12, 3:12] = False

        polygon = vectorize_mask(mask, FRAME, CONFIG).polygons[0]

        assert polygon.status == "valid"
        assert len(polygon.holes) == 1
        assert _net_px(polygon.outer, polygon.holes) == pytest.approx(400 - 81, rel=0.01)

    def test_gap_touching_outside_at_a_corner_gives_one_pinched_ring(self) -> None:
        # Пустой пиксель (3, 3) касается выреза (2, 2) углом: плита 4-связна, значит фон на
        # диагонали связан, и это не отверстие, а одно кольцо, дважды проходящее вершину (3, 3).
        # Без разведения вершины проверка промта 05 назвала бы его самопересечением.
        mask = _mask()
        mask[2:8, 2:8] = True
        mask[2, 2] = False
        mask[3, 3] = False

        vectors = vectorize_mask(mask, FRAME, CONFIG)

        assert len(vectors.polygons) == 1
        polygon = vectors.polygons[0]
        assert polygon.status == "valid", polygon.issue
        assert polygon.holes == []
        assert _area_px(polygon.outer) == pytest.approx(34, abs=0.1)

    def test_frame_with_open_corner_is_valid(self) -> None:
        # Рамка 3×3 без центра и без угла (4, 4): центр выходит наружу через угол.
        mask = _mask()
        mask[2:5, 2:5] = True
        mask[3, 3] = False
        mask[4, 4] = False

        vectors = vectorize_mask(mask, FRAME, CONFIG)

        assert len(vectors.polygons) == 1
        assert vectors.polygons[0].status == "valid", vectors.polygons[0].issue
        assert vectors.polygons[0].net_area_px == pytest.approx(7, abs=0.1)

    def test_corner_touching_components_are_separate_polygons(self) -> None:
        mask = _mask()
        mask[2:6, 2:6] = True
        mask[6:10, 6:10] = True

        vectors = vectorize_mask(mask, FRAME, CONFIG)

        assert len(vectors.polygons) == 2
        assert all(polygon.status == "valid" for polygon in vectors.polygons)

    def test_noisy_island_is_dropped_and_counted(self) -> None:
        mask = _mask()
        mask[10:30, 10:30] = True
        mask[50:52, 50:52] = True
        config = VectorConfig(min_component_px=16, min_hole_px=1)

        vectors = vectorize_mask(mask, FRAME, config)

        assert len(vectors.polygons) == 1
        assert vectors.dropped_components == 1

    def test_small_hole_is_filled_and_counted(self) -> None:
        mask = _mask()
        mask[10:30, 10:30] = True
        mask[15, 15] = False
        config = VectorConfig(min_component_px=16, min_hole_px=4)

        vectors = vectorize_mask(mask, FRAME, config)

        assert vectors.polygons[0].holes == []
        assert vectors.filled_holes == 1

    def test_simplification_bounds_area_change(self) -> None:
        mask = _mask()
        yy, xx = torch.meshgrid(torch.arange(SIZE), torch.arange(SIZE), indexing="ij")
        mask[((xx - 32) ** 2 + (yy - 32) ** 2) <= 20**2] = True
        exact = float(mask.sum())
        config = VectorConfig(min_component_px=4, min_hole_px=1, max_area_change_ratio=0.05)

        polygon = vectorize_mask(mask, FRAME, config).polygons[0]

        assert polygon.status == "valid"
        assert polygon.output_vertices < polygon.lattice_vertices
        assert abs(polygon.net_area_px - exact) <= config.max_area_change_ratio * exact

    @pytest.mark.parametrize("tolerance", [1.5, 4.0, 12.0])
    def test_coarse_tolerance_never_returns_invalid_geometry(self, tolerance: float) -> None:
        # Тонкие перемычки между отверстиями и краем: грубое упрощение сводит кольца вместе, и
        # тогда допуск откатывается, пока контур не станет действительным.
        mask = _mask()
        mask[4:40, 4:40] = True
        mask[5:20, 5:39] = False
        mask[21:39, 5:39] = False
        config = VectorConfig(
            min_component_px=4,
            min_hole_px=1,
            simplify_tolerance_px=tolerance,
            max_area_change_ratio=1.0,
        )

        polygon = vectorize_mask(mask, FRAME, config).polygons[0]

        assert polygon.status == "valid", polygon.issue
        assert validate_polygon(polygon.outer, polygon.holes) is None

    def test_coordinates_are_normalized_by_page_frame(self) -> None:
        mask = _mask(40, 20)
        mask[0:20, 0:40] = True
        frame = PageFrame(downsample=2, source_width=80, source_height=40)

        polygon = vectorize_mask(mask, frame, CONFIG).polygons[0]

        assert {tuple(point) for point in polygon.outer} == {
            (0.0, 0.0),
            (1.0, 0.0),
            (1.0, 1.0),
            (0.0, 1.0),
        }


def _write(path: Path, mask: torch.Tensor) -> TileMask:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_mask(path, mask.to(torch.uint8))
    return TileMask(path, (0, 0), mask.shape[1], mask.shape[0])


class TestStitch:
    def test_polygon_crossing_tile_boundary_is_one_polygon(self, tmp_path: Path) -> None:
        page = _mask(48, 24)
        page[5:15, 10:40] = True
        left = _write(tmp_path / "a.png", page[:, 0:32].clone())
        right_mask = page[:, 16:48].clone()
        right = TileMask(_write(tmp_path / "b.png", right_mask).path, (16, 0), 32, 24)

        stitched, uncovered = stitch([left, right], 48, 24, 0.5)

        assert uncovered == 0
        assert torch.equal(stitched, page)
        polygons = vectorize_mask(stitched, FRAME, CONFIG).polygons
        assert len(polygons) == 1
        assert polygons[0].net_area_px == pytest.approx(300)

    def test_duplicate_predictions_in_overlap_do_not_double_area(self, tmp_path: Path) -> None:
        tile = _mask(32, 24)
        tile[5:15, 18:30] = True
        first = _write(tmp_path / "a.png", tile)
        second = TileMask(_write(tmp_path / "b.png", tile.roll(-16, dims=1)).path, (16, 0), 32, 24)

        stitched, _ = stitch([first, second], 48, 24, 0.5)

        assert int(stitched.sum()) == 120
        assert stitch([second, first], 48, 24, 0.5)[0].equal(stitched)

    def test_tie_in_overlap_goes_to_slab_at_half_threshold(self, tmp_path: Path) -> None:
        yes = _mask(32, 24)
        yes[:, :] = True
        first = _write(tmp_path / "a.png", yes)
        second = TileMask(_write(tmp_path / "b.png", _mask(32, 24)).path, (16, 0), 32, 24)

        stitched, uncovered = stitch([first, second], 48, 24, 0.5)

        assert uncovered == 0
        assert bool(stitched[0, 20])
        assert not bool(stitched[0, 40])
        assert not bool(stitch([first, second], 48, 24, 0.75)[0][0, 20])


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class TestMetrics:
    def test_perfect_prediction(self) -> None:
        polygon = [_rect(10, 10, 30, 30), _rect(14, 14, 24, 24)]
        metrics = VectorMetrics(VectorConfig(min_hole_px=1, metric_stride_px=1))

        page = metrics.add_page(
            [polygon],
            [polygon],
            page_area_px=SIZE * SIZE,
            invalid_codes=[],
            lattice_vertices=8,
            output_vertices=8,
        )

        summary = metrics.summary()
        assert page["area_error"] == 0
        assert summary["polygon_recall"] == 1
        assert summary["polygon_precision"] == 1
        assert summary["hole_recall"] == 1
        assert summary["boundary_f1"] == 1
        assert summary["invalid_rate"] == 0

    def test_filled_hole_is_missed_and_counted_in_area(self) -> None:
        truth = [_rect(10, 10, 30, 30), _rect(14, 14, 24, 24)]
        metrics = VectorMetrics(VectorConfig(min_hole_px=1, metric_stride_px=1))

        page = metrics.add_page(
            [[_rect(10, 10, 30, 30)]],
            [truth],
            page_area_px=SIZE * SIZE,
            invalid_codes=["self_intersection"],
            lattice_vertices=4,
            output_vertices=4,
        )

        summary = metrics.summary()
        assert page["area_error"] == pytest.approx(100 / 300)
        assert net_area(truth) == 300
        assert summary["hole_recall"] == 0
        assert summary["polygon_recall"] == 1
        assert summary["invalid_rate"] == 0.5
        assert summary["invalid_codes"] == {"self_intersection": 1}

    def test_page_without_slab_reports_false_area(self) -> None:
        metrics = VectorMetrics(VectorConfig())

        page = metrics.add_page(
            [[_rect(0, 0, 8, 8)]],
            [],
            page_area_px=SIZE * SIZE,
            invalid_codes=[],
            lattice_vertices=4,
            output_vertices=4,
        )

        assert page["area_error"] is None
        assert page["false_area_of_page"] == pytest.approx(64 / (SIZE * SIZE))
        assert metrics.summary()["pages_without_slab"] == 1


class TestValidityParity:
    def test_copy_matches_portal_validator(self) -> None:
        portal = VISION_ROOT.parent / "apps" / "api" / "app" / "services" / "geometry"
        original = (portal / "validity.py").read_text(encoding="utf-8").replace("\r\n", "\n")
        copy = (
            (VISION_ROOT / "quantor_vision" / "vector" / "validity.py")
            .read_text(encoding="utf-8")
            .replace("\r\n", "\n")
        )
        assert copy == original.replace(
            "from app.domain import GeometryIssueCode",
            "from quantor_vision.vector.issue_codes import GeometryIssueCode",
        )

    def test_issue_codes_match_portal(self) -> None:
        domain = (VISION_ROOT.parent / "apps" / "api" / "app" / "domain.py").read_text(
            encoding="utf-8"
        )
        block = domain.split("class GeometryIssueCode(StrEnum):", 1)[1].split("\nclass ", 1)[0]
        portal = dict(re.findall(r"^\s+([A-Z_]+) = \"([a-z_]+)\"", block, flags=re.MULTILINE))
        assert portal == {code.name: code.value for code in GeometryIssueCode}


def _synthetic_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    build = tmp_path / "build"
    run = tmp_path / "run"
    truth_dir = tmp_path / "gt" / "p1"
    rows: list[dict[str, object]] = []
    manifest: list[tuple[str, dict[str, str]]] = []
    for split, guid in (("val", "page-val"), ("test", "page-test")):
        tile = _mask(32, 32)
        tile[4:28, 4:28] = True
        tile[10:16, 10:16] = False
        path = run / "predictions" / split / f"{split}-tile.png"
        _write(path, tile)
        manifest.append((split, {"tile_id": f"{split}-tile", "sha256": _sha(path)}))
        rows.append(
            {
                "tile_id": f"{split}-tile",
                "project_key": "p1",
                "page_guid": guid,
                "split": split,
                "tasks": ["slab"],
                "transform": {
                    "downsample": 2,
                    "source_size": [64, 64],
                    "working_size": [32, 32],
                    "origin_working_px": [0, 0],
                    "valid_size": [32, 32],
                },
            }
        )
    build.mkdir()
    (build / "tiles.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    for split in ("val", "test"):
        (run / f"{split}-predictions.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for name, item in manifest if name == split),
            encoding="utf-8",
        )
    truth_dir.mkdir(parents=True)
    corners = [[0.125, 0.125], [0.875, 0.125], [0.875, 0.875], [0.125, 0.875]]
    annotations: list[dict[str, object]] = []
    for guid in ("page-val", "page-test"):
        annotations.append(
            {
                "page": {"page_guid": guid},
                "annotation": {
                    "id": f"{guid}-a",
                    "kind": "polygon",
                    "label_raw": "Плита",
                    "points_normalized": corners,
                    "points_source_px": [guid, 1],
                },
            }
        )
    (truth_dir / "annotations.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in annotations), encoding="utf-8"
    )
    config = tmp_path / "build-v1.json"
    config.write_text(
        json.dumps(
            {
                "datasets": [
                    {"project_key": "p1", "dataset_dir": str(truth_dir), "tasks": ["slab"]}
                ],
                "targets": {"slab": {"kinds": ["polygon"], "labels": ["Плита"]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return build, run, config


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestRun:
    def test_val_then_test_once(self, tmp_path: Path) -> None:
        build, run, build_config = _synthetic_run(tmp_path)
        config = VectorConfig(min_component_px=4, min_hole_px=1)

        with pytest.raises(VectorizeRefusedError):
            vectorize_run(build, run, split="test", build_config=build_config, config=config)

        val = vectorize_run(build, run, split="val", build_config=build_config, config=config)
        summary = val["summary"]
        assert isinstance(summary, dict)
        assert summary["pages_with_slab"] == 1
        assert summary["polygon_recall"] == 1
        assert summary["page_area_error_median"] == pytest.approx(36 / 576)

        page_file = run / "vector" / config.sha256()[:12] / "val" / "p1__page-val.json"
        page = json.loads(page_file.read_text(encoding="utf-8"))
        assert page["coordinates"] == "sheet_normalized_top_left"
        assert page["evidence"][0]["mask_sha256"] == _sha(
            run / "predictions" / "val" / "val-tile.png"
        )
        assert page["polygons"][0]["status"] == "valid"

        vectorize_run(build, run, split="test", build_config=build_config, config=config)
        with pytest.raises(VectorizeRefusedError):
            vectorize_run(build, run, split="test", build_config=build_config, config=config)
        repeat = vectorize_run(
            build,
            run,
            split="test",
            build_config=build_config,
            config=config,
            new_experiment="проверка повтора",
        )
        assert "test-metrics-" in str(repeat["metrics"])

    def test_changed_mask_is_refused(self, tmp_path: Path) -> None:
        build, run, build_config = _synthetic_run(tmp_path)
        _write(run / "predictions" / "val" / "val-tile.png", _mask(32, 32))

        with pytest.raises(VectorizeRefusedError):
            vectorize_run(build, run, split="val", build_config=build_config, config=CONFIG)

    def test_unknown_override_is_refused(self) -> None:
        with pytest.raises(ValueError):
            VectorConfig.with_overrides({"threshold": "0.4"})
        assert VectorConfig.with_overrides({"min_hole_px": "8"}).min_hole_px == 8
