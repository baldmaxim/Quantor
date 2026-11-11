"""Точка входа: <python движка> -I run_floor3d_dxf.py --model model.json --out floor3d.dxf.

В изолированном режиме (-I) каталог скрипта не попадает в sys.path, поэтому добавляем его сами.
Код выхода 2 - ошибка входа; причина - одной строкой JSON `{"code", "message"}` в stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cad_walls.errors import EXIT_INPUT, WallsError
from cad_walls.floor3d_dxf import generate


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _fail("bad_arguments", message)
        raise SystemExit(EXIT_INPUT)


def _fail(code: str, message: str) -> None:
    sys.stderr.write(json.dumps({"code": code, "message": message}, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _JsonArgumentParser(
        prog="run_floor3d_dxf.py", description="3D DXF этажа по модели 3D-вида"
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    ns = parser.parse_args(argv)
    started = time.monotonic()
    try:
        summary = generate(ns.model, ns.out)
    except WallsError as exc:
        _fail(exc.code, exc.message)
        return exc.exit_code
    except OSError as exc:
        _fail("io_error", str(exc))
        return EXIT_INPUT
    summary["runtime_s"] = round(time.monotonic() - started, 1)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
