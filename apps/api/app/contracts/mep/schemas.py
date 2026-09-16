"""Выгрузка JSON Schema контрактов MEP v0.3 — языконезависимая форма для `vision/`.

Схемы генерируются из моделей и сверяются тестом; руками не правятся:

    python -m app.contracts.mep.schemas ../../docs/mep/schemas
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from app.contracts.mep.boq import MepBoq
from app.contracts.mep.evidence import MepEvidenceGraph
from app.contracts.mep.network import MepNetworkGraph
from app.contracts.mep.profile import MepSystemProfile

SCHEMA_FILES: Final[dict[str, type[BaseModel]]] = {
    "mep_evidence_graph.v0.3.schema.json": MepEvidenceGraph,
    "mep_network_graph.v0.3.schema.json": MepNetworkGraph,
    "mep_system_profile.v0.3.schema.json": MepSystemProfile,
    "mep_boq.v0.3.schema.json": MepBoq,
}


def render(model: type[BaseModel]) -> str:
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **model.model_json_schema(),
    }
    return json.dumps(schema, ensure_ascii=False, indent=2) + "\n"


def write(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_FILES.items():
        (target / name).write_text(render(model), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    write(Path(sys.argv[1]))
