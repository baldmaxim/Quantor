"""Сборщик датасета: цели, тайлы и преобразования, разбиение и утечка (промт 08)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from planswift_gt import build as dataset_build
from planswift_gt.buildconfig import BuildConfig, DatasetRef, TargetConfig
from planswift_gt.cli import main
from planswift_gt.geometry2d import (
    centerline_target,
    fill_rings,
    hamming,
    interior_point,
    phash,
    simplify,
)
from planswift_gt.splits import PageInfo, SplitFrozenError, assign, clusters, freeze
from planswift_gt.tiles import TileTransform, crop, grid_origins

ROOT_NAME = "Синтетика кладка"


class TestTargets:
    def test_slab_mask_keeps_the_hole_empty(self) -> None:
        width, height = 40, 40
        mask = bytearray(width * height)
        outer = [(5.0, 5.0), (35.0, 5.0), (35.0, 35.0), (5.0, 35.0)]
        hole = [(15.0, 15.0), (25.0, 15.0), (25.0, 25.0), (15.0, 25.0)]

        fill_rings(mask, width, height, [outer, hole])

        assert mask[10 * width + 10] == 255
        assert mask[20 * width + 20] == 0
        # Площадь по центрам пикселей: 30×30 − 10×10.
        assert sum(1 for value in mask if value) == 800

    def test_centerline_target_peaks_on_the_line_and_fades_by_radius(self) -> None:
        width, height = 30, 30
        target = bytearray(width * height)

        centerline_target(target, width, height, [(0.0, 15.0), (30.0, 15.0)], radius=6)

        assert target[15 * width + 10] >= 200
        assert 0 < target[18 * width + 10] < target[15 * width + 10]
        assert target[22 * width + 10] == 0

    def test_interior_point_avoids_the_hole(self) -> None:
        outer = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        hole = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0)]

        point = interior_point([outer, hole])

        assert point is not None
        assert not (3 < point[0] < 7 and 3 < point[1] < 7)

    def test_simplify_drops_collinear_vertices_and_keeps_corners(self) -> None:
        ring = [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]

        assert sorted(simplify(ring, 0.5, closed=True)) == [
            (0.0, 0.0),
            (0.0, 10.0),
            (10.0, 0.0),
            (10.0, 10.0),
        ]


class TestTiles:
    def test_grid_covers_every_working_pixel(self) -> None:
        width, height, size = 1000, 700, 256
        origins = grid_origins(width, height, size, 32)
        covered_x = {x for x0, _ in origins for x in range(x0, x0 + size)}
        covered_y = {y for _, y0 in origins for y in range(y0, y0 + size)}

        assert set(range(width)) <= covered_x and set(range(height)) <= covered_y
        # Окна не выходят за рабочий растр, если он больше тайла.
        assert all(x0 + size <= width and y0 + size <= height for x0, y0 in origins)

    def test_transform_roundtrips_and_records_padding(self) -> None:
        t = TileTransform(2, 8608, 6081, 4304, 3040, 3600, 2400, 1024)

        u, v = t.page_to_tile(0.9, 0.85)
        x, y = t.tile_to_page(u, v)
        assert abs(x - 0.9) < 1e-12 and abs(y - 0.85) < 1e-12
        qx, qy = t.to_qwen(u, v)
        px, py = t.qwen_to_page(qx, qy)
        # Шаг сетки Qwen — тысячная тайла: 1024 рабочих px → 2,048 исходных.
        assert abs(px - 0.9) * 8608 <= 1.1 and abs(py - 0.85) * 6081 <= 1.1
        record = t.record()
        assert record["valid_size"] == [704, 640]
        assert record["padding"] == {"right": 320, "bottom": 384}

    def test_crop_pads_outside_the_page(self) -> None:
        pixels = bytes(range(9))

        assert crop(pixels, 3, 3, 1, 1, 3, 255) == bytes([4, 5, 255, 7, 8, 255, 255, 255, 255])


class TestSplit:
    @staticmethod
    def page(
        project: str, guid: str, bits: int, weight: int = 10, sha: str | None = None
    ) -> PageInfo:
        return PageInfo(project, guid, sha or guid * 4, bits, weight)

    def test_near_duplicates_cluster_only_within_a_project(self) -> None:
        pages = [
            self.page("a", "p1", 0b1111),
            self.page("a", "p2", 0b1110),  # расстояние 1 — типовой этаж
            self.page("a", "p3", (1 << 40) - 1),
            self.page("b", "q1", 0b1111),  # тот же хеш, но другой проект
        ]

        groups = clusters(pages, threshold=4)

        assert sorted(sorted(p.page_guid for p in g) for g in groups) == [
            ["p1", "p2"],
            ["p3"],
            ["q1"],
        ]

    def test_cluster_never_crosses_a_split_and_test_is_not_empty(self) -> None:
        pages = [self.page("a", f"p{i}", 1 << (i * 7)) for i in range(8)]
        pages.append(self.page("a", "twin", 1 << 0, sha="p0" * 4))
        # Порог 1: разные одиночные биты (расстояние 2) — разные листы, близнец по растру — тот же.
        groups = clusters(pages, threshold=1)
        assert len(groups) == 8

        split = assign(groups, {"train": 0.7, "val": 0.15, "test": 0.15}, seed=1)

        for group in groups:
            assert len({split[p.key] for p in group}) == 1
        assert set(split.values()) == {"train", "val", "test"}
        assert split == assign(groups, {"train": 0.7, "val": 0.15, "test": 0.15}, seed=1)

    def test_frozen_split_is_not_silently_rebuilt(self, tmp_path: Path) -> None:
        pages = [self.page("a", f"p{i}", 1 << (i * 9)) for i in range(6)]
        groups = clusters(pages, threshold=1)
        path = tmp_path / "split.json"
        fractions = {"train": 0.7, "val": 0.15, "test": 0.15}

        first = freeze(
            path,
            config_fingerprint="c",
            seed=1,
            groups=groups,
            assignment=assign(groups, fractions, 1),
            refreeze=False,
        )
        again = freeze(
            path,
            config_fingerprint="c",
            seed=1,
            groups=groups,
            assignment=assign(groups, fractions, 1),
            refreeze=False,
        )
        assert first["sha256"] == again["sha256"]

        other = dict.fromkeys(assign(groups, fractions, 1), "train")
        with pytest.raises(SplitFrozenError):
            freeze(
                path,
                config_fingerprint="c",
                seed=1,
                groups=groups,
                assignment=other,
                refreeze=False,
            )
        assert (
            freeze(
                path, config_fingerprint="c", seed=1, groups=groups, assignment=other, refreeze=True
            )["sha256"]
            != first["sha256"]
        )

    def test_phash_is_stable_and_separates_different_pages(self) -> None:
        width, height = 64, 64
        blank = bytes([255] * (width * height))
        lines = bytearray(blank)
        for x in range(width):
            for y in (10, 11, 40, 41):
                lines[y * width + x] = 0

        assert hamming(phash(bytes(lines), width, height), phash(bytes(lines), width, height)) == 0
        assert hamming(phash(bytes(lines), width, height), phash(blank, width, height)) > 10


def _config(
    dataset_dir: Path,
    source_root: Path,
    *,
    seed: int = 7,
    tile_px: int = 256,
    overlap_px: int = 32,
    split_fractions: dict[str, float] | None = None,
    train_negative_ratio: float = 0.3,
) -> BuildConfig:
    base = BuildConfig(
        build_id="synthetic-build",
        seed=seed,
        datasets=(
            DatasetRef("synthetic", str(dataset_dir), str(source_root), ("slab", "masonry")),
        ),
        downsample=2,
        tile_px=tile_px,
        overlap_px=overlap_px,
        targets={
            "slab": TargetConfig(kinds=("polygon",)),
            "masonry": TargetConfig(kinds=("polyline",), min_positive_fraction=0.0005, radius_px=4),
        },
        train_negative_ratio=train_negative_ratio,
    )
    if split_fractions is not None:
        base = replace(base, split_fractions=split_fractions)
    return base


@pytest.fixture
def converted(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "gt"
    assert (
        main(
            [
                "convert",
                str(project),
                "--project-key",
                "synthetic",
                "--out",
                str(dataset),
                "--allow-inside-repo",
            ]
        )
        == 0
    )
    return dataset, project / ROOT_NAME


class TestBuild:
    def test_single_page_goes_to_test_with_the_whole_grid(
        self, converted: tuple[Path, Path], tmp_path: Path
    ) -> None:
        dataset, source = converted
        out = tmp_path / "build"

        # Весь вес в test: оценочная часть — ровно сетка, без отбора по разметке.
        manifest = dataset_build.build(
            _config(dataset, source, split_fractions={"train": 0.0, "val": 0.0, "test": 1.0}), out
        )

        leakage = manifest["leakage"]
        assert isinstance(leakage, dict) and all(leakage.values())
        tiles = [
            json.loads(line)
            for line in (out / "tiles.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert {tile["split"] for tile in tiles} == {"test"}
        assert len(tiles) == len(grid_origins(1000, 500, 256, 32))
        assert {tile["crop_policy"] for tile in tiles} == {"grid"}
        assert all((out / tile["image"]).is_file() for tile in tiles)
        assert all(
            (out / "targets" / "slab" / f"{tile['tile_id']}.png").is_file() for tile in tiles
        )

    def test_qwen_localization_box_matches_the_slab(
        self, converted: tuple[Path, Path], tmp_path: Path
    ) -> None:
        dataset, source = converted
        out = tmp_path / "build"
        manifest = dataset_build.build(_config(dataset, source, tile_px=1024, overlap_px=0), out)

        rows = [
            json.loads(line)
            for line in (out / "views" / "qwen_slab_localization_v1.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(rows) == 1
        target = json.loads(rows[0]["target"])
        # Контур 200..1800 × 200..800 исходных px → рабочие /2 → доли тайла 1024 → 0..1000.
        assert target["objects"] == [
            {
                "class": "slab",
                "bbox": [98, 98, 879, 391],
                "seed_points": target["objects"][0]["seed_points"],
            }
        ]
        seed = target["objects"][0]["seed_points"][0]
        assert not (195 <= seed[0] <= 293 and 195 <= seed[1] <= 293)  # не в отверстии
        masonry = [
            json.loads(line)
            for line in (out / "views" / "qwen_masonry_roi_v0.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert json.loads(masonry[0]["target"])["contains_masonry"] is True
        assert rows[0]["instruction"] == dataset_build.INSTRUCTIONS["qwen_slab_localization_v1"]
        # Прямой полигон — неподдерживаемый вид: не собирается, причина записана.
        assert not (out / "views" / "qwen_slab_polygon_v0.jsonl").exists()
        unsupported = manifest["unsupported_views"]
        assert isinstance(unsupported, dict) and "qwen_slab_polygon_v0" in unsupported

    def test_rebuild_is_identical_and_split_change_needs_refreeze(
        self, converted: tuple[Path, Path], tmp_path: Path
    ) -> None:
        dataset, source = converted
        out = tmp_path / "build"
        first = dataset_build.build(_config(dataset, source), out)
        second = dataset_build.build(_config(dataset, source), out)
        assert first["tiles_sha256"] == second["tiles_sha256"]
        assert first["views_sha256"] == second["views_sha256"]

        with pytest.raises(SplitFrozenError):
            dataset_build.build(
                _config(
                    dataset,
                    source,
                    split_fractions={"train": 0.5, "val": 0.25, "test": 0.25},
                    seed=8,
                ),
                out,
                refreeze=False,
            )

    def test_train_negatives_prefer_ink_and_respect_the_quota(self) -> None:
        config = _config(Path("."), Path("."), train_negative_ratio=0.5)
        negatives = [("empty1", 0.0), ("ink1", 0.05), ("empty2", 0.001), ("ink2", 0.09)]

        chosen = dataset_build.select_train_negatives(
            negatives, positives=4, config=config, page_guid="g"
        )

        assert chosen == {"ink1", "ink2"}


def test_train_page_gets_grid_positives_and_gt_crops(
    converted: tuple[Path, Path], tmp_path: Path
) -> None:
    dataset, source = converted
    out = tmp_path / "build"

    dataset_build.build(_config(dataset, source), out)

    tiles = [
        json.loads(line) for line in (out / "tiles.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {tile["split"] for tile in tiles} == {"train"}
    assert "gt_positive" in {tile["crop_policy"] for tile in tiles}
    assert all(tile["positive"] or tile["crop_policy"] == "grid" for tile in tiles)
