"""Командная строка импортёра: inspect, convert, validate, stats.

```bash
python -m planswift_gt inspect  <каталог|архив.7z> [--work-dir DIR]
python -m planswift_gt convert  <каталог|архив.7z> --project-key KEY [--out DIR] [--dataset-id ID]
python -m planswift_gt validate <каталог результата> [--source <каталог проекта>]
python -m planswift_gt stats    <каталог результата> [--expect ожидания.json]
python -m planswift_gt qa       <каталог результата> --source <проект> --out <каталог оверлеев>
python -m planswift_gt card     <каталог результата> [--qa-report qa-report.json] [--out card.md]
```

Корень частных данных — `--out` или переменная `QUANTOR_DATASET_ROOT`. Писать результат внутрь
git-репозитория инструмент отказывается: частные данные туда не попадают даже по ошибке.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from planswift_gt import FORMAT, buildconfig, card, qa
from planswift_gt import build as dataset_build
from planswift_gt.archive import ArchiveRejectedError, extract
from planswift_gt.manifest import (
    compare_expectations,
    findings,
    stats,
    summary,
    validate,
    write,
)
from planswift_gt.parser import ProjectRejectedError, parse_project
from planswift_gt.splits import SplitFrozenError

DATASET_ROOT_ENV = "QUANTOR_DATASET_ROOT"


def _print(value: object) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _inside_git_worktree(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _source(args: argparse.Namespace) -> Path:
    source = Path(args.source)
    if source.suffix.lower() != ".7z":
        return source
    if args.work_dir is None:
        raise ArchiveRejectedError("для .7z нужен --work-dir: каталог распаковки вне репозитория")
    work_dir = Path(args.work_dir)
    repo = _inside_git_worktree(work_dir)
    if repo is not None:
        raise ArchiveRejectedError(
            f"--work-dir внутри git-репозитория {repo}: частные данные туда не кладутся"
        )
    return extract(source, work_dir)


def _inspect(args: argparse.Namespace) -> int:
    result = parse_project(_source(args))
    _print({"project_name": result.project_name, **summary(result)})
    return 0


def _convert(args: argparse.Namespace) -> int:
    if args.out is not None:
        out = Path(args.out)
    elif os.environ.get(DATASET_ROOT_ENV):
        out = Path(os.environ[DATASET_ROOT_ENV]) / FORMAT / args.project_key
    else:
        sys.stderr.write(f"Укажите --out или {DATASET_ROOT_ENV}\n")
        return 2
    repo = _inside_git_worktree(out)
    if repo is not None and not args.allow_inside_repo:
        sys.stderr.write(f"{out} внутри git-репозитория {repo}: частные данные туда не пишутся\n")
        return 2

    result = parse_project(_source(args))
    manifest = write(
        result,
        out,
        dataset_id=args.dataset_id or f"{FORMAT}:{args.project_key}",
        project_key=args.project_key,
    )
    _print({"out": str(out), "summary": manifest["summary"]})
    return 0


def _validate(args: argparse.Namespace) -> int:
    dataset = Path(args.dataset)
    problems = [
        f"{p.where}: {p.message}"
        for p in validate(dataset, source_root=Path(args.source) if args.source else None)
    ]
    report: dict[str, object] = {}
    if args.reparse:
        # Повторный разбор источника во временный каталог: тот же вход обязан дать тот же отпечаток.
        manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="planswift-reparse-") as scratch:
            again = write(
                parse_project(Path(args.reparse)),
                Path(scratch),
                dataset_id=str(manifest["dataset_id"]),
                project_key=str(manifest["project_key"]),
            )
        same = again["dataset_fingerprint"] == manifest.get("dataset_fingerprint")
        report["reparse_dataset_fingerprint"] = again["dataset_fingerprint"]
        report["reparse_matches"] = same
        if not same:
            problems.append("reparse: отпечаток повторного разбора отличается от записанного")
        if again["source_fingerprint"] != manifest.get("source_fingerprint"):
            problems.append("reparse: источник изменился с момента импорта")
    report["findings"] = findings(dataset)
    _print({"ok": not problems, "problems": problems, **report})
    return 0 if not problems else 1


def _qa(args: argparse.Namespace) -> int:
    out = Path(args.out)
    repo = _inside_git_worktree(out)
    if repo is not None and not args.allow_inside_repo:
        sys.stderr.write(f"{out} внутри git-репозитория {repo}: оверлеи чертежей туда не пишутся\n")
        return 2
    summary_value = qa.run(
        Path(args.dataset),
        Path(args.source),
        out,
        debug_pages=args.debug_pages,
        max_side=args.max_side,
    )
    _print({key: value for key, value in summary_value.items() if key != "pages_report"})
    return 0


def _build(args: argparse.Namespace) -> int:
    out = Path(args.out)
    repo = _inside_git_worktree(out)
    if repo is not None and not args.allow_inside_repo:
        sys.stderr.write(f"{out} внутри git-репозитория {repo}: тайлы чертежей туда не пишутся\n")
        return 2
    try:
        config = buildconfig.load(Path(args.config))
        manifest = dataset_build.build(config, out, refreeze=args.refreeze)
    except (buildconfig.ConfigError, SplitFrozenError) as error:
        sys.stderr.write(f"{error}\n")
        return 2
    _print(manifest)
    leakage = manifest.get("leakage")
    return 0 if isinstance(leakage, dict) and all(leakage.values()) else 1


def _card(args: argparse.Namespace) -> int:
    text = card.build(
        Path(args.dataset), qa_report=Path(args.qa_report) if args.qa_report else None
    )
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def _stats(args: argparse.Namespace) -> int:
    report = stats(Path(args.dataset))
    if args.expect:
        expectations = json.loads(Path(args.expect).read_text(encoding="utf-8"))
        project = expectations.get(str(report.get("project_key")), {})
        summary_value = report.get("summary")
        rows = compare_expectations(
            summary_value if isinstance(summary_value, dict) else {}, project
        )
        report["expectations"] = [
            {
                "metric": row.metric,
                "expected": row.expected,
                "actual": row.actual,
                "tolerance": row.tolerance,
                "within": row.within,
            }
            for row in rows
        ]
    _print(report)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planswift_gt", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="сводка проекта без записи")
    inspect.add_argument("source")
    inspect.add_argument("--work-dir")
    inspect.set_defaults(handler=_inspect)

    convert = commands.add_parser("convert", help="записать planswift-gt-v1")
    convert.add_argument("source")
    convert.add_argument("--project-key", required=True)
    convert.add_argument("--dataset-id")
    convert.add_argument("--out")
    convert.add_argument("--work-dir")
    convert.add_argument(
        "--allow-inside-repo", action="store_true", help="только для синтетики в тестах"
    )
    convert.set_defaults(handler=_convert)

    check = commands.add_parser("validate", help="проверить каталог результата")
    check.add_argument("dataset")
    check.add_argument("--source", help="корень проекта: перепроверить хеши растров")
    check.add_argument(
        "--reparse", help="распакованный проект: разобрать заново и сверить отпечаток"
    )
    check.set_defaults(handler=_validate)

    review = commands.add_parser("qa", help="оверлеи листов и проверка совмещения с растром")
    review.add_argument("dataset")
    review.add_argument("--source", required=True, help="корень проекта с растрами")
    review.add_argument("--out", required=True)
    review.add_argument("--debug-pages", type=int, default=3)
    review.add_argument("--max-side", type=int, default=2400)
    review.add_argument("--allow-inside-repo", action="store_true", help="только для синтетики")
    review.set_defaults(handler=_qa)

    assemble = commands.add_parser("build", help="тайлы, цели, замороженное разбиение, виды Qwen")
    assemble.add_argument("config")
    assemble.add_argument("--out", required=True)
    assemble.add_argument("--refreeze", action="store_true", help="пересобрать разбиение явно")
    assemble.add_argument("--allow-inside-repo", action="store_true", help="только для синтетики")
    assemble.set_defaults(handler=_build)

    describe = commands.add_parser("card", help="карточка датасета без изображений")
    describe.add_argument("dataset")
    describe.add_argument("--qa-report")
    describe.add_argument("--out")
    describe.set_defaults(handler=_card)

    report = commands.add_parser("stats", help="сводка и сверка с ожиданиями")
    report.add_argument("dataset")
    report.add_argument("--expect", help="JSON ожиданий по project_key")
    report.set_defaults(handler=_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code: int = args.handler(args)
    except (ProjectRejectedError, ArchiveRejectedError) as error:
        sys.stderr.write(f"{error}\n")
        return 2
    return code
