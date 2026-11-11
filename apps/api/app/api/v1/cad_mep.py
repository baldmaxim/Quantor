"""Трассы механики (ADR-0036 п. 8): одобрение вида, постановка трасс, принятие трасс.

Те же границы, что у остального CAD: маршруты закрыты флагом пространства `cad.export`,
доступ - по пространству, проекту и ревизии; чужое - 404. Решения человека не правятся и не
удаляются; отозвать можно (запись остаётся с отметкой отзыва). Чтение (задание, вид, превью,
файлы, замечания) - общие маршруты CAD.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import ValidationError

from app.api.v1.cad import _job, _read_artifact_json, _scope
from app.api.v1.cad_constructions import _load_walls, _Sheet
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
from app.contracts.cad import CadJobRead
from app.contracts.cad_mep import (
    CadAcceptanceCreate,
    CadApprovalCreate,
    CadDecisionRead,
    CadMepRecomputeCreate,
    CadMepRoutes3dFile,
    CadMepRoutes3dOut,
    CadMepRoutesCreate,
    CadRevokeCreate,
    decision_read,
    routes3d_read,
)
from app.domain import JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_construction_store as construction_store
from app.services import cad_constructions
from app.services import cad_mep as cad_mep_service

router = APIRouter(
    prefix="/projects/{project_id}/revisions/{revision_id}/cad",
    tags=["cad-mep"],
    dependencies=[require_feature("cad.export")],
)


async def _sheet_levels(
    session: SessionDep, storage: StorageDep, sheet: _Sheet
) -> tuple[int | None, int | None]:
    """Отметка этажа и высота этажа листа - те же `effective_levels`, что у 3D-вида (ADR-0039).

    Конструкции вида не посчитаны или файл вне контракта - уровни не определены (`None`).
    """
    try:
        walls = await _load_walls(session, storage, sheet)
    except DomainError as error:
        if error.code in (ErrorCode.CAD_WALLS_NOT_READY, ErrorCode.CAD_ENGINE_FAILED):
            return None, None
        raise
    overrides = await construction_store.load_levels(
        session, revision_id=sheet.revision_id, page_index=sheet.page_index, view=sheet.view
    )
    project_slab = await construction_store.load_project_slab(session, project_id=sheet.project_id)
    levels = cad_constructions.effective_levels(walls.document.heights, overrides, project_slab)
    return levels.elevation_mm, levels.floor_height.value_mm


@router.post(
    "/{job_id}/views/{page_index}/{view}/approval",
    response_model=CadDecisionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Одобрить вид результата CAD для построения трасс (решение человека)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def approve_cad_view(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    body: CadApprovalCreate,
    session: SessionDep,
    context: AuthDep,
) -> CadDecisionRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    decision = await cad_mep_service.approve_view(
        session,
        job=job,
        attempt=body.attempt,
        page_index=page_index,
        view=view,
        comment=body.comment,
        user_id=context.principal.user_id,
    )
    result = decision_read(decision, await cad_mep_service.decision_author(session, decision))
    await session.commit()
    return result


@router.post(
    "/{job_id}/views/{page_index}/{view}/mep-routes",
    response_model=CadJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Поставить построение трасс механики по одобренному виду",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_mep_routes(
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
) -> CadJobRead:
    project, _revision = await _scope(session, context, project_id, revision_id)
    job = await _job(session, context, project_id, revision_id, job_id)
    # Не заданные в запросе отметка и высота - из уровней листа (как в 3D); заданные главнее.
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
    route = await cad_mep_service.schedule_routes(
        session,
        project=project,
        job=job,
        attempt=body.attempt,
        page_index=page_index,
        view=view,
        floor_elevation_mm=floor_elevation,
        floor_height_mm=floor_height,
        user_id=context.principal.user_id,
        settings=settings,
    )
    await session.commit()
    return CadJobRead.of(route, await cad_mep_service.load_state(session, [route]))


@router.post(
    "/{job_id}/recompute",
    response_model=CadJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Пересчитать трассы: новая попытка того же задания с другими отметкой и высотой",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def recompute_cad_mep_routes(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    body: CadMepRecomputeCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> CadJobRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    await cad_mep_service.recompute_routes(
        session,
        job=job,
        floor_elevation_mm=body.floor_elevation_mm,
        floor_height_mm=body.floor_height_mm,
        user_id=context.principal.user_id,
        settings=settings,
    )
    await session.commit()
    return CadJobRead.of(job, await cad_mep_service.load_state(session, [job]))


@router.post(
    "/{job_id}/acceptance",
    response_model=CadDecisionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Принять трассы этажа: открывает скачивание DXF трасс (решение человека)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def accept_cad_mep_routes(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    job_id: uuid.UUID,
    body: CadAcceptanceCreate,
    session: SessionDep,
    context: AuthDep,
) -> CadDecisionRead:
    job = await _job(session, context, project_id, revision_id, job_id)
    decision = await cad_mep_service.accept_routes(
        session,
        job=job,
        attempt=body.attempt,
        comment=body.comment,
        user_id=context.principal.user_id,
    )
    result = decision_read(decision, await cad_mep_service.decision_author(session, decision))
    await session.commit()
    return result


@router.post(
    "/decisions/{decision_id}/revoke",
    response_model=CadDecisionRead,
    summary="Отозвать решение (одобрение вида или принятие трасс); запись остаётся",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def revoke_cad_decision(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    decision_id: uuid.UUID,
    body: CadRevokeCreate,
    session: SessionDep,
    context: AuthDep,
) -> CadDecisionRead:
    await _scope(session, context, project_id, revision_id)
    decision = await cad_mep_service.decision_in_scope(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        decision_id=decision_id,
    )
    await cad_mep_service.revoke_decision(
        session, decision=decision, reason=body.reason, user_id=context.principal.user_id
    )
    result = decision_read(
        decision,
        await cad_mep_service.decision_author(session, decision),
        await cad_mep_service.revoker_name(session, decision),
    )
    await session.commit()
    return result


# 3D-трассы листа: адрес по листу (ревизия, страница, вид), а не по заданию.
routes3d_router = APIRouter(
    prefix="/projects/{project_id}/cad/mep",
    tags=["cad-mep"],
    dependencies=[require_feature("cad.export")],
)


@routes3d_router.get(
    "/routes3d",
    response_model=CadMepRoutes3dOut,
    summary="Трассы механики листа в 3D: вершины в мм DXF вида, Z от отметки этажа",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_mep_routes3d(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> CadMepRoutes3dOut:
    await _scope(session, context, project_id, revision_id)
    route = await cad_mep_service.latest_succeeded_route_job(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
    )
    if route is None:
        raise DomainError(ErrorCode.CAD_ROUTES_NOT_FOUND)
    attempt = cad_service.result_of(route).get("attempt")
    try:
        name = f"{cad_service.view_folder(page_index, view)}/{cad_mep_service.ROUTES3D_JSON}"
    except ValueError as error:
        raise not_found("Вид") from error
    raw = (
        await _read_artifact_json(storage, route, revision_id, attempt, name)
        if type(attempt) is int
        else None
    )
    if raw is None:
        raise DomainError(ErrorCode.CAD_ROUTES3D_MISSING)
    try:
        data = CadMepRoutes3dFile.model_validate(raw)
    except ValidationError as error:
        raise DomainError(ErrorCode.CAD_ENGINE_FAILED, "routes3d.json вне контракта") from error
    elevation, height = await _route_sheet_levels(
        session, context, storage, route, revision_id, project_id, page_index, view
    )
    return routes3d_read(route, data, levels_elevation_mm=elevation, levels_height_mm=height)


async def _route_sheet_levels(
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    route: Job,
    revision_id: uuid.UUID,
    project_id: uuid.UUID,
    page_index: int,
    view: int,
) -> tuple[int | None, int | None]:
    """Уровни листа для родителя route-задания; нет родителя - не определены."""
    parent_id = cad_mep_service.parent_job_id_of(route)
    parent = (
        None
        if parent_id is None
        else await cad_service.get_cad_job(
            session,
            workspace_id=context.tenant,
            project_id=project_id,
            revision_id=revision_id,
            job_id=parent_id,
        )
    )
    if parent is None or parent.job_type is not JobType.CAD_PDF_CONVERT:
        return None, None
    return await _sheet_levels(
        session, storage, _Sheet(parent, revision_id, page_index, view, project_id)
    )


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
qa_router.include_router(routes3d_router)
