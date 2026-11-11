"""Командная строка: контракт между исполнителем cad-worker и генератором трасс."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from cad_mep.errors import EXIT_INPUT, MepError
from cad_mep.pipeline import Args, generate


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        fail("bad_arguments", message)
        raise SystemExit(EXIT_INPUT)


def fail(code: str, message: str) -> None:
    sys.stderr.write(json.dumps({"code": code, "message": message}, ensure_ascii=False) + "\n")


def _parser() -> argparse.ArgumentParser:
    p = JsonArgumentParser(prog="run_mep.py", description="Трассы механики по плану этажа")
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--page-index", type=int, required=True)
    p.add_argument("--view-dxf", type=Path, required=True)
    p.add_argument("--scale", type=Path, required=True)
    p.add_argument("--preview", type=Path, required=True)
    p.add_argument("--params", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--view-folder", required=True)
    p.add_argument("--floor-elevation-mm", type=int, default=None)
    p.add_argument("--floor-height-mm", type=int, default=None)
    p.add_argument("--approval-id", default=None)
    p.add_argument("--risers", type=Path, default=None, help="реестр стояков cad_risers.v1")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ns = _parser().parse_args(argv)
    args = Args(
        pdf=ns.pdf,
        page_index=ns.page_index,
        view_dxf=ns.view_dxf,
        scale=ns.scale,
        preview=ns.preview,
        params=ns.params,
        out=ns.out,
        view_folder=ns.view_folder,
        floor_elevation_mm=ns.floor_elevation_mm,
        floor_height_mm=ns.floor_height_mm,
        approval_id=ns.approval_id,
        risers=ns.risers,
    )
    started = time.monotonic()
    try:
        summary = generate(args)
    except MepError as exc:
        fail(exc.code, exc.message)
        return exc.exit_code
    summary["runtime_s"] = round(time.monotonic() - started, 1)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0
