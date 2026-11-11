"""Временный pins.json для тестов CAD: версии и sha256 параметров заглушек генераторов."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services import cad as cad_service


def _entry(params: Path, version: str) -> dict[str, Any]:
    raw = params.read_bytes()
    return {
        "generator_version": version,
        "params_path": f"generators/{params.parent.parent.name}/params/{params.name}",
        "params_sha256": hashlib.sha256(raw).hexdigest(),
        "params_canonical_sha256": cad_service.params_sha256(json.loads(raw)),
    }


def write_pins(
    directory: Path,
    *,
    mep: Path | None = None,
    walls: Path | None = None,
    mep_version: str = "cad_mep.v1",
    walls_version: str = "cad_walls.v1",
    floor3d_version: str = "cad_floor3d_dxf.v2",
) -> str:
    """Пишет `directory/pins.json` с генераторами по файлам параметров; возвращает путь строкой.

    `mep` и `walls` - файлы `params/v1.json` заглушек; не заданный генератор в pins не попадает.
    """
    generators: dict[str, Any] = {"path": "generators"}
    if mep is not None:
        generators["cad_mep"] = _entry(mep, mep_version)
    if walls is not None:
        generators["cad_walls"] = _entry(walls, walls_version) | {
            "floor3d_dxf_version": floor3d_version
        }
    target = directory / "pins.json"
    target.write_text(
        json.dumps({"schema": "quantor.cad_engine.pins.v1", "generators": generators}),
        encoding="utf-8",
    )
    return str(target)
