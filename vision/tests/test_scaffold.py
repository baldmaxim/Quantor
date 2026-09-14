"""Каркас ML-контура: лицензионный гейт, контракт эксперимента, CLI и проверка сборки (промт 09)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from quantor_vision import licenses, runrecord
from quantor_vision.cli import DECISIONS, REPO_ROOT, main, verify_build
from quantor_vision.environment import BLOCKED_EXIT


def _decisions(tmp_path: Path, packages: dict[str, str]) -> Path:
    path = tmp_path / "decisions.json"
    path.write_text(
        json.dumps({"packages": {name: {"decision": value} for name, value in packages.items()}}),
        encoding="utf-8",
    )
    return path


class TestLicenseGate:
    def test_repository_manifests_pass_the_gate(self) -> None:
        assert licenses.check(REPO_ROOT, DECISIONS) == []

    def test_ultralytics_anywhere_is_a_violation(self, tmp_path: Path) -> None:
        (tmp_path / "vision").mkdir()
        (tmp_path / "vision" / "pyproject.toml").write_text(
            '[project]\nname = "x"\ndependencies = []\n'
            '[project.optional-dependencies]\ndetect = ["ultralytics>=8"]\n',
            encoding="utf-8",
        )
        (tmp_path / "requirements-train.txt").write_text(
            "torch==2.4\nUltralytics\n", encoding="utf-8"
        )

        violations = licenses.check(tmp_path, DECISIONS)

        assert {(v.manifest, v.package) for v in violations} == {
            ("vision/pyproject.toml", "ultralytics"),
            ("requirements-train.txt", "ultralytics"),
        }

    def test_unknown_guarded_package_needs_a_decision(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps(
                {"dependencies": {"left-pad": "1"}, "devDependencies": {"onnxruntime": "1"}}
            ),
            encoding="utf-8",
        )

        violations = licenses.check(tmp_path, _decisions(tmp_path, {}))

        assert [(v.package, v.reason) for v in violations] == [
            ("onnxruntime", "нет решения в матрице лицензий")
        ]

    def test_conditional_is_allowed_but_blocked_is_not(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("shapely\nunsloth[colab]\n", encoding="utf-8")
        decisions = _decisions(tmp_path, {"shapely": "conditional", "unsloth": "blocked"})

        assert [v.package for v in licenses.check(tmp_path, decisions)] == ["unsloth"]

    def test_node_modules_is_not_scanned(self, tmp_path: Path) -> None:
        nested = tmp_path / "node_modules" / "pkg"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text(
            json.dumps({"dependencies": {"ultralytics": "1"}}), encoding="utf-8"
        )

        assert licenses.check(tmp_path, DECISIONS) == []

    def test_matrix_blocks_ultralytics_and_unsloth(self) -> None:
        decisions = licenses.load_decisions(DECISIONS)

        assert decisions["ultralytics"] == "blocked"
        assert decisions["unsloth"] == "blocked"
        assert all(name in decisions for name in ("torch", "sam2", "transformers", "peft", "trl"))


def _record(
    run_dir: Path,
    *,
    task: str = "slab_segmentation",
    split_sha256: str = "b" * 64,
    metrics: dict[str, object] | None = None,
    weights: list[runrecord.Weights] | None = None,
) -> runrecord.RunRecord:
    file = run_dir / "model.bin"
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"weights")
    return runrecord.RunRecord(
        run_id="slab-tiny-unet-001",
        task=task,
        dataset_fingerprint="a" * 64,
        split_sha256=split_sha256,
        architecture="tiny-unet-16",
        initialization="scratch",
        seed=20260914,
        preprocessing={"downsample": 2},
        augmentation={"flip": True},
        training={"epochs": 1},
        software=runrecord.software_versions(()),
        source_state=runrecord.source_state(REPO_ROOT),
        weights=weights
        if weights is not None
        else [runrecord.Weights("model.bin", hashlib.sha256(b"weights").hexdigest())],
        metrics={"val_iou": 0.5} if metrics is None else metrics,
    )


class TestRunRecord:
    def test_complete_record_is_written(self, tmp_path: Path) -> None:
        record = _record(tmp_path)

        path = runrecord.write(record, tmp_path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["weights"][0]["sha256"] == hashlib.sha256(b"weights").hexdigest()
        assert data["source_state"]["git_commit"]

    def test_incomplete_record_is_refused(self, tmp_path: Path) -> None:
        record = _record(tmp_path, split_sha256="short", metrics={}, task="guessing")

        problems = runrecord.validate(record, tmp_path)

        assert any("split_sha256" in problem for problem in problems)
        assert any("metrics" in problem for problem in problems)
        assert any("task" in problem for problem in problems)
        with pytest.raises(ValueError, match="неполна"):
            runrecord.write(record, tmp_path)

    def test_weight_hash_must_match_the_file(self, tmp_path: Path) -> None:
        record = _record(tmp_path, weights=[runrecord.Weights("model.bin", "0" * 64)])

        assert any("SHA-256 веса" in problem for problem in runrecord.validate(record, tmp_path))


def _build_dir(tmp_path: Path) -> Path:
    build = tmp_path / "build"
    (build / "views").mkdir(parents=True)
    (build / "tiles.jsonl").write_text('{"tile_id":"t"}\n', encoding="utf-8")
    (build / "views" / "qwen_masonry_roi_v0.jsonl").write_text("", encoding="utf-8")
    body = {
        "holdout": "within-project grouped holdout",
        "pages": [],
        "seed": 1,
        "split_config_fingerprint": "c",
    }
    digest = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    ).hexdigest()
    (build / "split.json").write_text(json.dumps({**body, "sha256": digest}), encoding="utf-8")
    manifest = {
        "split_sha256": digest,
        "tiles_sha256": hashlib.sha256((build / "tiles.jsonl").read_bytes()).hexdigest(),
        "views_sha256": {"qwen_masonry_roi_v0": hashlib.sha256(b"").hexdigest()},
        "leakage": {"evaluation_tiles_grid_only": True},
    }
    (build / "build.json").write_text(json.dumps(manifest), encoding="utf-8")
    return build


class TestCli:
    def test_training_commands_report_blocked_not_success(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["qwen-train", "--config", "x.json"])

        report = json.loads(capsys.readouterr().out)
        assert code == BLOCKED_EXIT
        assert report["status"] in ("BLOCKED", "NOT_IMPLEMENTED")
        assert report["prompt"] == "промт 13"

    def test_build_verification_accepts_intact_and_rejects_tampered(self, tmp_path: Path) -> None:
        build = _build_dir(tmp_path)
        assert verify_build(build) == []

        (build / "tiles.jsonl").write_text('{"tile_id":"other"}\n', encoding="utf-8")
        assert verify_build(build) == ["tiles.jsonl изменён после сборки"]

    def test_leakage_failure_is_reported(self, tmp_path: Path) -> None:
        build = _build_dir(tmp_path)
        manifest = json.loads((build / "build.json").read_text(encoding="utf-8"))
        manifest["leakage"]["evaluation_tiles_grid_only"] = False
        (build / "build.json").write_text(json.dumps(manifest), encoding="utf-8")

        assert any("утечки" in problem for problem in verify_build(build))

    def test_licenses_check_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["licenses-check"]) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True
