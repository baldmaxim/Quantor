"""Командная строка: build, survey, check-binding, overlay.

Модуль импортирует только стандартную библиотеку: check-binding и overlay запускаются в окружении
оценки без Pydantic, поэтому всё остальное подгружается внутри команд.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _resolve_pdf(arg: str) -> Path:
    """`@файл` — путь к PDF лежит в текстовом файле (чтобы не печатать его в командной строке)."""
    if arg.startswith("@"):
        return Path(Path(arg[1:]).read_text(encoding="utf-8").strip())
    return Path(arg)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="building_model", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def tender_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--tender-number", default=None)
        p.add_argument("--tender-version", type=int, default=None)
        p.add_argument("--manifest-sha256", default=None)

    build = sub.add_parser("build", help="модель одного листа")
    build.add_argument("--input", type=Path, required=True)
    build.add_argument("--page", type=int, required=True)
    build.add_argument("--out", type=Path, required=True)
    tender_args(build)

    survey = sub.add_parser("survey", help="агрегаты по всем листам-планам комплекта")
    survey.add_argument("--input", type=Path, required=True)
    survey.add_argument("--out", type=Path, required=True)
    tender_args(survey)

    binding = sub.add_parser("check-binding", help="поворот и привязка листа к PDF")
    binding.add_argument("--input", type=Path, required=True)
    binding.add_argument("--page", type=int, required=True)
    binding.add_argument("--pdf", required=True)

    overlay = sub.add_parser("overlay", help="растровая подложка со стенами и проёмами")
    overlay.add_argument("--input", type=Path, required=True)
    overlay.add_argument("--model", type=Path, required=True)
    overlay.add_argument("--page", type=int, required=True)
    overlay.add_argument("--pdf", required=True)
    overlay.add_argument("--out", type=Path, required=True)
    return parser


def _cmd_build(args: argparse.Namespace) -> int:
    from building_model.pipeline import TenderArgs, build_model, dumps_model
    from building_model.reader import load_document

    tender = TenderArgs(args.tender_number, args.tender_version, args.manifest_sha256)
    model = build_model(load_document(args.input), args.page, tender)
    text = dumps_model(model)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    walls = model.stats["walls"]
    print(f"страница {args.page}: записано {len(text)} символов, sha256 {digest}")
    print(
        f"стен {len(model.walls)}, колонн {len(model.columns)}, проёмов {len(model.openings)}, "
        f"плит {len(model.slabs)}, помещений {len(model.rooms)}, стеков {len(model.stacks)}"
    )
    print(
        f"review: блокеров {model.review.blockers}, предупреждений {model.review.warnings}, "
        f"служебных {model.review.info}"
    )
    print(f"статистика стен: {json.dumps(walls, ensure_ascii=False)}")
    return 0


def _cmd_survey(args: argparse.Namespace) -> int:
    from building_model.params import Params
    from building_model.pipeline import TenderArgs
    from building_model.reader import load_document
    from building_model.survey import print_survey, run_survey

    tender = TenderArgs(args.tender_number, args.tender_version, args.manifest_sha256)
    result = run_survey(load_document(args.input), Params(), tender)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print_survey(result)
    return 0


def _cmd_check_binding(args: argparse.Namespace) -> int:
    from building_model.binding import check_binding

    return check_binding(args.input, args.page, _resolve_pdf(args.pdf))


def _cmd_overlay(args: argparse.Namespace) -> int:
    from building_model.overlay import render_overlay

    return render_overlay(args.input, args.model, args.page, _resolve_pdf(args.pdf), args.out)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {
        "build": _cmd_build,
        "survey": _cmd_survey,
        "check-binding": _cmd_check_binding,
        "overlay": _cmd_overlay,
    }
    try:
        return handlers[args.command](args)
    except OSError as exc:
        # Текст ошибки ввода-вывода может содержать путь к частному файлу: печатаем только вид.
        print(f"ошибка ввода-вывода: {type(exc).__name__}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
