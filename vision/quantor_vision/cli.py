"""Единые точки входа ML-контура.

```text
vision dataset verify <сборка>      проверка сборки промта 08: хеши split/tiles/views, утечка
vision licenses-check [--root DIR]  лицензионный гейт по всем манифестам репозитория
vision environment                  что есть в окружении: модули, GPU, решения
vision train ...                    промт 10/15   — малая сегментация / осевая кладки
vision qwen-build-sft ...           промт 12      — SFT-наборы из видов Qwen промта 08
vision qwen-train ...               промт 13      — SFT Qwen3-VL
vision qwen-evaluate ...            промт 14      — прямая геометрия и Qwen→SAM
vision evaluate ...                 промты 10–18  — метрики на frozen test
vision infer ...                    промт 20      — доверенный исполнитель (после PASS 18)
vision vectorize ...                промты 16–17  — маска → вектор
```

Команды обучения и оценки пока не реализованы: они проверяют окружение и сообщают BLOCKED с
причинами — модулей нет, GPU нет, лицензия не решена. Реализация — в своих промтах.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path

from quantor_vision import licenses
from quantor_vision.environment import (
    BLOCKED_EXIT,
    Requirement,
    blockers,
    missing_modules,
    nvidia_gpus,
)

VISION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = VISION_ROOT.parent
DECISIONS = VISION_ROOT / "licenses" / "decisions.json"

REQUIREMENTS: dict[str, tuple[Requirement, str]] = {
    "train": (Requirement(("torch", "torchvision"), needs_gpu=True), "промт 10 / 15"),
    "qwen-build-sft": (Requirement((), needs_gpu=False), "промт 12"),
    "qwen-train": (
        Requirement(("torch", "transformers", "peft", "trl"), needs_gpu=True),
        "промт 13",
    ),
    "qwen-evaluate": (Requirement(("torch", "transformers"), needs_gpu=True), "промт 14"),
    "evaluate": (Requirement(("torch",), needs_gpu=False), "промты 10–18"),
    "infer": (Requirement(("torch",), needs_gpu=False), "промт 20 — только после PASS промта 18"),
    "vectorize": (Requirement(("cv2",), needs_gpu=False), "промты 16–17"),
}


def _print(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_build(build_dir: Path) -> list[str]:
    """Сборка промта 08 годится для обучения: хеши сходятся, утечки нет, разбиение заморожено."""
    problems: list[str] = []
    manifest_path = build_dir / "build.json"
    split_path = build_dir / "split.json"
    if not manifest_path.is_file() or not split_path.is_file():
        return ["нет build.json или split.json"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    split = json.loads(split_path.read_text(encoding="utf-8"))

    body = {key: value for key, value in split.items() if key != "sha256"}
    digest = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    ).hexdigest()
    if digest != split.get("sha256") or digest != manifest.get("split_sha256"):
        problems.append("SHA-256 разбиения не сходится с split.json или build.json")
    if _sha256(build_dir / "tiles.jsonl") != manifest.get("tiles_sha256"):
        problems.append("tiles.jsonl изменён после сборки")
    for name, expected in dict(manifest.get("views_sha256", {})).items():
        if _sha256(build_dir / "views" / f"{name}.jsonl") != expected:
            problems.append(f"вид {name} изменён после сборки")
    leakage = manifest.get("leakage", {})
    if not leakage or not all(leakage.values()):
        problems.append(f"проверки утечки не пройдены: {leakage}")
    if split.get("holdout") != "within-project grouped holdout":
        problems.append("разбиение не помечено как within-project grouped holdout")
    return problems


def _dataset(args: argparse.Namespace) -> int:
    problems = verify_build(Path(args.build))
    _print({"ok": not problems, "problems": problems})
    return 0 if not problems else 1


def _licenses(args: argparse.Namespace) -> int:
    violations = licenses.check(Path(args.root), DECISIONS)
    _print(
        {
            "ok": not violations,
            "violations": [f"{v.manifest}: {v.package} — {v.reason}" for v in violations],
        }
    )
    return 0 if not violations else 1


def _environment(_: argparse.Namespace) -> int:
    modules = ("torch", "torchvision", "transformers", "peft", "trl", "sam2", "cv2")
    _print(
        {
            "gpus": nvidia_gpus(),
            "missing_modules": missing_modules(modules),
            "blocked_by_license": sorted(
                name
                for name, decision in licenses.load_decisions(DECISIONS).items()
                if decision == "blocked"
            ),
        }
    )
    return 0


def _pending(args: argparse.Namespace) -> int:
    requirement, prompt = REQUIREMENTS[args.command]
    reasons = blockers(requirement)
    status = "BLOCKED" if reasons else "NOT_IMPLEMENTED"
    _print(
        {
            "command": args.command,
            "prompt": prompt,
            "status": status,
            "reasons": reasons or ["реализуется в своём промте"],
        }
    )
    return BLOCKED_EXIT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vision", description="ML-контур Quantor Stage 2B")
    commands = parser.add_subparsers(dest="command", required=True)

    dataset = commands.add_parser("dataset", help="операции над сборкой датасета")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    verify = dataset_commands.add_parser("verify", help="проверить сборку промта 08")
    verify.add_argument("build")
    verify.set_defaults(handler=_dataset)

    gate = commands.add_parser("licenses-check", help="лицензионный гейт манифестов")
    gate.add_argument("--root", default=str(REPO_ROOT))
    gate.set_defaults(handler=_licenses)

    commands.add_parser("environment", help="модули, GPU, решения").set_defaults(
        handler=_environment
    )

    for name in REQUIREMENTS:
        pending = commands.add_parser(name, help=f"{REQUIREMENTS[name][1]}")
        pending.set_defaults(handler=_pending, accepts_unknown=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Отчёты — JSON в UTF-8: консоль Windows в cp1251 не выводит часть символов причин.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    # Аргументы будущих команд обучения ещё не описаны: сейчас они принимаются и игнорируются,
    # а команда честно отвечает BLOCKED. Остальным командам лишние аргументы — ошибка.
    args, unknown = parser.parse_known_args(argv)
    if unknown and not getattr(args, "accepts_unknown", False):
        parser.error("неизвестные аргументы: " + " ".join(unknown))
    code: int = args.handler(args)
    return code
