"""Лицензионный гейт: ни одна зависимость ML не попадает в манифест без решения в матрице.

Проверяются все манифесты репозитория — `pyproject.toml`, `requirements*.txt`, `package.json` —
а не только `apps/api`. Пакет из «охраняемого» списка (фреймворки обучения, модели, VLM-стек)
допускается в манифесте только при решении `allow` или `conditional`; `blocked` и отсутствие
решения — нарушение. Ultralytics и Unsloth сейчас `blocked`.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Пакеты, для которых решение обязательно. Любой из них в любом манифесте без строки
# allow/conditional в decisions.json — нарушение.
GUARDED = (
    "ultralytics",
    "unsloth",
    "unsloth-zoo",
    "torch",
    "torchvision",
    "sam2",
    "mobile-sam",
    "segment-anything",
    "transformers",
    "peft",
    "trl",
    "accelerate",
    "bitsandbytes",
    "opencv-python",
    "opencv-python-headless",
    "opencv-contrib-python",
    "segmentation-models-pytorch",
    "timm",
    "shapely",
    "pypdfium2",
    "onnxruntime",
    "vllm",
)
ALLOWED_DECISIONS = ("allow", "conditional")
SKIP_DIRS = {"node_modules", ".venv", ".git", ".next", "dist", "build", "__pycache__", "_prompts"}


@dataclass(frozen=True, slots=True)
class Violation:
    manifest: str
    package: str
    reason: str


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(spec: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", spec)
    return normalize(match.group(1)) if match else ""


def declared_in_pyproject(path: Path) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        specs.extend(extra)
    for group in data.get("dependency-groups", {}).values():
        specs.extend(item for item in group if isinstance(item, str))
    return [_requirement_name(spec) for spec in specs]


def declared_in_requirements(path: Path) -> list[str]:
    names = []
    # utf-8-sig: снимок `pip freeze`, сохранённый из PowerShell, начинается с BOM, и без этого
    # первый пакет списка молча выпал бы из проверки.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped and not stripped.startswith("-"):
            names.append(_requirement_name(stripped))
    return names


def declared_in_package_json(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        names.extend(normalize(name) for name in data.get(section, {}))
    return names


def manifests(root: Path) -> list[Path]:
    """Манифесты репозитория; node_modules, окружения и сборки не обходятся вовсе."""
    found: list[Path] = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(name for name in subdirectories if name not in SKIP_DIRS)
        for name in files:
            if name in ("pyproject.toml", "package.json") or re.fullmatch(
                r"requirements.*\.txt", name
            ):
                found.append(Path(directory) / name)
    return sorted(found)


def load_decisions(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    packages = data.get("packages", {})
    return {normalize(name): str(entry.get("decision", "")) for name, entry in packages.items()}


def check(root: Path, decisions_path: Path) -> list[Violation]:
    decisions = load_decisions(decisions_path)
    guarded = {normalize(name) for name in GUARDED}
    violations: list[Violation] = []
    for manifest in manifests(root):
        if manifest.name == "pyproject.toml":
            names = declared_in_pyproject(manifest)
        elif manifest.name == "package.json":
            names = declared_in_package_json(manifest)
        else:
            names = declared_in_requirements(manifest)
        relative = manifest.relative_to(root).as_posix()
        for name in sorted(set(names) & guarded):
            decision = decisions.get(name)
            if decision is None:
                violations.append(Violation(relative, name, "нет решения в матрице лицензий"))
            elif decision not in ALLOWED_DECISIONS:
                violations.append(Violation(relative, name, f"решение «{decision}»"))
    return violations
