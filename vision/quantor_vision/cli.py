"""Единые точки входа ML-контура.

```text
vision dataset verify <сборка>      проверка сборки промта 08: хеши split/tiles/views, утечка
vision licenses-check [--root DIR]  лицензионный гейт по всем манифестам репозитория
vision environment                  что есть в окружении: модули, GPU, решения
vision train slab --build DIR       промт 10      — малая сегментация плиты (masonry — промт 15)
vision qwen-build-sft --build --out промт 12      — SFT-наборы Qwen из сборки промта 08
vision qwen-env probe|fetch|smoke   промт 12      — GPU и BF16, закреплённые веса, дымовой прогон
vision qwen-train ...               промт 13      — SFT Qwen3-VL
vision qwen-evaluate ...            промт 14      — прямая геометрия и Qwen→SAM
vision evaluate slab --build --run  промт 10      — метрики на frozen test, один раз
vision infer ...                    промт 20      — доверенный исполнитель (после PASS 18)
vision vectorize slab --build --run промт 16      — маска → многоугольник с отверстиями, метрики
vision sam run --policy auto|coarse промт 11      — SAM 2: val настраивает, test один раз
```

Команды обучения и оценки пока не реализованы: они проверяют окружение и сообщают BLOCKED с
причинами — модулей нет, GPU нет, лицензия не решена. Реализация — в своих промтах.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
from datetime import UTC, datetime
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
    "train masonry": (Requirement(("torch", "torchvision"), needs_gpu=True), "промт 15"),
    "qwen-train": (
        Requirement(("torch", "transformers", "peft", "trl"), needs_gpu=True),
        "промт 13",
    ),
    "qwen-evaluate": (Requirement(("torch", "transformers"), needs_gpu=True), "промт 14"),
    "evaluate masonry": (Requirement(("torch",), needs_gpu=False), "промты 15–18"),
    "infer": (Requirement(("torch",), needs_gpu=False), "промт 20 — только после PASS промта 18"),
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
    # v1 — листы одного проекта; v2 (Р-9) — семейства объектов целиком.
    if split.get("holdout") not in ("within-project grouped holdout", "project-family holdout"):
        problems.append("вид разбиения не распознан")
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
    key = args.command if args.command in REQUIREMENTS else f"{args.command} {args.task}"
    requirement, prompt = REQUIREMENTS[key]
    reasons = blockers(requirement)
    status = "BLOCKED" if reasons else "NOT_IMPLEMENTED"
    _print(
        {
            "command": key,
            "prompt": prompt,
            "status": status,
            "reasons": reasons or ["реализуется в своём промте"],
        }
    )
    return BLOCKED_EXIT


def _inside_git_worktree(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _runs_root(value: str | None) -> Path | None:
    if value:
        return Path(value)
    root = os.environ.get("QUANTOR_DATASET_ROOT")
    return Path(root) / "runs" if root else None


def _blocked(command: str, reasons: list[str]) -> int:
    _print({"command": command, "status": "BLOCKED", "reasons": reasons})
    return BLOCKED_EXIT


def _train_slab(args: argparse.Namespace) -> int:
    reasons = blockers(Requirement(("torch",), needs_gpu=False))
    if not args.allow_cpu and not nvidia_gpus():
        reasons.append("нет NVIDIA GPU; дымовой прогон на CPU — только с --allow-cpu")
    runs = _runs_root(args.runs)
    if runs is None:
        reasons.append("не задан --runs и нет QUANTOR_DATASET_ROOT")
    elif _inside_git_worktree(runs) is not None and not args.allow_inside_repo:
        reasons.append(f"{runs} внутри git-репозитория: веса и прогнозы туда не пишутся")
    if reasons or runs is None:
        return _blocked("train slab", reasons)

    from quantor_vision.slab.train import TrainConfig, train

    run_id = args.run_id or "slab-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    config = TrainConfig(
        run_id=run_id,
        seed=args.seed,
        epochs=args.epochs,
        patience=args.patience,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        base_width=args.base,
        amp=args.amp,
        limit_tiles=args.limit_tiles,
        device=args.device,
        architecture=args.arch,
        encoder=args.encoder,
        head_width=args.head_width,
    )
    run_dir = train(Path(args.build), runs, config)
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    _print({"run_dir": str(run_dir), "val": metrics["val"], "best_epoch": metrics["best_epoch"]})
    return 0


def _evaluate_slab(args: argparse.Namespace) -> int:
    reasons = blockers(Requirement(("torch",), needs_gpu=False))
    if reasons:
        return _blocked("evaluate slab", reasons)

    from quantor_vision.slab.train import evaluate

    try:
        result = evaluate(
            Path(args.build), Path(args.run), split=args.split, device_choice=args.device
        )
    except ValueError as error:
        _print({"command": "evaluate slab", "status": "REFUSED", "reason": str(error)})
        return 2
    _print(result)
    return 0


def _sam_run(args: argparse.Namespace) -> int:
    reasons = blockers(Requirement(("torch", "transformers"), needs_gpu=False))
    if not args.allow_cpu and not nvidia_gpus():
        reasons.append("нет NVIDIA GPU; прогон на CPU — только с --allow-cpu")
    runs = _runs_root(args.runs)
    if runs is None:
        reasons.append("не задан --runs и нет QUANTOR_DATASET_ROOT")
    elif _inside_git_worktree(runs) is not None:
        reasons.append(f"{runs} внутри git-репозитория: прогнозы туда не пишутся")
    if reasons or runs is None:
        return _blocked("sam run", reasons)

    import torch

    from quantor_vision.sam.run import RunRefusedError, run
    from quantor_vision.sam.segmenter import Sam2Segmenter

    config: dict[str, object] = {}
    for item in args.set or []:
        key, _, value = item.partition("=")
        config[key] = float(value) if "." in value else int(value)
    device = torch.device(
        "cuda"
        if args.device == "auto" and torch.cuda.is_available()
        else ("cpu" if args.device == "auto" else args.device)
    )
    try:
        result = run(
            Path(args.build),
            runs,
            run_id=args.run_id,
            split=args.split,
            device=device,
            factory=Sam2Segmenter,
            policy=args.policy,
            model_size=args.model,
            config=config or None,
            coarse_run=Path(args.coarse_run) if args.coarse_run else None,
            new_experiment=args.new_experiment,
            limit_tiles=args.limit_tiles,
        )
    except RunRefusedError as error:
        _print({"command": "sam run", "status": "REFUSED", "reason": str(error)})
        return 2
    _print(result)
    return 0


def _data_subdir(value: str | None, name: str) -> Path | None:
    if value:
        return Path(value)
    root = os.environ.get("QUANTOR_DATASET_ROOT")
    return Path(root) / name if root else None


def _outside_repo(path: Path | None, flag: str, what: str, reasons: list[str]) -> None:
    if path is None:
        reasons.append(f"не задан {flag} и нет QUANTOR_DATASET_ROOT")
    elif _inside_git_worktree(path) is not None:
        reasons.append(f"{path} внутри git-репозитория: {what} туда не пишутся")


def _vectorize_slab(args: argparse.Namespace) -> int:
    reasons = blockers(Requirement(("torch",), needs_gpu=False))
    if reasons:
        return _blocked("vectorize slab", reasons)

    from quantor_vision.vector.polygonize import VectorConfig
    from quantor_vision.vector.run import VectorizeRefusedError, vectorize_run

    overrides = {key: value for key, _, value in (item.partition("=") for item in args.set or [])}
    try:
        config = VectorConfig.with_overrides(overrides)
        result = vectorize_run(
            Path(args.build),
            Path(args.run),
            split=args.split,
            build_config=Path(args.build_config),
            config=config,
            new_experiment=args.new_experiment,
        )
    except (VectorizeRefusedError, ValueError) as error:
        _print({"command": "vectorize slab", "status": "REFUSED", "reason": str(error)})
        return 2
    _print(result)
    return 0


def _qwen_build_sft(args: argparse.Namespace) -> int:
    from quantor_vision.qwen.schema import Limits
    from quantor_vision.qwen.sft import SftConfig, SftRefusedError, build_sft
    from quantor_vision.qwen.targets import TargetConfig

    build = Path(args.build)
    reasons = [] if args.skip_verify else verify_build(build)
    out = Path(args.out)
    _outside_repo(out, "--out", "SFT-наборы", reasons)
    if reasons:
        return _blocked("qwen-build-sft", reasons)
    config = SftConfig(
        targets=TargetConfig(stride=args.stride, min_area_px=args.min_area_px),
        limits=Limits(max_objects=args.max_objects),
    )
    try:
        result = build_sft(build, out, config)
    except SftRefusedError as error:
        _print({"command": "qwen-build-sft", "status": "REFUSED", "reason": str(error)})
        return 2
    _print(
        {"out": str(out), "counters": result["counters"], "anti_leakage": result["anti_leakage"]}
    )
    return 0


def _qwen_env(args: argparse.Namespace) -> int:
    from quantor_vision.qwen import environment

    if args.env_command == "probe":
        report = environment.probe()
        _print(report)
        return 0 if report["status"] == "OK" else BLOCKED_EXIT

    models = _data_subdir(args.models, "models")
    reasons: list[str] = []
    _outside_repo(models, "--models", "веса", reasons)
    if args.env_command == "fetch":
        reasons.extend(blockers(Requirement(("huggingface_hub",), needs_gpu=False)))
        if reasons or models is None:
            return _blocked("qwen-env fetch", reasons)
        result = environment.fetch(args.model, models)
        _print(result)
        return 0 if result["verified"] else 1

    modules = ("torch", "transformers", "PIL") + (("unsloth",) if args.backend == "unsloth" else ())
    reasons.extend(blockers(Requirement(modules, needs_gpu=True)))
    runs = _data_subdir(args.runs, "runs")
    _outside_repo(runs, "--runs", "записи прогонов", reasons)
    if reasons or models is None or runs is None:
        return _blocked("qwen-env smoke", reasons)
    record = environment.smoke(
        model_key=args.model,
        backend=args.backend,
        quantization=args.quantization,
        models_root=models,
        out_dir=runs / "qwen-env",
        max_new_tokens=args.max_new_tokens,
    )
    printable = {key: value for key, value in record.items() if key != "traceback"}
    _print(printable)
    return 0 if record["status"] == "OK" else BLOCKED_EXIT


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

    trainer = commands.add_parser("train", help="обучение: slab — промт 10, masonry — промт 15")
    train_tasks = trainer.add_subparsers(dest="task", required=True)
    slab = train_tasks.add_parser("slab", help="малый U-Net плиты на сборке промта 08")
    slab.add_argument("--build", required=True)
    slab.add_argument("--runs", help="каталог прогонов; по умолчанию $QUANTOR_DATASET_ROOT/runs")
    slab.add_argument("--run-id")
    slab.add_argument("--seed", type=int, default=20260914)
    slab.add_argument("--epochs", type=int, default=60)
    slab.add_argument("--patience", type=int, default=10)
    slab.add_argument("--batch-size", type=int, default=4)
    slab.add_argument("--lr", type=float, default=2e-3)
    slab.add_argument("--base", type=int, default=16)
    slab.add_argument("--amp", choices=("bf16", "off"), default="bf16")
    slab.add_argument(
        "--limit-tiles", type=int, default=0, help="дымовой прогон: N тайлов на часть"
    )
    slab.add_argument("--device", default="auto")
    slab.add_argument(
        "--arch",
        choices=("tiny-unet", "dinov2-probe"),
        default="tiny-unet",
        help="tiny-unet — промт 10; dinov2-probe — замороженный DINOv2 + голова (Р-8)",
    )
    slab.add_argument("--encoder", choices=("large", "base"), default="large")
    slab.add_argument("--head-width", type=int, default=256)
    slab.add_argument("--allow-cpu", action="store_true", help="разрешить обучение без GPU")
    slab.add_argument("--allow-inside-repo", action="store_true", help="только для тестов")
    slab.set_defaults(handler=_train_slab)
    train_tasks.add_parser("masonry", help="промт 15").set_defaults(
        handler=_pending, accepts_unknown=True
    )

    evaluator = commands.add_parser("evaluate", help="оценка на замороженной части")
    evaluate_tasks = evaluator.add_subparsers(dest="task", required=True)
    slab_eval = evaluate_tasks.add_parser("slab", help="метрики маски плиты и площади листа")
    slab_eval.add_argument("--build", required=True)
    slab_eval.add_argument("--run", required=True)
    slab_eval.add_argument("--split", choices=("val", "test"), default="test")
    slab_eval.add_argument("--device", default="auto")
    slab_eval.set_defaults(handler=_evaluate_slab)
    evaluate_tasks.add_parser("masonry", help="промты 15–18").set_defaults(
        handler=_pending, accepts_unknown=True
    )

    sam = commands.add_parser("sam", help="промт 11: SAM 2 без разметки в подсказках")
    sam_commands = sam.add_subparsers(dest="sam_command", required=True)
    sam_run = sam_commands.add_parser("run", help="прогон политики на val или test")
    sam_run.add_argument("--build", required=True)
    sam_run.add_argument("--runs", help="каталог прогонов; по умолчанию $QUANTOR_DATASET_ROOT/runs")
    sam_run.add_argument("--run-id", required=True)
    sam_run.add_argument("--split", choices=("val", "test"), default="val")
    sam_run.add_argument("--policy", choices=("auto", "coarse"), help="только для нового прогона")
    sam_run.add_argument("--model", choices=("tiny", "small", "base-plus"), default="small")
    sam_run.add_argument("--coarse-run", help="каталог прогона промта 10 для политики coarse")
    sam_run.add_argument("--set", action="append", help="настройка политики: ключ=значение")
    sam_run.add_argument("--new-experiment", help="причина второго test той же политики")
    sam_run.add_argument("--limit-tiles", type=int, default=0, help="дымовой прогон; test запрещён")
    sam_run.add_argument("--device", default="auto")
    sam_run.add_argument("--allow-cpu", action="store_true")
    sam_run.set_defaults(handler=_sam_run)

    vectorize = commands.add_parser("vectorize", help="маска → вектор: slab — промт 16")
    vectorize_tasks = vectorize.add_subparsers(dest="task", required=True)
    vector_slab = vectorize_tasks.add_parser("slab", help="многоугольники плиты и метрики")
    vector_slab.add_argument("--build", required=True)
    vector_slab.add_argument("--run", required=True, help="каталог прогона с predictions/<split>")
    vector_slab.add_argument("--split", choices=("val", "test"), default="val")
    vector_slab.add_argument(
        "--build-config", required=True, help="конфиг сборки 08: пути разметки и метки плит"
    )
    vector_slab.add_argument("--set", action="append", help="настройка: ключ=значение (только val)")
    vector_slab.add_argument("--new-experiment", help="причина повторного test")
    vector_slab.set_defaults(handler=_vectorize_slab)

    sft = commands.add_parser("qwen-build-sft", help="промт 12: SFT-наборы Qwen из сборки 08")
    sft.add_argument("--build", required=True)
    sft.add_argument("--out", required=True, help="пустой каталог вне репозитория")
    sft.add_argument("--stride", type=int, default=4, help="шаг сетки целей, px тайла")
    sft.add_argument("--min-area-px", type=int, default=1024)
    sft.add_argument("--max-objects", type=int, default=16)
    sft.add_argument("--skip-verify", action="store_true", help="только для синтетики в тестах")
    sft.set_defaults(handler=_qwen_build_sft)

    qwen_env = commands.add_parser("qwen-env", help="промт 12: окружение Qwen3-VL")
    env_commands = qwen_env.add_subparsers(dest="env_command", required=True)
    env_commands.add_parser("probe", help="версии, GPU, BF16, телеметрия").set_defaults(
        handler=_qwen_env
    )
    for name, text in (("fetch", "скачать и сверить веса"), ("smoke", "загрузка и один ответ")):
        sub = env_commands.add_parser(name, help=text)
        sub.add_argument("--model", choices=("2b", "4b", "8b"), required=True)
        sub.add_argument("--models", help="каталог весов; иначе $QUANTOR_DATASET_ROOT/models")
        if name == "smoke":
            sub.add_argument("--backend", choices=("transformers", "unsloth"), required=True)
            sub.add_argument("--quantization", choices=("bf16", "4bit"), default="bf16")
            sub.add_argument("--runs", help="по умолчанию $QUANTOR_DATASET_ROOT/runs")
            sub.add_argument("--max-new-tokens", type=int, default=256)
        sub.set_defaults(handler=_qwen_env)

    for name in REQUIREMENTS:
        if " " in name:
            continue
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
