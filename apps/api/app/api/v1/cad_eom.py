"""ЭОМ и СС этажа: постановка по одобренному виду, состояние задания, сети и ведомость в 3D.

Границы те же, что у трасс механики: маршруты закрыты флагом пространства `cad.export`, доступ -
по пространству, проекту и ревизии; чужое - 404. Одобрение вида общее с механикой (одно решение
человека на вид), отметка пола, высота этажа и уровни - те же, что у трасс механики листа.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import ValidationError

from app.api.v1.cad import _job, _read_artifact_json, _scope
from app.api.v1.cad_constructions import _Sheet
from app.api.v1.cad_mep import _route_sheet_levels, _sheet_levels
from app.api.v1.deps import (
    AuthDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    require,
    require_feature,
)
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_eom import (
    CadEomJobRead,
    CadEomRoutes3dFile,
    CadEomRoutes3dOut,
    routes3d_read,
)
from app.contracts.cad_mep import CadMepRoutesCreate
from app.domain import JobType
from app.errors import DomainError, ErrorCode, not_found
from app.services import cad as cad_service
from app.services import cad_eom as cad_eom_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_sections

router = APIRouter(
    prefix="/projects/{project_id}/revisions/{revision_id}/cad",
    tags=["cad-eom"],
    dependencies=[require_feature("cad.export")],
)


@router.post(
    "/{job_id}/views/{page_index}/{view}/eom-routes",
    response_model=CadEomJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Поставить построение ЭОМ и СС этажа по одобренному виду",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_eom_routes(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    body: CadMepRoutesCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> CadEomJobRead:
    project, _revision = await _scope(session, context, project_id, revision_id)
    job = await _job(session, context, project_id, revision_id, job_id)
    level_elevation, level_height = (None, None)
    if job.job_type is JobType.CAD_PDF_CONVERT:
        level_elevation, level_height = await _sheet_levels(
            session, storage, _Sheet(job, revision_id, page_index, view, project_id)
        )
    floor_elevation, floor_height = cad_mep_service.merge_floor_params(
        requested_elevation_mm=body.floor_elevation_mm,
        requested_height_mm=body.floor_height_mm,
        level_elevation_mm=level_elevation,
        level_height_mm=level_height,
    )
    levels = await cad_sections.resolve_route_levels(
        session,
        settings=settings,
        workspace_id=project.workspace_id,
        project_id=project_id,
        floor_elevation_mm=floor_elevation,
        plan_revision_id=revision_id,
        plan_page_index=page_index,
    )
    route = await cad_eom_service.schedule_eom(
        session,
        project=project,
        job=job,
        attempt=body.attempt,
        page_index=page_index,
        view=view,
        floor_elevation_mm=floor_elevation,
        floor_height_mm=floor_height,
        settings=settings,
        clear_height_mm=levels.clear_height_mm,
        slab_thickness_mm=levels.slab_thickness_mm,
        levels_source=levels.source,
    )
    await session.commit()
    return CadEomJobRead.of(route)


# Чтение по листу (ревизия, страница, вид), а не по заданию - как 3D-трассы механики.
sheet_router = APIRouter(
    prefix="/projects/{project_id}/cad/eom",
    tags=["cad-eom"],
    dependencies=[require_feature("cad.export")],
)


@sheet_router.get(
    "/job",
    response_model=CadEomJobRead,
    summary="Новейшее задание ЭОМ и СС листа в любом статусе (ход и отказ)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_eom_job(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
) -> CadEomJobRead:
    await _scope(session, context, project_id, revision_id)
    job = await cad_eom_service.latest_eom_job(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
    )
    if job is None:
        raise DomainError(ErrorCode.CAD_EOM_NOT_FOUND)
    return CadEomJobRead.of(job)


@sheet_router.get(
    "/routes3d",
    response_model=CadEomRoutes3dOut,
    summary="ЭОМ и СС листа в 3D: сети и приборы (мм DXF вида, Z от отметки этажа) и ведомость",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_eom_routes3d(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadEomRoutes3dOut:
    await _scope(session, context, project_id, revision_id)
    job = await cad_eom_service.latest_succeeded_eom_job(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
    )
    if job is None:
        raise DomainError(ErrorCode.CAD_EOM_NOT_FOUND)
    attempt = cad_service.result_of(job).get("attempt")
    try:
        folder = cad_service.view_folder(page_index, view)
    except ValueError as error:
        raise not_found("Вид") from error
    if type(attempt) is not int:
        raise DomainError(ErrorCode.CAD_EOM_NOT_FOUND)
    raw = await _read_artifact_json(
        storage, job, revision_id, attempt, f"{folder}/{cad_eom_service.ROUTES3D_JSON}"
    )
    if raw is None:
        raise DomainError(ErrorCode.CAD_EOM_NOT_FOUND)
    try:
        data = CadEomRoutes3dFile.model_validate(raw)
    except ValidationError as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "eom_routes3d.json вне контракта") from error
    candidate = await _read_artifact_json(
        storage, job, revision_id, attempt, f"{folder}/{cad_eom_service.CANDIDATE_JSON}"
    )
    elevation, height = await _route_sheet_levels(
        session, context, storage, job, revision_id, project_id, page_index, view
    )
    return routes3d_read(
        job,
        data,
        candidate if isinstance(candidate, dict) else None,
        levels_elevation_mm=elevation,
        levels_height_mm=height,
    )


qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
qa_router.include_router(sheet_router)
