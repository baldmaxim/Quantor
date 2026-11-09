"""Выгрузка OpenAPI в packages/api-client/openapi.json.

Единственный источник правды по контракту — FastAPI. TypeScript-типы генерируются из этого
файла, руками DTO не дублируются. Запускается офлайн, без БД и хранилища.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.api.v1.cad import qa_router as cad_qa_router
from app.core.config import REPO_ROOT
from app.main import create_app

OUTPUT_PATH = REPO_ROOT / "packages" / "api-client" / "openapi.json"


def export(path: Path = OUTPUT_PATH) -> Path:
    app = create_app()
    if not any(getattr(route, "path", "").endswith("/cad") for route in app.routes):
        # Контракт QA-маршрутов PDF -> CAD входит в клиент, чтобы интерфейс работал на
        # сгенерированных типах. На сервере маршруты существуют только при CAD_QA_ENABLED
        # (local/test) и флаге `cad.export`; интерфейс проверяет тот же флаг.
        app.include_router(cad_qa_router)
    schema = app.openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    written = export()
    print(f"OpenAPI -> {written}")
