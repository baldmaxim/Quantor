"""Точка входа: <python движка> -I tools/cad_mep/run_zones.py --pdf … --out zones.json.

В изолированном режиме (-I) каталог скрипта не попадает в sys.path, поэтому добавляем его сами.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cad_mep.zones_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
