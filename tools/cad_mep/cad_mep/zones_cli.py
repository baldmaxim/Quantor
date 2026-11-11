"""Командная строка разметки зон помещений: тот же контракт аргументов и ошибок, что у cli.py."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from cad_mep.cli import JsonArgumentParser, fail
from cad_mep.errors import MepError
from cad_mep.zones import ZoneArgs, extract_zones, write_zones

OUT_NAME = "zones.json"


def _parser() -> argparse.ArgumentParser:
    p = JsonArgumentParser(prog="run_zones.py", description="Зоны помещений квартир по плану этажа")
    p.add_argument("--pdf", type=Path, required=True)
    p.add_argument("--page-index", type=int, required=True)
    p.add_argument("--view-dxf", type=Path, required=True)
    p.add_argument("--scale", type=Path, required=True)
    p.add_argument("--preview", type=Path, required=True)
    p.add_argument("--params", type=Path, default=None)
    p.add_argument("--out", type=Path, required=True, help="файл zones.json или каталог для него")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ns = _parser().parse_args(argv)
    out: Path = ns.out / OUT_NAME if ns.out.is_dir() else ns.out
    args = ZoneArgs(ns.pdf, ns.page_index, ns.view_dxf, ns.scale, ns.preview, ns.params, out)
    started = time.monotonic()
    try:
        data = extract_zones(args)
        write_zones(args, data)
    except MepError as exc:
        fail(exc.code, exc.message)
        return exc.exit_code
    except OSError as exc:
        fail("out_unwritable", f"{out.name}: не записывается ({exc})")
        return 2
    zones, unmatched, spaces = data["zones"], data["unmatched_marks"], data["parking_spaces"]
    summary = {
        "ok": True,
        "zones": len(zones) if isinstance(zones, list) else 0,
        "unmatched_marks": len(unmatched) if isinstance(unmatched, list) else 0,
        "parking_spaces": len(spaces) if isinstance(spaces, list) else 0,
        "runtime_s": round(time.monotonic() - started, 1),
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0
