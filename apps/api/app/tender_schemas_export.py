"""Выгрузка JSON Schema файлов пакетов обмена с TENDER в docs/tender-exchange/schemas/.

Единственный источник правды по формату — контракты `app/contracts/tender_exchange.py`; схемы
для навыков TENDER (`quantor-obmen`) порождаются из них, руками не пишутся. Файл схемы назван по
идентификатору схемы: `quantor.object_base.v1.schema.json`. Запуск офлайн, без БД и хранилища:
`python -m app.tender_schemas_export`.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.contracts.tender_exchange import PACKAGE_MODELS
from app.core.config import REPO_ROOT

OUTPUT_DIR = REPO_ROOT / "docs" / "tender-exchange" / "schemas"
DRAFT = "https://json-schema.org/draft/2020-12/schema"


def schema_files() -> dict[str, str]:
    """Имя файла -> содержимое JSON Schema для каждого файла пакетов."""
    files: dict[str, str] = {}
    for schema_id, model in PACKAGE_MODELS.items():
        schema = model.model_json_schema(by_alias=True)
        schema = {"$schema": DRAFT, "$id": schema_id, **schema}
        files[f"{schema_id}.schema.json"] = (
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
    return files


def export(directory: Path = OUTPUT_DIR) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in schema_files().items():
        path = directory / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in export():
        print(f"JSON Schema -> {written_path}")
