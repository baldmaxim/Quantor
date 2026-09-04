"""Выгрузка OpenAPI в packages/api-client/openapi.json.

Единственный источник правды по контракту — FastAPI. TypeScript-типы генерируются из этого
файла, руками DTO не дублируются. Запускается офлайн, без БД и хранилища.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import REPO_ROOT
from app.main import create_app

OUTPUT_PATH = REPO_ROOT / "packages" / "api-client" / "openapi.json"


def export(path: Path = OUTPUT_PATH) -> Path:
    schema = create_app().openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    written = export()
    print(f"OpenAPI -> {written}")
