"""Обучение и оценка малой сегментации плиты (промт 10).

Порядок строгий:

1. обучение только на train; каждую эпоху — IoU на val при пороге 0,5, лучшая эпоха сохраняется;
2. ранняя остановка по val;
3. порог выбирается на val по лучшей эпохе и **замораживается** в `run.json`;
4. test оценивается отдельной командой один раз, с замороженным порогом — ни порог, ни эпоха по
   test не выбираются.

Дисбаланс классов учтён явно: BCE с `pos_weight = фон / плита` (с ограничением) плюс мягкий Dice.
"""

from __future__ import annotations

import json
import platform
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional

from quantor_vision import runrecord
from quantor_vision.slab.data import BuildInfo, SlabTiles, TileRef, load_build, positive_fraction
from quantor_vision.slab.dino import DinoProbe
from quantor_vision.slab.evaluation import evaluate_predictor, save_outputs
from quantor_vision.slab.metrics import MaskMetrics
from quantor_vision.slab.model import TinyUNet, parameter_count

ARCHITECTURES = ("tiny-unet", "dinov2-probe")

THRESHOLDS = tuple(round(0.2 + 0.05 * step, 2) for step in range(13))


@dataclass(frozen=True, slots=True)
class TrainConfig:
    run_id: str
    seed: int = 20260914
    epochs: int = 60
    patience: int = 10
    batch_size: int = 4
    learning_rate: float = 2e-3
    weight_decay: float = 1e-4
    base_width: int = 16
    depth: int = 4
    amp: str = "bf16"  # bf16 | off
    max_pos_weight: float = 20.0
    limit_tiles: int = 0  # 0 — все; >0 — дымовой прогон на первых тайлах
    device: str = "auto"
    # tiny-unet — промт 10; dinov2-probe — замороженный DINOv2 + голова (Р-8).
    architecture: str = "tiny-unet"
    encoder: str = "large"
    head_width: int = 256


@dataclass(frozen=True, slots=True)
class BuiltModel:
    module: nn.Module
    # Часть, которая обучается и сохраняется в best.pt: весь U-Net или только голова DINOv2.
    trainable: nn.Module
    name: str
    initialization: str


ModelFactory = Callable[[TrainConfig, torch.device], BuiltModel]


def build_model(config: TrainConfig, device: torch.device) -> BuiltModel:
    if config.architecture == "tiny-unet":
        unet = TinyUNet(config.base_width, config.depth).to(device)
        return BuiltModel(unet, unet, unet.name, "scratch")
    if config.architecture == "dinov2-probe":
        from quantor_vision.slab.dino import ENCODERS, load_encoder

        encoder, initialization = load_encoder(config.encoder, device)
        probe = DinoProbe(encoder, ENCODERS[config.encoder].embed_dim, config.head_width)
        probe = probe.to(device)
        return BuiltModel(probe, probe.head, probe.name, initialization)
    raise ValueError(f"архитектура {config.architecture!r} не из {ARCHITECTURES}")


def _device(choice: str) -> torch.device:
    if choice == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(choice)


def _seed(seed: int) -> None:
    torch.manual_seed(seed)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)


def _loss(
    logits: torch.Tensor, target: torch.Tensor, valid: torch.Tensor, pos_weight: torch.Tensor
) -> torch.Tensor:
    v = valid.float()
    bce = functional.binary_cross_entropy_with_logits(
        logits, target, pos_weight=pos_weight, reduction="none"
    )
    bce = (bce * v).sum() / v.sum().clamp(min=1)
    probability = torch.sigmoid(logits) * v
    t = target * v
    dice = 1 - (2 * (probability * t).sum() + 1) / (probability.sum() + t.sum() + 1)
    return bce + dice


def _autocast(device: torch.device, amp: str) -> torch.autocast:
    enabled = amp == "bf16" and device.type == "cuda"
    return torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=enabled)


def _logits(
    model: nn.Module, x: torch.Tensor, index: int, cache: list[torch.Tensor] | None
) -> torch.Tensor:
    """Логиты тайла. У DINOv2 признаки неизменной части (val без аугментаций) считаются один раз."""
    if not isinstance(model, DinoProbe):
        logits: torch.Tensor = model(x)
        return logits
    if cache is not None and index < len(cache):
        features = cache[index].to(x.device)
    else:
        features = model.features(x)
        if cache is not None:
            cache.append(features.to("cpu", torch.float16))
    return model.decode(features, x.shape[2], x.shape[3])


