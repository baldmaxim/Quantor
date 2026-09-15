"""Промт 11 на синтетике: подсказки без разметки, политики SAM, test один раз на политику.

Настоящий SAM здесь не грузится: сегментатор подменён детерминированной заглушкой с тем же
интерфейсом. Проверяется то, что можно испортить в своём коде, — откуда берутся подсказки, что
остаётся после фильтров и как защищён test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from quantor_vision.sam.policies import AutoConfig, CoarseConfig, auto_predict, coarse_predict
from quantor_vision.sam.prompts import components, grid_points
from quantor_vision.sam.run import RunRefusedError, run
from quantor_vision.sam.segmenter import MaskBatch
from quantor_vision.slab.train import TrainConfig, train
from tests.synthetic_build import _png, make_build


class FakeSegmenter:
    """Рамка → маска-прямоугольник; точка → квадрат 8×8 вокруг неё. Логиты 64×64 на тайл 32×32."""

    def __init__(self, size: int = 32) -> None:
        self.size = size
        self.calls: list[str] = []

    def embed(self, image: torch.Tensor) -> object:
        self.calls.append("embed")
        return image

    def _mask(self, x0: float, y0: float, x1: float, y1: float) -> torch.Tensor:
        scale = 2
        logits = torch.full((self.size * scale, self.size * scale), -5.0)
        logits[int(y0 * scale) : int(y1 * scale), int(x0 * scale) : int(x1 * scale)] = 5.0
        return logits

    def from_points(self, embedding: object, points: list[tuple[float, float]]) -> MaskBatch:
        self.calls.append(f"points:{len(points)}")
        masks = [self._mask(x - 4, y - 4, x + 4, y + 4) for x, y in points]
        logits = torch.stack([torch.stack([m, m * 0 - 5, m * 0 - 5]) for m in masks])
        return MaskBatch(logits, torch.tensor([[0.95, 0.1, 0.1]] * len(points)))

    def from_boxes(
        self,
        embedding: object,
        boxes: list[tuple[float, float, float, float]],
        points: list[tuple[float, float]],
    ) -> MaskBatch:
        self.calls.append(f"boxes:{len(boxes)}")
        masks = [self._mask(*box) for box in boxes]
        logits = torch.stack([torch.stack([m, m * 0 - 5, m * 0 - 5]) for m in masks])
        return MaskBatch(logits, torch.tensor([[0.9, 0.2, 0.2]] * len(boxes)))

    def provenance(self) -> dict[str, str]:
        return {"model_id": "fake", "revision": "0", "weights_sha256": "0" * 64}


class TestPrompts:
    def test_grid_covers_the_tile(self) -> None:
        points = grid_points(1024, 16)

        assert len(points) == 256
        assert points[0] == (32.0, 32.0) and points[-1] == (992.0, 992.0)

    def test_components_give_box_and_confident_point(self) -> None:
        probability = torch.zeros(1, 64, 64)
        probability[0, 8:24, 8:40] = 0.7
        probability[0, 12, 20] = 0.99
        probability[0, 48:52, 48:52] = 0.9  # мелкая область — отбрасывается

        found = components(probability, threshold=0.5, stride=4, min_area_px=64, max_components=8)

        assert len(found) == 1
        assert found[0].box == (8, 8, 40, 24)
        assert found[0].point == (22.0, 14.0)


class TestPolicies:
    def test_auto_keeps_confident_white_regions_only(self) -> None:
        image = torch.ones(1, 32, 32)
        image[0, :, 16:] = 0.0  # правая половина — «чернила»
        config = AutoConfig(
            grid_per_side=4,
            min_score=0.5,
            min_area_fraction=0.01,
            max_area_fraction=0.9,
            min_white_fraction=0.9,
            chunk=3,
        )

        mask = auto_predict(FakeSegmenter(), image, config)

        assert mask.shape == (1, 32, 32)
        assert float(mask[0, :, :12].sum()) > 0
        assert float(mask[0, :, 20:].sum()) == 0

    def test_coarse_refines_by_component_boxes(self) -> None:
        image = torch.ones(1, 32, 32)
        probability = torch.zeros(1, 32, 32)
        probability[0, 4:20, 4:28] = 0.8
        segmenter = FakeSegmenter()

        mask = coarse_predict(
            segmenter,
            image,
            probability,
            coarse_threshold=0.5,
            config=CoarseConfig(min_area_px=16, max_components=4, min_score=0.5),
        )

        assert segmenter.calls == ["embed", "boxes:1"]
        assert float(mask[0, 4:20, 4:28].mean()) == 1.0
        assert float(mask.sum()) == 16 * 24

    def test_coarse_without_components_skips_sam(self) -> None:
        segmenter = FakeSegmenter()

        mask = coarse_predict(
            segmenter,
            torch.ones(1, 32, 32),
            torch.zeros(1, 32, 32),
            coarse_threshold=0.5,
            config=CoarseConfig(),
        )

        assert segmenter.calls == [] and float(mask.sum()) == 0


def _factory(_: str, __: torch.device) -> FakeSegmenter:
    return FakeSegmenter()


class TestRunProtocol:
    def test_val_then_single_test_per_policy(self, tmp_path: Path) -> None:
        make_build(tmp_path / "build", per_split={"train": 2, "val": 2, "test": 2})
        runs = tmp_path / "runs"
        cpu = torch.device("cpu")

        with pytest.raises(RunRefusedError, match="после val"):
            run(
                tmp_path / "build",
                runs,
                run_id="auto-1",
                split="test",
                device=cpu,
                factory=_factory,
            )

        val = run(
            tmp_path / "build",
            runs,
            run_id="auto-1",
            split="val",
            device=cpu,
            factory=_factory,
            policy="auto",
            config={"grid_per_side": 4},
        )
        assert val["policy"] == "auto" and val["tiles"] == 2
        record = json.loads((runs / "auto-1" / "sam-run.json").read_text(encoding="utf-8"))
        assert record["prompt_source"] == "изображение тайла"

        with pytest.raises(RunRefusedError, match="настройки из командной строки"):
            run(
                tmp_path / "build",
                runs,
                run_id="auto-1",
                split="test",
                device=cpu,
                factory=_factory,
                policy="auto",
            )

        test = run(
            tmp_path / "build", runs, run_id="auto-1", split="test", device=cpu, factory=_factory
        )
        assert test["config_sha256"] == record["config_sha256"]

        with pytest.raises(RunRefusedError, match="уже оценён"):
            run(
                tmp_path / "build",
                runs,
                run_id="auto-1",
                split="test",
                device=cpu,
                factory=_factory,
            )

        run(
            tmp_path / "build",
            runs,
            run_id="auto-2",
            split="val",
            device=cpu,
            factory=_factory,
            policy="auto",
            config={"grid_per_side": 8},
        )
        with pytest.raises(RunRefusedError, match="уже оценена на test"):
            run(
                tmp_path / "build",
                runs,
                run_id="auto-2",
                split="test",
                device=cpu,
                factory=_factory,
            )
        run(
            tmp_path / "build",
            runs,
            run_id="auto-2",
            split="test",
            device=cpu,
            factory=_factory,
            new_experiment="сетка 8 вместо 4",
        )
        registry = json.loads((runs / "sam-test-registry.json").read_text(encoding="utf-8"))
        assert set(registry) == {"auto", "auto#2"}
        assert registry["auto#2"]["reason"] == "сетка 8 вместо 4"

    def test_smoke_run_cannot_reach_test(self, tmp_path: Path) -> None:
        make_build(tmp_path / "build", per_split={"train": 1, "val": 3, "test": 1})
        cpu = torch.device("cpu")
        result = run(
            tmp_path / "build",
            tmp_path / "runs",
            run_id="smoke",
            split="val",
            device=cpu,
            factory=_factory,
            policy="auto",
            limit_tiles=1,
        )
        assert result["tiles"] == 1

        with pytest.raises(RunRefusedError, match="дымовой"):
            run(
                tmp_path / "build",
                tmp_path / "runs",
                run_id="smoke",
                split="test",
                device=cpu,
                factory=_factory,
            )

    def test_changed_settings_need_a_new_run_id(self, tmp_path: Path) -> None:
        make_build(tmp_path / "build", per_split={"train": 1, "val": 1})
        cpu = torch.device("cpu")
        run(
            tmp_path / "build",
            tmp_path / "runs",
            run_id="r",
            split="val",
            device=cpu,
            factory=_factory,
            policy="auto",
        )

        with pytest.raises(RunRefusedError, match="настроен иначе"):
            run(
                tmp_path / "build",
                tmp_path / "runs",
                run_id="r",
                split="val",
                device=cpu,
                factory=_factory,
                policy="auto",
                config={"grid_per_side": 2},
            )
        with pytest.raises(RunRefusedError, match="неизвестные настройки"):
            run(
                tmp_path / "build",
                tmp_path / "runs",
                run_id="x",
                split="val",
                device=cpu,
                factory=_factory,
                policy="auto",
                config={"gt_boxes": 1},
            )

    def test_predictions_do_not_depend_on_ground_truth(self, tmp_path: Path) -> None:
        """Те же изображения, другие маски истины → те же прогнозы: подсказки не видят GT."""
        cpu = torch.device("cpu")
        make_build(tmp_path / "a" / "build", per_split={"train": 1, "val": 2})
        make_build(tmp_path / "b" / "build", per_split={"train": 1, "val": 2})
        # Во втором наборе все маски истины заменены пустыми: изображения те же, истина другая.
        empty = bytes(32 * 32)
        for mask in (tmp_path / "b" / "build" / "targets" / "slab").glob("*.png"):
            _png(mask, 32, 32, empty)
        results = []
        for side in ("a", "b"):
            run(
                tmp_path / side / "build",
                tmp_path / side / "runs",
                run_id="r",
                split="val",
                device=cpu,
                factory=_factory,
                policy="auto",
                config={"grid_per_side": 4},
            )
            results.append(
                (tmp_path / side / "runs" / "r" / "val-predictions.jsonl").read_text(
                    encoding="utf-8"
                )
            )

        assert results[0] == results[1]

    def test_coarse_policy_uses_the_prompt10_run(self, tmp_path: Path) -> None:
        build = make_build(tmp_path / "build", per_split={"train": 3, "val": 2, "test": 1})
        coarse = train(
            build,
            tmp_path / "coarse",
            TrainConfig(
                run_id="unet",
                epochs=1,
                batch_size=3,
                base_width=4,
                depth=2,
                amp="off",
                device="cpu",
            ),
        )
        cpu = torch.device("cpu")

        with pytest.raises(RunRefusedError, match="coarse-run"):
            run(
                build,
                tmp_path / "runs",
                run_id="c",
                split="val",
                device=cpu,
                factory=_factory,
                policy="coarse",
            )
        result = run(
            build,
            tmp_path / "runs",
            run_id="c2",
            split="val",
            device=cpu,
            factory=_factory,
            policy="coarse",
            coarse_run=coarse,
        )

        record = json.loads((tmp_path / "runs" / "c2" / "sam-run.json").read_text(encoding="utf-8"))
        assert record["coarse_model"]["run_id"] == "unet"
        assert record["config"]["coarse_run_id"] == "unet"
        assert result["policy"] == "coarse"

        (coarse / "best.pt").write_bytes(b"tampered")
        with pytest.raises(RunRefusedError, match="веса грубой модели"):
            run(build, tmp_path / "runs", run_id="c2", split="val", device=cpu, factory=_factory)
