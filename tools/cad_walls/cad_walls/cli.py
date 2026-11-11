"""Командная строка: контракт между исполнителем cad-worker и скриптом конструкций."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from cad_walls.errors import EXIT_INPUT, WallsError
from cad_walls.pipeline import Args, generate


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _fail("bad_arguments", message)
        raise SystemExit(EXIT_INPUT)


def _fail(code: str, message: str) -> None:
    sys.stderr.write(json.dumps({"code": code, "message": message}, ensure_ascii=False) + "\n")


def _parser() -> argparse.ArgumentParser:
    p = _JsonArgumentParser(prog="run_walls.py", description="Конструкции кладки и монолита по DXF")
    p.add_argument("--dxf", type=Path, required=True)
    p.add_argument("--params", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pdf", type=Path, default=None)
    p.add_argument("--page", type=int, default=None, help="индекс страницы PDF, с нуля")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ns = _parser().parse_args(argv)
    if (ns.pdf is None) != (ns.page is None):
        _fail("bad_arguments", "--pdf и --page задаются вместе")
        return EXIT_INPUT
    started = time.monotonic()
    try:
        summary = generate(Args(dxf=ns.dxf, params=ns.params, out=ns.out, pdf=ns.pdf, page=ns.page))
    except WallsError as exc:
        _fail(exc.code, exc.message)
        return exc.exit_code
    except OSError as exc:
        _fail("io_error", str(exc))
        return EXIT_INPUT
    summary["runtime_s"] = round(time.monotonic() - started, 1)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0
