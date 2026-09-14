"""Контракт эксперимента: всё, что нужно, чтобы прогон можно было объяснить и повторить.

Прогон без полной записи — не результат. Запись пишется в каталог прогона как `run.json` и
проверяется `validate`: пустое обязательное поле, неизвестный хеш или несовпадение хеша весов с
файлом делают запись негодной для сравнения моделей (промт 18).
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

RUN_FILE = "run.json"
TRACKED_PACKAGES = (
    "torch",
    "torchvision",
    "transformers",
    "peft",
    "trl",
    "sam2",
    "opencv-python-headless",
    "numpy",
)
TASKS = (
    "slab_segmentation",
    "masonry_centerline",
    "qwen_slab_localization",
    "qwen_masonry_roi",
    "sam_refine",
)


@dataclass(frozen=True, slots=True)
class Weights:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    task: str
    dataset_fingerprint: str
    split_sha256: str
    architecture: str
    # Откуда начальные веса: "scratch" или идентификатор с ревизией и строкой в матрице лицензий.
    initialization: str
    seed: int
    preprocessing: dict[str, object]
    augmentation: dict[str, object]
    training: dict[str, object]
    software: dict[str, str]
    source_state: dict[str, str]
    weights: list[Weights]
    metrics: dict[str, object]
    notes: list[str] = field(default_factory=list)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def software_versions(packages: tuple[str, ...] = TRACKED_PACKAGES) -> dict[str, str]:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name in packages:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return versions


def source_state(root: Path) -> dict[str, str]:
    """Коммит и признак незакоммиченных правок. Нет git — так и записывается, а не пропускается."""
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": "unavailable", "dirty": "unknown"}
    return {"git_commit": head, "dirty": "yes" if dirty else "no"}


def write(record: RunRecord, run_dir: Path) -> Path:
    problems = validate(record, run_dir)
    if problems:
        raise ValueError("запись прогона неполна: " + "; ".join(problems))
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / RUN_FILE
    path.write_text(
        json.dumps(asdict(record), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def validate(record: RunRecord, run_dir: Path) -> list[str]:
    problems: list[str] = []
    for name in ("run_id", "task", "architecture", "initialization"):
        if not getattr(record, name):
            problems.append(f"{name} пусто")
    if record.task not in TASKS:
        problems.append(f"task {record.task!r} не из {TASKS}")
    for name in ("dataset_fingerprint", "split_sha256"):
        value = getattr(record, name)
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            problems.append(f"{name} — не SHA-256")
    if not record.metrics:
        problems.append("metrics пусто")
    if "python" not in record.software:
        problems.append("software без версии python")
    if "git_commit" not in record.source_state:
        problems.append("source_state без git_commit")
    if not record.weights:
        problems.append("нет выходных весов")
    for weight in record.weights:
        path = run_dir / weight.path
        if not path.is_file():
            problems.append(f"вес {weight.path} не найден")
        elif sha256_file(path) != weight.sha256:
            problems.append(f"SHA-256 веса {weight.path} не совпадает")
    return problems


def interpreter() -> str:
    return sys.executable
