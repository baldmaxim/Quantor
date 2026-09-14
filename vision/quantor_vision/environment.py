"""Что есть в окружении для команды: extras, GPU, лицензионные решения.

Команда, для которой чего-то не хватает, не делает вид, что работает: она печатает BLOCKED с
причинами и завершается кодом 3. «Нет GPU» и «нет решения по лицензии» — разные причины, и обе
видны.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass

BLOCKED_EXIT = 3


@dataclass(frozen=True, slots=True)
class Requirement:
    modules: tuple[str, ...]
    needs_gpu: bool
    blocked_by_license: tuple[str, ...] = ()


def missing_modules(modules: tuple[str, ...]) -> list[str]:
    return [name for name in modules if importlib.util.find_spec(name) is None]


def nvidia_gpus() -> list[str]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    try:
        output = subprocess.run(
            [executable, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def blockers(requirement: Requirement) -> list[str]:
    reasons: list[str] = []
    missing = missing_modules(requirement.modules)
    if missing:
        reasons.append("не установлены модули: " + ", ".join(missing))
    if requirement.needs_gpu and not nvidia_gpus():
        reasons.append("нет NVIDIA GPU (nvidia-smi не нашёл устройств)")
    for package in requirement.blocked_by_license:
        reasons.append(f"лицензия: «{package}» заблокирован в vision/licenses/decisions.json")
    return reasons
