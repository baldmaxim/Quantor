"""Трассы механики (ADR-0036 п. 8): одобрение вида, постановка трасс, принятие трасс.

Те же границы, что у остального CAD: маршруты закрыты флагом пространства `cad.export`,
доступ - по пространству, проекту и ревизии; чужое - 404. Решения человека неизменяемы и
не имеют отмены. Чтение (задание, вид, превью, файлы, замечания) - общие маршруты CAD.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.v1.cad import _job, _scope
from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad import CadJobRead
from app.contracts.cad_mep import (
    CadAcceptanceCreate,
    CadApprovalCreate,
    CadDecisionRead,
    CadMepRoutesCreate,
    decision_read,
)
from app.services import cad_mep as cad_mep_service

router = APIRouter(
    prefix="/projects/{project_id}/revisions/{revision_id}/cad",
    tags=["cad-mep"],
    dependencies=[require_feature("cad.export")],
)


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
) -> CadJobRead:
    project, _revision = await _scope(session, context, project_id, revision_id)
    job = await _job(session, context, project_id, revision_id, job_id)
    route = await cad_mep_service.schedule_routes(
        session,
        project=project,
        job=job,
        attempt=body.attempt,
        page_index=page_index,
        view=view,
        floor_elevation_mm=body.floor_elevation_mm,
        floor_height_mm=body.floor_height_mm,
        settings=settings,
    )
    await session.commit()
    return CadJobRead.of(route, await cad_mep_service.load_state(session, [route]))


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


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
