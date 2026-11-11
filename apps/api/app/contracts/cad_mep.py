"""Контракты трасс механики (ADR-0036 п. 8): решения человека и route-задания."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class CadMepFloorParams(BaseModel):
    """Отметка пола и высота этажа необязательны.

    Не заданы - генератор определит их по тексту документации; заданы - это переопределение
    человека (с проверкой пределов).
    """

    model_config = ConfigDict(extra="forbid")

    floor_elevation_mm: (
        Annotated[
            int, Field(ge=cad_mep_service.ELEVATION_MIN_MM, le=cad_mep_service.ELEVATION_MAX_MM)
        ]
        | None
    ) = None
    floor_height_mm: (
        Annotated[
            int,
            Field(ge=cad_mep_service.FLOOR_HEIGHT_MIN_MM, le=cad_mep_service.FLOOR_HEIGHT_MAX_MM),
        ]
        | None
    ) = None


class CadMepRoutesCreate(CadMepFloorParams):
    """Постановка трасс по одобренному виду. Попытка - та, чей результат одобрен."""

    attempt: Annotated[int, Field(ge=1)]


class CadMepRecomputeCreate(CadMepFloorParams):
    """Пересчёт трасс новой попыткой того же задания: пусто - по документации."""


class CadRevokeCreate(BaseModel):
    """Отзыв решения; причина необязательна."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=MAX_DECISION_COMMENT)

    @field_validator("reason")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        stripped = None if value is None else value.strip()
        return stripped or None


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
    # Отзыв: пусто у действующего решения.
    revoked_at: datetime | None = None
    revoked_by: UUID | None = None
    revoked_by_name: str | None = None
    revoke_reason: str | None = None


def decision_read(
    decision: CadDecision, author: str | None, revoker: str | None = None
) -> CadDecisionRead:
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
            "revoked_at": decision.revoked_at,
            "revoked_by": decision.revoked_by,
            "revoked_by_name": revoker,
            "revoke_reason": decision.revoke_reason,
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
    # Одобрение вида, по которому построены трассы, и действует ли оно ещё.
    approval_id: UUID | None = None
    approval_revoked: bool = False


class CadMepAttemptRead(BaseModel):
    """Попытка route-задания: что запросил человек и что получилось (история расчётов)."""

    attempt: int
    # Запрос человека; пусто - определить по документации.
    requested_elevation_mm: int | None
    requested_height_mm: int | None
    requested_at: datetime | None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    error_code: str | None
    # Итог попытки (из её candidate.json): значение и источник.
    floor_elevation_mm: int | None
    floor_elevation_source: str | None
    floor_height_mm: int | None
    floor_height_source: str | None


def _result_value(result: dict[str, object], key: str) -> tuple[int | None, str | None]:
    raw = result.get(key)
    if isinstance(raw, dict) and type(raw.get("value_mm")) is int:
        source = raw.get("source")
        return raw["value_mm"], source if isinstance(source, str) else None
    return None, None


def attempts_read(job: Job) -> list[CadMepAttemptRead]:
    """История попыток route-задания: параметры из `mep_attempts`, итог - из сохранённых."""
    history = job.payload.get("mep_attempts")
    out: list[CadMepAttemptRead] = []
    for entry in history if isinstance(history, list) else []:
        number = entry.get("attempt") if isinstance(entry, dict) else None
        if type(number) is not int:
            continue
        result = cad_service.result_for_attempt(job, number)
        # В очереди номер попытки ещё не выдан: ожидающая - следующая за последней захваченной.
        current = job.attempt + 1 if job.status is JobStatus.QUEUED else job.attempt
        if number > current:
            status = "queued"
        elif number == current:
            status = job.status.value
        else:
            status = "failed" if result.get("result_status") == "failed" else "succeeded"
        error = job.error_code if number == current else result.get("error_code")
        if status != "failed":
            error = None
        elevation, elevation_source = _result_value(result, "floor_elevation")
        height, height_source = _result_value(result, "floor_height")
        requested_at = entry.get("requested_at")
        out.append(
            CadMepAttemptRead.model_validate(
                {
                    "attempt": number,
                    "requested_elevation_mm": cad_mep_service.entry_int(
                        entry, "floor_elevation_mm"
                    ),
                    "requested_height_mm": cad_mep_service.entry_int(entry, "floor_height_mm"),
                    "requested_at": requested_at if isinstance(requested_at, str) else None,
                    "status": status,
                    "error_code": error if isinstance(error, str) else None,
                    "floor_elevation_mm": elevation,
                    "floor_elevation_source": elevation_source,
                    "floor_height_mm": height,
                    "floor_height_source": height_source,
                }
            )
        )
    return out


