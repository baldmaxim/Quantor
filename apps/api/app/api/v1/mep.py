"""Страница MEP-эксперимента в режиме MOCK (ADR-0027, PROMPT 11).

Только чтение синтетических сценариев. Граф проверяется контрактами, ВОР строит существующий
Quantity Engine. Весь маршрутизатор закрыт флагом `mep_rd_hypothesis_v1` (ADR-0023).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.v1.deps import require, require_feature
from app.auth.permissions import Permission
from app.contracts.mep import MepEvidenceGraph, MepNetworkGraph, MepSystemProfile
from app.contracts.mep.boq import MepBoq
from app.contracts.mep.common import ContractIssue
from app.errors import not_found
from app.services.mep import scenarios as scenarios_service

router = APIRouter(
    prefix="/mep/experiment",
    tags=["mep"],
    dependencies=[require_feature("mep_rd_hypothesis_v1")],
)


class MepScenarioSummary(BaseModel):
    scenario_id: str
    title: str
    description: str


class MepContractIssueRead(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    subject_id: str | None
    message: str


class MepScenarioRead(BaseModel):
    """Сценарий целиком: входы, замечания проверок и ВОР, посчитанный движком на сервере."""

    scenario: MepScenarioSummary
    mode: Literal["MOCK"] = "MOCK"
    profile: MepSystemProfile
    evidence: MepEvidenceGraph
    network: MepNetworkGraph
    evidence_sha256: str
    network_sha256: str
    evidence_issues: list[MepContractIssueRead]
    network_issues: list[MepContractIssueRead]
    boq: MepBoq
    # Ссылки ВОР разрешаются в сеть и evidence; значения группы совпадают с параметрами.
    boq_issues: list[MepContractIssueRead]


def _summary(scenario: scenarios_service.Scenario) -> MepScenarioSummary:
    return MepScenarioSummary(
        scenario_id=scenario.scenario_id, title=scenario.title, description=scenario.description
    )


def _issues(items: list[ContractIssue]) -> list[MepContractIssueRead]:
    return [
        MepContractIssueRead(
            code=item.code,
            severity=item.severity.value,
            subject_id=item.subject_id,
            message=item.message,
        )
        for item in items
    ]


@router.get(
    "/scenarios",
    response_model=list[MepScenarioSummary],
    summary="Синтетические сценарии MEP-эксперимента",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def list_mep_scenarios() -> list[MepScenarioSummary]:
    return [_summary(scenario) for scenario in scenarios_service.SCENARIOS]


@router.get(
    "/scenarios/{scenario_id}",
    response_model=MepScenarioRead,
    summary="Сценарий MEP-эксперимента: evidence, сеть РД и физический ВОР",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def get_mep_scenario(scenario_id: str) -> MepScenarioRead:
    scenario = scenarios_service.find(scenario_id)
    if scenario is None:
        raise not_found("Сценарий")
    result = scenarios_service.run(scenario)
    return MepScenarioRead(
        scenario=_summary(scenario),
        profile=result.profile,
        evidence=result.evidence,
        network=result.network,
        evidence_sha256=result.evidence_sha256,
        network_sha256=result.network_sha256,
        evidence_issues=_issues(result.evidence_issues),
        network_issues=_issues(result.network_issues),
        boq=result.boq,
        boq_issues=_issues(result.boq_issues),
    )
