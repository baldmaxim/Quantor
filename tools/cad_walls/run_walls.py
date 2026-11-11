"""Точка входа: <python движка> -I tools/cad_walls/run_walls.py --dxf … --out walls.json.

В изолированном режиме (-I) каталог скрипта не попадает в sys.path, поэтому добавляем его сами.
Каталог tools/cad_mep нужен только для разбора отметок по PDF (cad_mep.elevations).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parent.parent / "cad_mep"))

from cad_walls.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
