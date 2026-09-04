"""Экспорт OpenAPI — единственный источник TypeScript-клиента."""

from __future__ import annotations

import json
from pathlib import Path

from app.openapi_export import export


def test_openapi_export_is_offline_and_stable(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"

    export(target)
    first = target.read_text(encoding="utf-8")
    export(target)
    second = target.read_text(encoding="utf-8")

    assert first == second, "экспорт должен быть детерминированным, иначе drift-check ложно падает"

    schema = json.loads(first)
    assert schema["openapi"].startswith("3.")
    assert "/api/v1/meta" in schema["paths"]
    assert "/health/live" in schema["paths"]