def _probabilities(
    model: nn.Module,
    dataset: SlabTiles,
    device: torch.device,
    amp: str,
    cache: list[torch.Tensor] | None = None,
) -> list[torch.Tensor]:
    model.eval()
    outputs: list[torch.Tensor] = []
    with torch.no_grad():
        for index in range(len(dataset)):
            x, _, _ = dataset[index]
            with _autocast(device, amp):
                logits = _logits(model, x.unsqueeze(0).to(device), index, cache)
            outputs.append(torch.sigmoid(logits.float()).cpu()[0])
    return outputs


def _batches(
    dataset: SlabTiles, batch_size: int, generator: torch.Generator
) -> Iterator[tuple[torch.Tensor, ...]]:
    order = torch.randperm(len(dataset), generator=generator).tolist()
    for start in range(0, len(order), batch_size):
        items = [dataset[index] for index in order[start : start + batch_size]]
        yield tuple(torch.stack([item[part] for item in items]) for part in range(3))


def _score(
    probabilities: list[torch.Tensor], dataset: SlabTiles, threshold: float
) -> dict[str, float | int | None]:
    metrics = MaskMetrics()
    for index, probability in enumerate(probabilities):
        _, y, valid = dataset[index]
        metrics.update(
            (probability >= threshold).float().unsqueeze(0), y.unsqueeze(0), valid.unsqueeze(0)
        )
    return metrics.summary()


def _split(build: BuildInfo, name: str, limit: int) -> list[TileRef]:
    tiles = [tile for tile in build.tiles if tile.split == name]
    return tiles[:limit] if limit else tiles


