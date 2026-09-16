"""Синтетические примеры MEP v0.3 и помощники тестов контрактов и ВОР."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.contracts.mep import (
    MepEvidenceGraph,
    MepNetworkGraph,
    MepSystemProfile,
    canonical_sha256,
)
from app.contracts.mep.common import ContractIssue, IssueSeverity

DOCS = Path(__file__).resolve().parents[3] / "docs" / "mep"
EXAMPLES = Path(__file__).resolve().parents[1] / "app" / "services" / "mep" / "fixtures"

Json = dict[str, Any]


def load(name: str) -> Json:
    data: Json = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return data


PROFILE = load("synthetic_profile.v0.3.json")
EVIDENCE = load("evidence_graph.v0.3.json")
NETWORK = load("network_graph.v0.3.json")


def profile_model(data: Json | None = None) -> MepSystemProfile:
    return MepSystemProfile.model_validate(PROFILE if data is None else data)


def evidence_model(data: Json | None = None) -> MepEvidenceGraph:
    return MepEvidenceGraph.model_validate(EVIDENCE if data is None else data)


def network_model(data: Json | None = None) -> MepNetworkGraph:
    return MepNetworkGraph.model_validate(NETWORK if data is None else data)


def errors(issues: list[ContractIssue]) -> set[str]:
    return {item.code for item in issues if item.severity == IssueSeverity.ERROR}


def warnings(issues: list[ContractIssue]) -> set[str]:
    return {item.code for item in issues if item.severity == IssueSeverity.WARNING}


def element(data: Json, element_id: str) -> Json:
    return by_id(data["elements"], element_id)


def by_id(items: list[Json], item_id: str) -> Json:
    found: Json = next(item for item in items if item["id"] == item_id)
    return found


def rehash(data: Json, graph: MepEvidenceGraph) -> Json:
    data["evidence_graph"]["sha256"] = canonical_sha256(graph)
    return data
