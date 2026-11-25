"""Командная строка: build, check, register, register-all.

python -m model_package build --ifc ФАЙЛ[:ДИСЦИПЛИНА] [--ifc …] --out КАТАЛОГ
                              [--only-storey ПОДСТРОКА]
python -m model_package check КАТАЛОГ
python -m model_package register --grids grids.json --pdf FILE.pdf --page N [--out placement.json]
                                 [--png overlay.png --footprint footprints/<этаж>.json]
python -m model_package register-all --package КАТАЛОГ --pdf FILE.pdf [--out registrations.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import qmp_check


def _print(text: str) -> None:
    print(text, flush=True)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=1)
    path.write_bytes((text + "\n").encode("utf-8"))


def cmd_build(args: argparse.Namespace) -> int:
    from .disciplines import split_ifc_arg
    from .ifc_source import QmpError
    from .qmp_build import DEFAULT_PART_LIMIT, IfcInput, build_package

    inputs = [IfcInput(Path(p), d) for p, d in map(split_ifc_arg, args.ifc)]
    limit = int(args.part_limit_mb * 1024 * 1024) if args.part_limit_mb else DEFAULT_PART_LIMIT
    try:
        result = build_package(
            inputs,
            Path(args.out),
            only_storey=args.only_storey,
            part_limit=limit,
            threads=args.threads,
            log=_print,
        )
    except (QmpError, ValueError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 2
    for warning in result.warnings:
        _print(f"предупреждение: {warning}")
    m = result.manifest
    total = sum(p["bytes"] for p in m["parts"])
    _print(
        f"пакет {result.out_dir}: этажей {m['counts']['storeys']}, элементов "
        f"{m['counts']['elements']}, треугольников {m['counts']['triangles']}, частей "
        f"{m['counts']['parts']}, {total / 1e6:.1f} МБ; manifest_sha256 {m['manifest_sha256']}"
    )
    _print("время, с: " + ", ".join(f"{k} {v}" for k, v in result.timings.items()))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    report = qmp_check.check_package(Path(args.package), args.previous)
    _print(qmp_check.format_report(report))
    return 0 if report.ok else 1


def cmd_register(args: argparse.Namespace) -> int:
    from .register_sheet import load_json, register_sheet

    grids = load_json(Path(args.grids))
    placement = register_sheet(grids, Path(args.pdf), args.page)
    _print(json.dumps(placement, ensure_ascii=False, indent=1))
    if args.out:
        _write_json(Path(args.out), placement)
    if args.png:
        from .overlay import draw_overlay

        footprint = load_json(Path(args.footprint)) if args.footprint else None
        if placement["affine"]:
            draw_overlay(Path(args.pdf), placement, grids, Path(args.png), footprint)
    return 0 if placement["ok"] else 1


def cmd_register_all(args: argparse.Namespace) -> int:
    from .register_sheet import format_table, load_json, register_all

    package = Path(args.package) if args.package else None
    grids_path = Path(args.grids) if args.grids else package / "grids.json" if package else None
    storeys_path = (
        Path(args.storeys) if args.storeys else package / "storeys.json" if package else None
    )
    if grids_path is None or storeys_path is None:
        print("ошибка: нужен --package или пара --grids и --storeys", file=sys.stderr)
        return 2
    rows = register_all(load_json(grids_path), load_json(storeys_path), Path(args.pdf))
    _print(format_table(rows))
    if args.out:
        _write_json(Path(args.out), rows)
    plans = [r for r in rows if r["plan"]]
    _print(f"планов {len(plans)}, привязано {sum(r['placement']['ok'] for r in plans)}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="model_package", description="Пакет модели QMP v1")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="собрать пакет из IFC")
    b.add_argument("--ifc", action="append", required=True, help="ФАЙЛ[:ДИСЦИПЛИНА], можно много")
    b.add_argument("--out", required=True, help="каталог пакета (новый или с прежней выгрузкой)")
    b.add_argument("--only-storey", help="только этажи, в имени которых есть подстрока")
    b.add_argument("--part-limit-mb", type=float, help="предел части GLB, МиБ (по умолчанию 60)")
    b.add_argument("--threads", type=int, default=1, help="потоков триангуляции (по умолчанию 1)")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="самопроверка каталога пакета (раздел 9)")
    c.add_argument("package")
    c.add_argument("--previous", type=Path, action="append", default=[])
    c.set_defaults(func=cmd_check)
    r = sub.add_parser("register", help="привязать страницу PDF к осям")
    r.add_argument("--grids", required=True)
    r.add_argument("--pdf", required=True)
    r.add_argument("--page", type=int, required=True, help="индекс страницы с нуля")
    r.add_argument("--out")
    r.add_argument("--png", help="картинка проверки")
    r.add_argument("--footprint", help="footprints/<этаж>.json для картинки")
    r.set_defaults(func=cmd_register)
    a = sub.add_parser("register-all", help="все планы PDF: этаж по отметке и привязка")
    a.add_argument("--package", help="каталог пакета (grids.json и storeys.json)")
    a.add_argument("--grids")
    a.add_argument("--storeys")
    a.add_argument("--pdf", required=True)
    a.add_argument("--out")
    a.set_defaults(func=cmd_register_all)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.func(args))