class CadViewMepRead(BaseModel):
    """Решения вида: у родителя - одобрение и route-задания, у route-задания - принятие."""

    approval: CadDecisionRead | None = None
    acceptance: CadDecisionRead | None = None
    route_jobs: list[CadRouteJobRead] = Field(default_factory=list)
    # История отозванных решений этого вида (одобрение и принятие), старые сверху.
    revoked_decisions: list[CadDecisionRead] = Field(default_factory=list)


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
    approval_id = cad_mep_service.approval_id_of(job)
    approval = None if approval_id is None else state.approval_by_id.get(approval_id)
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
        approval_id=approval_id,
        approval_revoked=approval is not None and approval.revoked_at is not None,
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
        revoked_decisions=[decision_read(*row) for row in state.revoked.get(key, [])],
    )


class CadMepRoute3dPolyline(BaseModel):
    """3D-полилиния трассы или стояка: слой и вершины (x, y, z_rel), мм."""

    model_config = ConfigDict(extra="forbid")

    layer: Annotated[str, Field(min_length=1, max_length=64)]
    pts: Annotated[list[tuple[int, int, int]], Field(min_length=2)]


class CadMepRoutes3dFile(BaseModel):
    """Файл `routes3d.json` генератора (`cad_mep_routes3d.v1`): трассы с Z от отметки этажа."""

    model_config = ConfigDict(extra="ignore")

    schema_id: Literal["cad_mep_routes3d.v1"] = Field(alias="schema")
    frame: Literal["view_dxf_mm"]
    floor_elevation_mm: int | None
    floor_height_mm: int | None
    polylines: list[CadMepRoute3dPolyline]


class CadMepRoutes3dOut(BaseModel):
    """Трассы листа в 3D: вершины в мм DXF вида, Z - над отметкой этажа (верх плиты)."""

    job_id: UUID
    generator_version: str | None
    # Высоты, от которых построены трассы (из файла).
    floor_elevation_mm: int | None
    floor_height_mm: int | None
    # Действующие уровни листа сейчас (из 3D-вида); None - не определены.
    levels_elevation_mm: int | None
    levels_height_mm: int | None
    # Обе пары известны и равны; иначе - false (трассы стоит перестроить).
    heights_match: bool
    polylines: list[CadMepRoute3dPolyline]


def routes3d_read(
    job: Job,
    data: CadMepRoutes3dFile,
    *,
    levels_elevation_mm: int | None,
    levels_height_mm: int | None,
) -> CadMepRoutes3dOut:
    version = job.payload.get("generator_version")
    return CadMepRoutes3dOut(
        job_id=job.id,
        generator_version=version if isinstance(version, str) else None,
        floor_elevation_mm=data.floor_elevation_mm,
        floor_height_mm=data.floor_height_mm,
        levels_elevation_mm=levels_elevation_mm,
        levels_height_mm=levels_height_mm,
        heights_match=cad_mep_service.heights_match(
            data.floor_elevation_mm,
            data.floor_height_mm,
            levels_elevation_mm,
            levels_height_mm,
        ),
        polylines=data.polylines,
    )
