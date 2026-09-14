"""Конфигурация сборки датасета. Отпечаток конфига — часть замороженного разбиения.

Пути в конфиге могут ссылаться на `${QUANTOR_DATASET_ROOT}`: пример в git не содержит частных путей,
а на машине с данными переменная раскрывается.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

TASKS = ("slab", "masonry")
SPLITS = ("train", "val", "test")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetRef:
    project_key: str
    dataset_dir: str
    source_root: str
    tasks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetConfig:
    kinds: tuple[str, ...]
    # Метки позиций PlanSwift, входящие в цель; пусто — все аннотации указанных видов.
    labels: tuple[str, ...] = ()
    # Доля пикселей цели в тайле, с которой тайл считается положительным.
    min_positive_fraction: float = 0.001
    # Только для осевой: радиус спада цели в пикселях рабочего растра.
    radius_px: float = 6.0


@dataclass(frozen=True, slots=True)
class BuildConfig:
    build_id: str
    seed: int
    datasets: tuple[DatasetRef, ...]
    downsample: int = 2
    tile_px: int = 1024
    overlap_px: int = 128
    pad_value: int = 255
    targets: dict[str, TargetConfig] = field(default_factory=dict)
    train_negative_ratio: float = 0.3
    hard_negative_ink_fraction: float = 0.02
    train_positive_crops_per_page: int = 8
    split_fractions: dict[str, float] = field(
        default_factory=lambda: {"train": 0.7, "val": 0.15, "test": 0.15}
    )
    phash_hamming_threshold: int = 10
    qwen_coordinate_range: int = 1000
    qwen_masonry_guide_points: int = 8

    def fingerprint(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def split_fingerprint(self) -> str:
        """Отпечаток того, от чего зависит разбиение. Смена размера тайла разбиение не меняет."""
        payload = json.dumps(
            {
                "seed": self.seed,
                "datasets": [(d.project_key, d.tasks) for d in self.datasets],
                "fractions": self.split_fractions,
                "phash_hamming_threshold": self.phash_hamming_threshold,
                "downsample": self.downsample,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expand(value: str) -> str:
    if "${" in value:
        root = os.environ.get("QUANTOR_DATASET_ROOT")
        if root is None:
            raise ConfigError(f"{value}: не задана переменная QUANTOR_DATASET_ROOT")
        value = value.replace("${QUANTOR_DATASET_ROOT}", root)
    return value


def load(path: Path) -> BuildConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        datasets = tuple(
            DatasetRef(
                project_key=str(item["project_key"]),
                dataset_dir=_expand(str(item["dataset_dir"])),
                source_root=_expand(str(item["source_root"])),
                tasks=tuple(str(task) for task in item["tasks"]),
            )
            for item in raw["datasets"]
        )
        targets = {
            str(name): TargetConfig(
                kinds=tuple(spec["kinds"]),
                labels=tuple(spec.get("labels") or ()),
                min_positive_fraction=float(spec.get("min_positive_fraction", 0.001)),
                radius_px=float(spec.get("radius_px", 6.0)),
            )
            for name, spec in raw["targets"].items()
        }
        options = {
            key: value for key, value in raw.items() if key not in ("datasets", "targets", "_note")
        }
        config = BuildConfig(datasets=datasets, targets=targets, **options)
    except (KeyError, TypeError) as error:
        raise ConfigError(f"{path}: {error}") from error
    _check(config)
    return config


def _check(config: BuildConfig) -> None:
    for dataset in config.datasets:
        for task in dataset.tasks:
            if task not in TASKS or task not in config.targets:
                raise ConfigError(f"{dataset.project_key}: задача {task!r} не описана в targets")
    if (
        set(config.split_fractions) != set(SPLITS)
        or abs(sum(config.split_fractions.values()) - 1) > 1e-9
    ):
        raise ConfigError("split_fractions: нужны train/val/test с суммой 1")
    if not 0 <= config.overlap_px < config.tile_px:
        raise ConfigError("overlap_px должен быть меньше tile_px")
    if config.downsample < 1:
        raise ConfigError("downsample — целое ≥ 1")
