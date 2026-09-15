"""Прогоны SAM на замороженном разбиении: настройка на val, test один раз на политику.

```text
<runs>/<run_id>/sam-run.json      политика, настройки и их SHA-256, веса SAM и грубой модели, сборка
<runs>/<run_id>/val-metrics.json  метрики val — можно пересчитывать, настройки при этом не меняются
<runs>/<run_id>/test-metrics.json один раз и только после val того же прогона
<runs>/sam-test-registry.json     какая политика уже оценена на test и каким прогоном
```

Защита от подбора по test: прогон на test берёт настройки из своего `sam-run.json` (менять их
нельзя), требует готовый val того же прогона и отказывает, если политика уже оценивалась на test
другим прогоном — кроме явно названного нового эксперимента, причина которого пишется в реестр.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import torch

from quantor_vision import runrecord
from quantor_vision.sam.policies import (
    POLICIES,
    AutoConfig,
    CoarseConfig,
    auto_predict,
    coarse_predict,
)
from quantor_vision.sam.segmenter import MODELS, Segmenter
from quantor_vision.slab.data import BuildInfo, SlabTiles, TileRef, load_build
from quantor_vision.slab.evaluation import evaluate_predictor, save_outputs
from quantor_vision.slab.model import TinyUNet

RECORD = "sam-run.json"
REGISTRY = "sam-test-registry.json"

SegmenterFactory = Callable[[str, torch.device], Segmenter]
JsonObject = dict[str, object]


class RunRefusedError(ValueError):
    pass


def config_sha256(policy: str, config: JsonObject) -> str:
    payload = json.dumps({"policy": policy, "config": config}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise RunRefusedError("запись прогона повреждена: ожидался объект")
    return {str(key): item for key, item in value.items()}


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RunRefusedError(f"настройка {value!r} — не число")
    return float(value)


def _read_json(path: Path) -> JsonObject:
    return _object(json.loads(path.read_text(encoding="utf-8")))


def _auto_config(config: JsonObject) -> AutoConfig:
    return AutoConfig(
        grid_per_side=int(_number(config["grid_per_side"])),
        min_score=_number(config["min_score"]),
        min_area_fraction=_number(config["min_area_fraction"]),
        max_area_fraction=_number(config["max_area_fraction"]),
        min_white_fraction=_number(config["min_white_fraction"]),
        chunk=int(_number(config["chunk"])),
    )


def _coarse_config(config: JsonObject) -> CoarseConfig:
    return CoarseConfig(
        min_area_px=int(_number(config["min_area_px"])),
        max_components=int(_number(config["max_components"])),
        min_score=_number(config["min_score"]),
    )


def run(
    build_dir: Path,
    runs_root: Path,
    *,
    run_id: str,
    split: str,
    device: torch.device,
    factory: SegmenterFactory,
    policy: str | None = None,
    model_size: str = "small",
    config: JsonObject | None = None,
    coarse_run: Path | None = None,
    new_experiment: str | None = None,
    limit_tiles: int = 0,
) -> JsonObject:
    build = load_build(build_dir)
    run_dir = runs_root / run_id
    record_path = run_dir / RECORD

    if split == "test":
        if not record_path.exists() or not (run_dir / "val-metrics.json").exists():
            raise RunRefusedError(
                "test только после val того же прогона: настройки берутся из sam-run.json"
            )
        if (run_dir / "test-metrics.json").exists():
            raise RunRefusedError("test уже оценён этим прогоном; повторная оценка не выполняется")
        if policy is not None or config is not None or coarse_run is not None:
            raise RunRefusedError("для test настройки из командной строки не принимаются")

    record = _prepare_record(
        build,
        run_dir,
        record_path,
        run_id=run_id,
        policy=policy,
        model_size=model_size,
        config=config,
        coarse_run=coarse_run,
        limit_tiles=limit_tiles,
    )
    if split == "test" and record.get("limit_tiles"):
        raise RunRefusedError("дымовой прогон (--limit-tiles) на test не оценивается")
    if record["split_sha256"] != build.split_sha256 or record["tiles_sha256"] != build.tiles_sha256:
        raise RunRefusedError("сборка не та, на которой настроен прогон")

    policy_name = str(record["policy"])
    registry_path = runs_root / REGISTRY
    registry = _read_json(registry_path) if registry_path.exists() else {}
    tested = [key for key in registry if key.split("#", 1)[0] == policy_name]
    if split == "test" and tested and not new_experiment:
        previous = _object(registry[tested[0]])
        raise RunRefusedError(
            f"политика {policy_name} уже оценена на test прогоном {previous.get('run_id')};"
            " новый test — только как явно названный новый эксперимент (--new-experiment)"
        )

    segmenter = factory(str(record["model_size"]), device)
    predictor = _predictor(record, segmenter, device)
    tiles = [tile for tile in build.tiles if tile.split == split]
    limit = int(_number(record.get("limit_tiles", 0)))
    dataset = SlabTiles(tiles[:limit] if limit else tiles, augment=False, seed=0)
    output = evaluate_predictor(
        dataset,
        predictor,
        threshold=0.5,
        device=device,
        predictions_dir=run_dir / "predictions" / split,
    )
    provenance = segmenter.provenance()
    record["sam"] = provenance
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = save_outputs(
        run_dir,
        split,
        output,
        {
            "run_id": run_id,
            "policy": policy_name,
            "config_sha256": record["config_sha256"],
            "sam": provenance,
        },
    )

    if split == "test":
        key = policy_name if not tested else f"{policy_name}#{len(tested) + 1}"
        registry[key] = {
            "run_id": run_id,
            "config_sha256": record["config_sha256"],
            "reason": new_experiment or "первый test политики",
        }
        registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return result


def _prepare_record(
    build: BuildInfo,
    run_dir: Path,
    record_path: Path,
    *,
    run_id: str,
    policy: str | None,
    model_size: str,
    config: JsonObject | None,
    coarse_run: Path | None,
    limit_tiles: int,
) -> JsonObject:
    if record_path.exists():
        existing = _read_json(record_path)
        if policy is not None:
            merged = _merged(policy, config, coarse_run)
            if (
                policy != existing["policy"]
                or config_sha256(policy, merged) != existing["config_sha256"]
            ):
                raise RunRefusedError(
                    f"прогон {run_id} уже настроен иначе"
                    f" ({str(existing['config_sha256'])[:12]}); новые настройки — новый --run-id"
                )
        return existing
    if policy is None:
        raise RunRefusedError("для нового прогона нужна --policy")
    if policy not in POLICIES:
        raise RunRefusedError(f"неизвестная политика {policy!r}")
    if model_size not in MODELS:
        raise RunRefusedError(f"неизвестный размер SAM {model_size!r}")
    merged = _merged(policy, config, coarse_run)
    run_dir.mkdir(parents=True, exist_ok=True)
    record: JsonObject = {
        "run_id": run_id,
        "task": "slab_segmentation",
        "policy": policy,
        "model_size": model_size,
        # >0 — дымовой прогон: val на части тайлов, test запрещён.
        "limit_tiles": limit_tiles,
        "config": merged,
        "config_sha256": config_sha256(policy, merged),
        "split_sha256": build.split_sha256,
        "tiles_sha256": build.tiles_sha256,
        "prompt_source": "изображение тайла"
        if policy == "auto"
        else "прогноз малого U-Net промта 10 (без разметки)",
        "software": runrecord.software_versions((*runrecord.TRACKED_PACKAGES, "huggingface-hub")),
        "source_state": runrecord.source_state(Path(__file__).resolve().parents[3]),
    }
    if coarse_run is not None:
        # Путь — только в частной записи на машине с данными; в отпечаток настроек входит id.
        record["coarse_run_dir"] = str(coarse_run)
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record


def _merged(policy: str, config: JsonObject | None, coarse_run: Path | None) -> JsonObject:
    defaults: JsonObject = asdict(AutoConfig() if policy == "auto" else CoarseConfig())
    unknown = set(config or {}) - set(defaults)
    if unknown:
        raise RunRefusedError(f"неизвестные настройки политики {policy}: {sorted(unknown)}")
    merged: JsonObject = {**defaults, **(config or {})}
    if policy == "coarse":
        if coarse_run is None:
            raise RunRefusedError("политика coarse требует --coarse-run (прогон промта 10)")
        merged["coarse_run_id"] = coarse_run.name
    return merged


def _predictor(
    record: JsonObject, segmenter: Segmenter, device: torch.device
) -> Callable[[TileRef, torch.Tensor], torch.Tensor]:
    config = _object(record["config"])
    if record["policy"] == "auto":
        auto = _auto_config(config)

        def predict_auto(_: TileRef, image: torch.Tensor) -> torch.Tensor:
            return auto_predict(segmenter, image, auto)

        return predict_auto

    coarse_dir = Path(str(record["coarse_run_dir"]))
    coarse = _coarse_config(config)
    coarse_record = _read_json(coarse_dir / "run.json")
    weights = coarse_dir / "best.pt"
    coarse_weights = _object(_list(coarse_record["weights"])[0])
    if runrecord.sha256_file(weights) != coarse_weights["sha256"]:
        raise RunRefusedError("веса грубой модели изменены после обучения")
    if coarse_record["split_sha256"] != record["split_sha256"]:
        raise RunRefusedError("грубая модель обучалась на другом разбиении")
    training = _object(coarse_record["training"])
    if training.get("architecture", "tiny-unet") != "tiny-unet":
        raise RunRefusedError("политика coarse пока принимает только грубую модель tiny-unet")
    model = TinyUNet(int(_number(training["base_width"])), int(_number(training["depth"])))
    model = model.to(device)
    model.load_state_dict(torch.load(weights, map_location=device, weights_only=True))
    model.eval()
    threshold = _number(training["frozen_threshold"])
    use_bf16 = training.get("amp") == "bf16" and device.type == "cuda"
    record["coarse_model"] = {
        "run_id": str(coarse_record["run_id"]),
        "weights_sha256": str(coarse_weights["sha256"]),
        "frozen_threshold": threshold,
    }

    def predict_coarse(_: TileRef, image: torch.Tensor) -> torch.Tensor:
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=use_bf16):
            logits = model(image.unsqueeze(0).to(device))
        probability = torch.sigmoid(logits.float()).cpu()[0]
        return coarse_predict(
            segmenter, image, probability, coarse_threshold=threshold, config=coarse
        )

    return predict_coarse


def _list(value: object) -> list[object]:
    if not isinstance(value, list) or not value:
        raise RunRefusedError("запись прогона повреждена: ожидался непустой список")
    return value
