"""Синтетические сценарии страницы MEP-эксперимента (PROMPT 11, режим MOCK).

Сценарий — только набор файлов-фикстур. Статус не задаётся руками: граф проходит те же проверки
контрактов, а ВОР строит тот же `build_boq`, что и в PROMPT 09. Модели, изображения и цены нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Final

from app.contracts.mep import (
    MepEvidenceGraph,
    MepNetworkGraph,
    MepSystemProfile,
    canonical_sha256,
    validate_evidence_graph,
    validate_network_graph,
)
from app.contracts.mep.boq import MepBoq
from app.contracts.mep.boq_validation import validate_boq
from app.contracts.mep.common import ContractIssue
from app.services.mep.boq import build_boq

FIXTURES_PACKAGE: Final = "app.services.mep"
PROFILE_FILE: Final = "synthetic_profile.v0.3.json"
EVIDENCE_FILE: Final = "evidence_graph.v0.3.json"


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    title: str
    description: str
    network_file: str
    evidence_file: str = EVIDENCE_FILE


SCENARIOS: Final[tuple[Scenario, ...]] = (
    Scenario(
        scenario_id="complete",
        title="A · все параметры определены",
        description="Материал задан правилом генератора: физический ВОР рассчитан полностью.",
        network_file="network_graph_resolved.v0.3.json",
    ),
    Scenario(
        scenario_id="partial",
        title="B · материал не определён",
        description="Материал участков unresolved: длины заблокированы, счёт узлов рассчитан.",
        network_file="network_graph.v0.3.json",
    ),
    Scenario(
        scenario_id="refused",
        title="C · нарушена целостность калибровки",
        description="Коэффициент калибровки изменён после фиксации снимка: расчёт ВОР отказан.",
        network_file="network_graph_corrupted.v0.3.json",
    ),
    Scenario(
        scenario_id="hybrid",
        title="D · evidence проверен человеком",
        description=(
            "Модель ошиблась в подписи и положении прибора; инженер исправил. Сеть и ВОР построены "
            "по проверенному evidence (HYBRID_REVIEWED)."
        ),
        network_file="network_graph_hybrid.v0.3.json",
        evidence_file="evidence_graph_hybrid.v0.3.json",
    ),
)


@dataclass(frozen=True, slots=True)
class ScenarioRun:
    scenario: Scenario
    profile: MepSystemProfile
    evidence: MepEvidenceGraph
    network: MepNetworkGraph
    evidence_sha256: str
    network_sha256: str
    evidence_issues: list[ContractIssue]
    network_issues: list[ContractIssue]
    boq: MepBoq
    boq_issues: list[ContractIssue]


def _read(name: str) -> str:
    return files(FIXTURES_PACKAGE).joinpath("fixtures", name).read_text(encoding="utf-8")


def find(scenario_id: str) -> Scenario | None:
    return next((s for s in SCENARIOS if s.scenario_id == scenario_id), None)


def run(scenario: Scenario) -> ScenarioRun:
    profile = MepSystemProfile.model_validate_json(_read(PROFILE_FILE))
    evidence = MepEvidenceGraph.model_validate_json(_read(scenario.evidence_file))
    network = MepNetworkGraph.model_validate_json(_read(scenario.network_file))
    boq = build_boq(network, profile, evidence)
    return ScenarioRun(
        scenario=scenario,
        profile=profile,
        evidence=evidence,
        network=network,
        evidence_sha256=canonical_sha256(evidence),
        network_sha256=canonical_sha256(network),
        evidence_issues=validate_evidence_graph(evidence, profile),
        network_issues=validate_network_graph(network, evidence, profile),
        boq=boq,
        boq_issues=validate_boq(boq, network, evidence),
    )
