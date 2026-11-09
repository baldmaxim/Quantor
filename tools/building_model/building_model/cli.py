"""Командная строка: parse, build, survey, check-binding, overlay, markup, approve, revit,
revit-building, run.

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

    parse = sub.add_parser(
        "parse", help="PDF -> plangeom -> set.json (нужно окружение .venv-reader)"
    )
    parse.add_argument("--pdf", required=True)
    parse.add_argument("--out", type=Path, required=True)
    parse.add_argument("--pages", default=None, help="номера страниц через запятую: 51,33")
    parse.add_argument("--workers", type=int, default=1)

    markup = sub.add_parser("markup", help="модели, PNG-наложения и index.html для человека")
    markup.add_argument("--input", type=Path, required=True)
    markup.add_argument("--pdf", default=None)
    markup.add_argument("--out-dir", type=Path, required=True)
    markup.add_argument("--pages", default=None)

    approve = sub.add_parser("approve", help="подтверждение масштаба и модели листа человеком")
    approve.add_argument("--input", type=Path, required=True)
    approve.add_argument("--model", type=Path, required=True)
    approve.add_argument("--page", type=int, required=True)
    approve.add_argument("--by", required=True)
    approve.add_argument("--out", type=Path, required=True)
    approve.add_argument("--note", default=None)
    approve.add_argument(
        "--accept-noise",
        action="store_true",
        help="принять блокер openings_noise (шумный лист) после проверки разметки",
    )

    revit = sub.add_parser("revit", help="пакет quantor.revit_package.v0 из модели и подтверждения")
    revit.add_argument("--model", type=Path, required=True)
    revit.add_argument("--approval", type=Path, default=None)
    revit.add_argument("--unapproved-test", action="store_true")
    revit.add_argument("--out", type=Path, required=True)

    schema = sub.add_parser("revit-schema", help="JSON Schema пакета Revit")
    schema.add_argument("--out", type=Path, required=True)

    building = sub.add_parser(
        "revit-building", help="пакет quantor.revit_building_package.v0 из моделей листов здания"
    )
    building.add_argument("--input", type=Path, required=True)
    building.add_argument("--models-dir", type=Path, required=True)
    building.add_argument("--building", type=int, required=True)
    building.add_argument("--add-page", type=int, action="append", default=[])
    building.add_argument("--exclude-page", type=int, action="append", default=[])
    building.add_argument("--approvals-dir", type=Path, default=None)
    building.add_argument("--unapproved-test", action="store_true")
    building.add_argument("--out", type=Path, required=True)

    building_schema = sub.add_parser(
        "revit-building-schema", help="JSON Schema пакета здания для Revit"
    )
    building_schema.add_argument("--out", type=Path, required=True)

    run = sub.add_parser("run", help="parse -> markup; пакеты не строит (нужно подтверждение)")
    run.add_argument("--pdf", default=None)
    run.add_argument("--out-dir", type=Path, required=True)
    run.add_argument("--pages", default=None)
    run.add_argument("--input", type=Path, default=None)
    run.add_argument("--workers", type=int, default=1)
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


def _cmd_parse(args: argparse.Namespace) -> int:
    from building_model.parse_pdf import parse_pages, parse_pdf

    pages = None if args.pages is None else parse_pages(args.pages)
    summary = parse_pdf(_resolve_pdf(args.pdf), args.out, pages, args.workers)
    verdicts = ", ".join(f"{k}: {v}" for k, v in summary.verdicts.items())
    print(f"parse: листов {summary.sheets} ({verdicts}), {summary.seconds:.1f} с")
    print(f"записано {summary.bytes_written} байт")
    return 0


def _print_markup(result: object, index: Path) -> None:
    from building_model.markup import MarkupResult

    if not isinstance(result, MarkupResult):
        raise TypeError("ожидался MarkupResult")
    blockers = sum(r.blockers for r in result.rows)
    print(
        f"листов-планов {len(result.rows)}: моделей построено {result.models_built}, "
        f"использовано готовых {result.models_reused}, PNG {result.images}, блокеров {blockers}"
    )
    if result.excluded:
        print(f"исключено листов: {json.dumps(result.excluded, ensure_ascii=False)}")
    print(f"index.html: {index}")


def _cmd_markup(args: argparse.Namespace) -> int:
    from building_model.markup import run_markup, write_index
    from building_model.parse_pdf import parse_pages

    pages = None if args.pages is None else parse_pages(args.pages)
    pdf = None if args.pdf is None else _resolve_pdf(args.pdf)
    result = run_markup(args.input, pdf, args.out_dir, pages)
    _print_markup(result, write_index(result, args.out_dir))
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    from building_model.approval import dumps_approval, make_approval

    approval = make_approval(
        args.input, args.model, args.page, args.by, args.note, accept_noise=args.accept_noise
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dumps_approval(approval), encoding="utf-8")
    print(f"подтверждение страницы {approval.page}: {approval.by}, {approval.at}")
    return 0


def _cmd_revit(args: argparse.Namespace) -> int:
    from building_model.approval import load_approval, sha256_of_file
    from building_model.canonical import BuildingModel
    from building_model.revit import build_package
    from building_model.revit_format import dumps_package

    if (args.approval is None) == (not args.unapproved_test):
        raise ValueError("укажите ровно одно: --approval файл или --unapproved-test")
    model = BuildingModel.model_validate_json(args.model.read_text(encoding="utf-8"))
    approval = None if args.approval is None else load_approval(args.approval)
    package = build_package(model, approval, sha256_of_file(args.model))
    text = dumps_package(package)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    data = text.encode("utf-8")
    print(f"пакет: {len(data)} байт, sha256 {hashlib.sha256(data).hexdigest()}")
    print(f"масштаб: {package.manifest.scale_status}")
    for kind, cov in package.manifest.coverage.items():
        print(f"{kind}: всего {cov.total}, выгружено {cov.exported}, нет {cov.not_exported}")
    reasons: dict[str, int] = {}
    for item in package.not_exported:
        name = f"{item.kind}/{item.reason}"
        reasons[name] = reasons.get(name, 0) + 1
    print(f"не выгружено по причинам: {json.dumps(dict(sorted(reasons.items())))}")
    return 0


def _cmd_revit_schema(args: argparse.Namespace) -> int:
    from building_model.revit_format import package_json_schema

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(package_json_schema(), encoding="utf-8")
    return 0


def _cmd_revit_building(args: argparse.Namespace) -> int:
    from building_model.revit_building_run import run_building
    from building_model.revit_format import dumps_building_package

    if (args.approvals_dir is None) == (not args.unapproved_test):
        raise ValueError("укажите ровно одно: --approvals-dir каталог или --unapproved-test")
    package = run_building(
        args.input,
        args.models_dir,
        args.building,
        args.add_page,
        args.exclude_page,
        args.approvals_dir,
    )
    text = dumps_building_package(package)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    data = text.encode("utf-8")
    info = package.manifest.building
    print(f"пакет здания: {len(data)} байт, sha256 {hashlib.sha256(data).hexdigest()}")
    print(f"масштаб: {package.manifest.scale_status}, опорный лист {info.reference_page}")
    print(
        f"листов {len(package.manifest.sheets)}, уровней {len(package.levels)}, "
        f"пропущено страниц {len(info.skipped_pages)}, нет этажей {len(info.missing_floors)}"
    )
    for kind, cov in package.manifest.coverage.items():
        print(f"{kind}: всего {cov.total}, выгружено {cov.exported}, нет {cov.not_exported}")
    return 0


def _cmd_revit_building_schema(args: argparse.Namespace) -> int:
    from building_model.revit_format import building_package_json_schema

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(building_package_json_schema(), encoding="utf-8")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from building_model.parse_pdf import parse_pages
    from building_model.runner import NEXT_STEP, run_pipeline

    pages = None if args.pages is None else parse_pages(args.pages)
    pdf = None if args.pdf is None else _resolve_pdf(args.pdf)
    result, index = run_pipeline(pdf, args.out_dir, pages, args.input, args.workers)
    _print_markup(result, index)
    print(NEXT_STEP.format(index=index))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    handlers = {
        "build": _cmd_build,
        "survey": _cmd_survey,
        "check-binding": _cmd_check_binding,
        "overlay": _cmd_overlay,
        "parse": _cmd_parse,
        "markup": _cmd_markup,
        "approve": _cmd_approve,
        "revit": _cmd_revit,
        "revit-schema": _cmd_revit_schema,
        "revit-building": _cmd_revit_building,
        "revit-building-schema": _cmd_revit_building_schema,
        "run": _cmd_run,
    }
    try:
        return handlers[args.command](args)
    except OSError as exc:
        # Текст ошибки ввода-вывода может содержать путь к частному файлу: печатаем только вид.
        print(f"ошибка ввода-вывода: {type(exc).__name__}", file=sys.stderr)
        return 1
    except ValueError as exc:
        if type(exc).__module__.startswith("pydantic"):
            # Текст ошибки Pydantic цитирует входные данные (частные): печатаем только число ошибок.
            count = getattr(exc, "error_count", lambda: 0)()
            print(f"ошибка формата входного файла: {count} несоответствий", file=sys.stderr)
        else:
            print(f"ошибка: {exc}", file=sys.stderr)
        return 2
