"""Общий вид здания для 3D во вкладке CAD (ADR-0039): этажи проекта с отметками и контуром плиты.

Маршрут закрыт флагом пространства `cad.export` на сервере; доступ — по пространству и проекту,
чужое — 404. Только чтение: в итоги обмера, таблицы MEP и calc вид не входит.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

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
from app.contracts.cad_ai_coordination import AiCoordinationStart, AiCoordinationStarted
from app.contracts.cad_building3d import CadBuilding3dRead
from app.contracts.cad_project_context import CadProjectContextRead
from app.errors import DomainError, ErrorCode, not_found
from app.services import cad_axis_coordination_jobs, cad_building3d_assembly, cad_project_context
from app.services import projects as projects_service

router = APIRouter(tags=["cad-building3d"], dependencies=[require_feature("cad.export")])


@router.get(
    "/projects/{project_id}/cad/building3d",
    response_model=CadBuilding3dRead,
    summary="Общий вид здания: этажи проекта (листы CAD) с отметками и контуром плиты",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_building3d(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    walls: Annotated[
        bool,
        Query(description="Добавить контуры конструкций этажей (по умолчанию ответ лёгкий)"),
    ] = False,
) -> CadBuilding3dRead:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return await cad_building3d_assembly.build_building3d(
        session, storage, workspace_id=context.tenant, project_id=project_id, include_walls=walls
    )


@router.post(
    "/projects/{project_id}/cad/building3d/axis-coordination",
    response_model=AiCoordinationStarted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить ИИ-координацию осей вида с эталоном «Здания» (пилот)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_axis_coordination(
    project_id: uuid.UUID,
    body: AiCoordinationStart,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> AiCoordinationStarted:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    job, target_id = await cad_axis_coordination_jobs.start_for_view(
        session,
        settings,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=body.revision_id,
        page_index=body.page_index,
        view=body.view,
    )
    result = AiCoordinationStarted(
        job_id=job.id,
        status=job.status.value,
        target_walls_job_id=target_id,
    )
    await session.commit()
    return result


@router.get(
    "/projects/{project_id}/cad/project-context",
    response_model=CadProjectContextRead,
    summary="Проектный контекст CAD: координатная сетка, высоты (разрезы/КР), фасады и зоны",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_project_context(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    revision_id: Annotated[
        uuid.UUID | None,
        Query(description="Ревизия фокусного вида (вместе с page_index и view)"),
    ] = None,
    page_index: Annotated[
        int | None,
        Query(ge=0, description="Индекс страницы фокусного вида с 0"),
    ] = None,
    view: Annotated[
        int | None,
        Query(ge=0, description="Номер фокусного вида на странице"),
    ] = None,
) -> CadProjectContextRead:
    focus_args = (revision_id is not None, page_index is not None, view is not None)
    if any(focus_args) and not all(focus_args):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Для фокусного вида укажите вместе revision_id, page_index и view",
        )
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return await cad_project_context.build_project_context(
        session,
        storage,
        project=project,
        focus_revision_id=revision_id,
        focus_page_index=page_index,
        focus_view=view,
    )


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
