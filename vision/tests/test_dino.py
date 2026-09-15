"""Р-8: замороженный DINOv2 + голова — форма выхода, заморозка, обучение и оценка без весов HF."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from torch import nn

from quantor_vision.slab.dino import ENCODERS, PATCH, DinoProbe
from quantor_vision.slab.train import BuiltModel, TrainConfig, evaluate, train
from tests.synthetic_build import make_build

DIM = 8


class FakeEncoder(nn.Module):
    """Вместо DINOv2: свёртка с шагом патча, выход как у `Dinov2Model` — CLS и токены патчей."""

    def __init__(self) -> None:
        super().__init__()
        self.project = nn.Conv2d(3, DIM, PATCH, stride=PATCH)

    def forward(self, pixel_values: torch.Tensor) -> SimpleNamespace:
        grid = self.project(pixel_values)
        tokens = grid.flatten(2).transpose(1, 2)
        return SimpleNamespace(
            last_hidden_state=torch.cat([tokens.mean(1, keepdim=True), tokens], 1)
        )


def _factory(config: TrainConfig, device: torch.device) -> BuiltModel:
    # Один и тот же «энкодер» при обучении и при оценке: веса задаются seed.
    torch.manual_seed(7)
    probe = DinoProbe(FakeEncoder(), DIM, config.head_width).to(device)
    return BuiltModel(probe, probe.head, probe.name, "fake-encoder")


class TestProbe:
    def test_output_matches_tile_size_including_non_multiple_of_patch(self) -> None:
        torch.manual_seed(0)
        probe = DinoProbe(FakeEncoder(), DIM, head_width=4)

        logits = probe(torch.rand(2, 1, 32, 45))

        assert logits.shape == (2, 1, 32, 45)

    def test_encoder_is_frozen_and_stays_in_eval(self) -> None:
        probe = DinoProbe(FakeEncoder(), DIM, head_width=4)
        probe.train()

        assert not probe.backbone.training
        assert all(not parameter.requires_grad for parameter in probe.backbone.parameters())
        loss = probe(torch.rand(1, 1, 28, 28)).sum()
        torch.autograd.backward(loss)
        assert all(parameter.grad is None for parameter in probe.backbone.parameters())
        assert all(parameter.grad is not None for parameter in probe.head.parameters())

    def test_pinned_encoders_have_full_revisions_and_license_rows(self) -> None:
        decisions_path = Path(__file__).resolve().parents[1] / "licenses" / "decisions.json"
        decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
        for pinned in ENCODERS.values():
            assert len(pinned.revision) == 40
            assert len(pinned.weights_sha256) == 64
            row = decisions["weights"][pinned.repo_id]
            assert row["decision"] == "allow"
            assert row["revision"] == pinned.revision


class TestTraining:
    def test_smoke_training_saves_only_head_and_evaluates_once(self, tmp_path: Path) -> None:
        build_dir = make_build(tmp_path / "build", per_split={"train": 4, "val": 2, "test": 2})
        config = TrainConfig(
            run_id="dino-smoke",
            epochs=2,
            patience=3,
            batch_size=2,
            amp="off",
            device="cpu",
            architecture="dinov2-probe",
            head_width=4,
        )

        run_dir = train(build_dir, tmp_path / "runs", config, model_factory=_factory)

        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert record["initialization"] == "fake-encoder"
        assert record["training"]["architecture"] == "dinov2-probe"
        saved = torch.load(run_dir / "best.pt", weights_only=True)
        assert saved
        assert all(not key.startswith("backbone") for key in saved)

        result = evaluate(
            build_dir, run_dir, split="test", device_choice="cpu", model_factory=_factory
        )
        assert result["tiles"] == 2
        with pytest.raises(ValueError):
            evaluate(build_dir, run_dir, split="test", device_choice="cpu", model_factory=_factory)