def train(
    build_dir: Path,
    runs_root: Path,
    config: TrainConfig,
    model_factory: ModelFactory = build_model,
) -> Path:
    _seed(config.seed)
    device = _device(config.device)
    build = load_build(build_dir)
    train_set = SlabTiles(
        _split(build, "train", config.limit_tiles), augment=True, seed=config.seed
    )
    val_set = SlabTiles(_split(build, "val", config.limit_tiles), augment=False, seed=config.seed)
    if not len(train_set) or not len(val_set):
        raise ValueError("в сборке нет тайлов плиты в train или val")

    fraction = positive_fraction(train_set)
    pos_weight = torch.tensor(
        min(config.max_pos_weight, (1 - fraction) / max(fraction, 1e-6)), device=device
    )
    built = model_factory(config, device)
    model = built.module
    optimizer = torch.optim.AdamW(
        built.trainable.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    val_cache: list[torch.Tensor] | None = [] if isinstance(model, DinoProbe) else None
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, config.epochs))
    shuffle = torch.Generator().manual_seed(config.seed)

    run_dir = runs_root / config.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    log = (run_dir / "train.log").open("w", encoding="utf-8")
    best_iou, best_epoch, waited = -1.0, 0, 0
    history: list[dict[str, float | int | None]] = []
    started = time.perf_counter()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    for epoch in range(1, config.epochs + 1):
        model.train()
        total = 0.0
        for x, y, valid in _batches(train_set, config.batch_size, shuffle):
            x, y, valid = x.to(device), y.to(device), valid.to(device)
            optimizer.zero_grad(set_to_none=True)
            with _autocast(device, config.amp):
                logits = _logits(model, x, 0, None)
            loss = _loss(logits.float(), y, valid, pos_weight)
            torch.autograd.backward(loss)
            optimizer.step()
            total += float(loss.detach()) * x.shape[0]
        scheduler.step()
        val = _score(_probabilities(model, val_set, device, config.amp, val_cache), val_set, 0.5)
        entry = {
            "epoch": epoch,
            "train_loss": total / len(train_set),
            "val_iou@0.5": val["iou"],
            "val_boundary_f1@0.5": val["boundary_f1"],
        }
        history.append(entry)
        log.write(json.dumps(entry) + "\n")
        log.flush()
        iou = float(val["iou"] or 0.0)
        if iou > best_iou:
            best_iou, best_epoch, waited = iou, epoch, 0
            torch.save(built.trainable.state_dict(), run_dir / "best.pt")
        else:
            waited += 1
            if waited >= config.patience:
                break
    log.close()
    elapsed = time.perf_counter() - started

    built.trainable.load_state_dict(
        torch.load(run_dir / "best.pt", map_location=device, weights_only=True)
    )
    probabilities = _probabilities(model, val_set, device, config.amp, val_cache)
    sweep = {threshold: _score(probabilities, val_set, threshold) for threshold in THRESHOLDS}
    threshold = max(
        THRESHOLDS, key=lambda value: (float(sweep[value]["iou"] or 0.0), -abs(value - 0.5))
    )

    metrics = {
        "val": sweep[threshold],
        "val_threshold_sweep_iou": {str(key): value["iou"] for key, value in sweep.items()},
        "best_epoch": best_epoch,
        "epochs_run": len(history),
        "train_seconds": round(elapsed, 1),
        "peak_memory_mib": round(torch.cuda.max_memory_allocated(device) / 2**20, 1)
        if device.type == "cuda"
        else None,
    }
    (run_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    record = runrecord.RunRecord(
        run_id=config.run_id,
        task="slab_segmentation",
        dataset_fingerprint=build.tiles_sha256,
        split_sha256=build.split_sha256,
        architecture=f"{built.name} ({parameter_count(built.trainable)} обучаемых параметров)",
        initialization=built.initialization,
        seed=config.seed,
        preprocessing={
            "input": "тайл 1 024 px рабочего растра, яркость /255",
            "valid_region": "без заливки",
            "encoder_input": "заливка белым до кратного 14, 3 канала, нормировка ImageNet"
            if isinstance(model, DinoProbe)
            else "нет",
        },
        augmentation={"rot90": "k ∈ {0,1,2,3}", "horizontal_flip": 0.5},
        training={
            **asdict(config),
            "device": str(device),
            "device_name": torch.cuda.get_device_name(device)
            if device.type == "cuda"
            else platform.processor(),
            "cuda": str(torch.version.cuda),
            "pos_weight": round(float(pos_weight), 3),
            "positive_fraction_train": round(fraction, 6),
            "train_tiles": len(train_set),
            "val_tiles": len(val_set),
            "frozen_threshold": threshold,
            "history": history,
        },
        software=runrecord.software_versions(),
        source_state=runrecord.source_state(Path(__file__).resolve().parents[3]),
        weights=[runrecord.Weights("best.pt", runrecord.sha256_file(run_dir / "best.pt"))],
        metrics=metrics,
    )
    runrecord.write(record, run_dir)
    return run_dir


def evaluate(
    build_dir: Path,
    run_dir: Path,
    *,
    split: str = "test",
    device_choice: str = "auto",
    model_factory: ModelFactory = build_model,
) -> dict[str, object]:
    """Оценка на замороженной части. Порог и веса — из `run.json`; test здесь ничего не выбирает."""
    with torch.no_grad():
        return _evaluate(
            build_dir, run_dir, split=split, device_choice=device_choice, factory=model_factory
        )


def _evaluate(
    build_dir: Path, run_dir: Path, *, split: str, device_choice: str, factory: ModelFactory
) -> dict[str, object]:
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if runrecord.sha256_file(run_dir / "best.pt") != record["weights"][0]["sha256"]:
        raise ValueError("веса изменены после обучения")
    build = load_build(build_dir)
    if (
        build.split_sha256 != record["split_sha256"]
        or build.tiles_sha256 != record["dataset_fingerprint"]
    ):
        raise ValueError("сборка не та, на которой обучалась модель")
    if split == "test" and (run_dir / "test-metrics.json").exists():
        raise ValueError("test уже оценён этим прогоном; повторная оценка не выполняется")

    training = record["training"]
    device = _device(device_choice)
    # Прогоны промта 10 записаны до выбора архитектуры: у них её поле отсутствует — это tiny-unet.
    config = TrainConfig(
        run_id=str(record["run_id"]),
        base_width=int(training["base_width"]),
        depth=int(training["depth"]),
        architecture=str(training.get("architecture", "tiny-unet")),
        encoder=str(training.get("encoder", "large")),
        head_width=int(training.get("head_width", 256)),
    )
    built = factory(config, device)
    built.trainable.load_state_dict(
        torch.load(run_dir / "best.pt", map_location=device, weights_only=True)
    )
    model = built.module
    model.eval()
    amp = str(training["amp"])
    dataset = SlabTiles(
        [tile for tile in build.tiles if tile.split == split], augment=False, seed=0
    )

    def predict(_: TileRef, x: torch.Tensor) -> torch.Tensor:
        with _autocast(device, amp):
            logits = _logits(model, x.unsqueeze(0).to(device), 0, None)
        return torch.sigmoid(logits.float()).cpu()[0]

    output = evaluate_predictor(
        dataset,
        predict,
        threshold=float(training["frozen_threshold"]),
        device=device,
        predictions_dir=run_dir / "predictions" / split,
    )
    return save_outputs(run_dir, split, output, {"run_id": record["run_id"]})
