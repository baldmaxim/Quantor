"""Промт 10 на синтетике: U-Net, метрики, данные, обучение и оценка без утечки.

Файл требует torch: без него `conftest.py` его не собирает (CI без тяжёлых зависимостей). На машине
разработки тесты идут на CPU во временном окружении, на машине владельца — в `.venv-train`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from quantor_vision.slab.data import SlabTiles, load_build, positive_fraction
from quantor_vision.slab.metrics import MaskMetrics, boundary, page_area_errors
from quantor_vision.slab.model import TinyUNet, parameter_count
from quantor_vision.slab.train import TrainConfig, evaluate, train
from tests.synthetic_build import TILE, make_build


class TestModelAndMetrics:
    def test_unet_keeps_resolution_and_is_small(self) -> None:
        model = TinyUNet(base=8, depth=3)
        out = model(torch.zeros(2, 1, 64, 64))

        assert out.shape == (2, 1, 64, 64)
        assert parameter_count(TinyUNet()) < 3_000_000

    def test_perfect_prediction_scores_one(self) -> None:
        truth = torch.zeros(1, 1, 16, 16)
        truth[..., 4:12, 4:12] = 1
        truth[..., 7:9, 7:9] = 0  # отверстие
        metrics = MaskMetrics()
        metrics.update(truth.clone(), truth, torch.ones_like(truth, dtype=torch.bool))

        summary = metrics.summary()
        assert summary["iou"] == 1.0 and summary["boundary_f1"] == 1.0
        assert summary["tile_area_error_median"] == 0.0

    def test_filled_hole_is_penalised(self) -> None:
        truth = torch.zeros(1, 1, 32, 32)
        truth[..., 4:28, 4:28] = 1
        truth[..., 12:20, 12:20] = 0
        filled = torch.zeros_like(truth)
        filled[..., 4:28, 4:28] = 1
        metrics = MaskMetrics()
        metrics.update(filled, truth, torch.ones_like(truth, dtype=torch.bool))

        summary = metrics.summary()
        assert float(summary["iou"] or 0) < 1.0
        assert float(summary["boundary_f1"] or 0) < 1.0  # граница отверстия не найдена
        assert summary["tile_area_error_median"] == pytest.approx(64 / (576 - 64))

    def test_padding_is_excluded(self) -> None:
        truth = torch.zeros(1, 1, 8, 8)
        prediction = torch.zeros(1, 1, 8, 8)
        prediction[..., :, 6:] = 1  # «плита» только в заливке
        valid = torch.zeros_like(truth, dtype=torch.bool)
        valid[..., :, :6] = True
        metrics = MaskMetrics()
        metrics.update(prediction, truth, valid)

        assert metrics.summary()["iou"] == 1.0

    def test_boundary_of_a_square(self) -> None:
        square = torch.zeros(1, 1, 8, 8)
        square[..., 2:6, 2:6] = 1

        assert int(boundary(square).sum()) == 12

    def test_page_area_errors(self) -> None:
        result = page_area_errors({"a": (90.0, 100.0), "b": (110.0, 100.0), "c": (5.0, 0.0)})

        assert result["pages_with_slab"] == 2
        assert result["page_area_error_median"] == pytest.approx(0.1)


class TestData:
    def test_padding_region_and_positive_fraction(self, tmp_path: Path) -> None:
        build = load_build(make_build(tmp_path / "build", per_split={"train": 2}, valid=24))
        dataset = SlabTiles(build.tiles, augment=False, seed=1)

        x, y, valid = dataset[0]
        assert x.shape == y.shape == valid.shape == (1, TILE, TILE)
        assert bool(valid[0, 0, 23]) and not bool(valid[0, 0, 24])
        assert 0 < positive_fraction(dataset) < 1

    def test_augmentation_moves_image_mask_and_valid_together(self, tmp_path: Path) -> None:
        build = load_build(make_build(tmp_path / "build", per_split={"train": 1}, valid=24))
        plain = SlabTiles(build.tiles, augment=False, seed=1)
        x0, y0, _ = plain[0]
        augmented = SlabTiles(build.tiles, augment=True, seed=3)

        for _ in range(8):
            x, y, valid = augmented[0]
            # Тёмные пиксели изображения и граница маски трансформируются одинаково.
            assert int((x < 0.5).sum()) == int((x0 < 0.5).sum())
            assert int(y.sum()) == int(y0.sum())
            assert int(valid.sum()) == 24 * TILE


class TestTrainAndEvaluate:
    def test_smoke_training_then_single_test_evaluation(self, tmp_path: Path) -> None:
        build_dir = make_build(tmp_path / "build", per_split={"train": 6, "val": 3, "test": 3})
        runs = tmp_path / "runs"
        config = TrainConfig(
            run_id="smoke",
            epochs=3,
            patience=5,
            batch_size=3,
            base_width=4,
            depth=2,
            amp="off",
            device="cpu",
        )

        run_dir = train(build_dir, runs, config)

        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert record["task"] == "slab_segmentation"
        assert record["split_sha256"] == "c" * 64
        assert 0.2 <= record["training"]["frozen_threshold"] <= 0.8
        assert record["training"]["train_tiles"] == 6
        assert (run_dir / "best.pt").is_file()

        result = evaluate(build_dir, run_dir, split="test", device_choice="cpu")
        assert result["tiles"] == 3
        pixel = result["pixel"]
        assert isinstance(pixel, dict) and 0.0 <= float(pixel["iou"]) <= 1.0
        assert (
            len((run_dir / "test-predictions.jsonl").read_text(encoding="utf-8").splitlines()) == 3
        )

        with pytest.raises(ValueError, match="уже оценён"):
            evaluate(build_dir, run_dir, split="test", device_choice="cpu")

    def test_evaluation_refuses_a_different_build(self, tmp_path: Path) -> None:
        build_dir = make_build(tmp_path / "build", per_split={"train": 3, "val": 2, "test": 2})
        run_dir = train(
            build_dir,
            tmp_path / "runs",
            TrainConfig(
                run_id="r", epochs=1, batch_size=3, base_width=4, depth=2, amp="off", device="cpu"
            ),
        )
        other = make_build(tmp_path / "other", per_split={"train": 3, "val": 2, "test": 3})

        with pytest.raises(ValueError, match="сборка не та"):
            evaluate(other, run_dir, split="test", device_choice="cpu")

    def test_tampered_weights_are_refused(self, tmp_path: Path) -> None:
        build_dir = make_build(tmp_path / "build", per_split={"train": 3, "val": 2, "test": 2})
        run_dir = train(
            build_dir,
            tmp_path / "runs",
            TrainConfig(
                run_id="w", epochs=1, batch_size=3, base_width=4, depth=2, amp="off", device="cpu"
            ),
        )
        (run_dir / "best.pt").write_bytes(b"x")

        with pytest.raises(ValueError, match="веса"):
            evaluate(build_dir, run_dir, split="test", device_choice="cpu")
