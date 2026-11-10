"""Контракты трасс механики (ADR-0036 п. 8): решения человека и route-задания."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain import JobStatus
from app.models import CadDecision, Job
from app.models.cad_decision import MAX_DECISION_COMMENT
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service

CadJobType = Literal["cad_pdf_convert", "cad_mep_route"]


class CadApprovalCreate(BaseModel):
    """Одобрение вида: решение человека. Попытка - та, чей результат он смотрел."""

    model_config = ConfigDict(extra="forbid")

    attempt: Annotated[int, Field(ge=1)]
    comment: str | None = Field(default=None, max_length=MAX_DECISION_COMMENT)


class CadAcceptanceCreate(CadApprovalCreate):
    """Принятие трасс этажа целиком. Страница и вид берутся из route-задания."""


class CadMepRoutesCreate(BaseModel):
    """Постановка трасс. Отметка пола и высота этажа - ввод человека, обе обязательны."""

    model_config = ConfigDict(extra="forbid")

    attempt: Annotated[int, Field(ge=1)]
    floor_elevation_mm: Annotated[
        int, Field(ge=cad_mep_service.ELEVATION_MIN_MM, le=cad_mep_service.ELEVATION_MAX_MM)
    ]
    floor_height_mm: Annotated[
        int,
        Field(ge=cad_mep_service.FLOOR_HEIGHT_MIN_MM, le=cad_mep_service.FLOOR_HEIGHT_MAX_MM),
    ]


class CadDecisionRead(BaseModel):
    id: UUID
    kind: Literal["view_approval", "mep_acceptance"]
    job_id: UUID
    attempt: int
    page_index: int
    view: int
    artifact_sha256: str
    decided_by: UUID
    decided_by_name: str | None
    decided_at: datetime
    comment: str | None


def decision_read(decision: CadDecision, author: str | None) -> CadDecisionRead:
    return CadDecisionRead.model_validate(
        {
            "id": decision.id,
            "kind": decision.kind,
            "job_id": decision.job_id,
            "attempt": decision.attempt,
            "page_index": decision.page_index,
            "view": decision.view,
            "artifact_sha256": decision.artifact_sha256,
            "decided_by": decision.decided_by,
            "decided_by_name": author,
            "decided_at": decision.decided_at,
            "comment": decision.comment,
        }
    )


class CadRouteJobRead(BaseModel):
    """Route-задание вида в списке у родителя."""

    job_id: UUID
    status: JobStatus
    attempt: int
    created_at: datetime
    finished_at: datetime | None
    error_code: str | None
    floor_elevation_mm: int | None
    floor_height_mm: int | None
    generator_version: str | None
    accepted: bool


class CadViewMepRead(BaseModel):
    """Решения вида: у родителя - одобрение и route-задания, у route-задания - принятие."""

    approval: CadDecisionRead | None = None
    acceptance: CadDecisionRead | None = None
    route_jobs: list[CadRouteJobRead] = Field(default_factory=list)


def _route_ref(job: Job, state: cad_mep_service.MepState) -> CadRouteJobRead:
    result = cad_service.result_of(job)
    attempt = result.get("attempt")
    page_index = cad_mep_service.payload_int(job, "page_index")
    view = cad_mep_service.payload_int(job, "view")
    accepted = (
        type(attempt) is int
        and page_index is not None
        and view is not None
        and (job.id, attempt, page_index, view) in state.acceptances
    )
    version = job.payload.get("generator_version")
    return CadRouteJobRead(
        job_id=job.id,
        status=job.status,
        attempt=job.attempt,
        created_at=job.created_at,
        finished_at=job.finished_at,
        error_code=job.error_code,
        floor_elevation_mm=cad_mep_service.payload_int(job, "floor_elevation_mm"),
        floor_height_mm=cad_mep_service.payload_int(job, "floor_height_mm"),
        generator_version=version if isinstance(version, str) else None,
        accepted=bool(accepted),
    )


def view_mep_read(
    job: Job,
    result_attempt: int | None,
    page_index: int,
    view: int,
    state: cad_mep_service.MepState | None,
) -> CadViewMepRead:
    """Решения вида из состояния; без состояния (не загружали) - пусто."""
    if state is None or result_attempt is None:
        return CadViewMepRead()
    key = (job.id, result_attempt, page_index, view)
    approval = state.approvals.get(key)
    acceptance = state.acceptances.get(key)
    routes = [
        ref
        for route in state.routes.get(job.id, [])
        if cad_mep_service.payload_int(route, "page_index") == page_index
        and cad_mep_service.payload_int(route, "view") == view
        and cad_mep_service.payload_int(route, "parent_attempt") == result_attempt
        for ref in (_route_ref(route, state),)
    ]
    return CadViewMepRead(
        approval=decision_read(*approval) if approval else None,
        acceptance=decision_read(*acceptance) if acceptance else None,
        route_jobs=routes,
    )
