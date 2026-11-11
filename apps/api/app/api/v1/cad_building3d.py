"""Общий вид здания для 3D во вкладке CAD (ADR-0039): этажи проекта с отметками и контуром плиты.

Маршрут закрыт флагом пространства `cad.export` на сервере; доступ — по пространству и проекту,
чужое — 404. Только чтение: в итоги обмера, таблицы MEP и calc вид не входит.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.v1.deps import AuthDep, SessionDep, StorageDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_building3d import CadBuilding3dRead
from app.errors import not_found
from app.services import cad_building3d
from app.services import projects as projects_service

router = APIRouter(tags=["cad-building3d"], dependencies=[require_feature("cad.export")])


@router.get(
    "/projects/{project_id}/cad/building3d",
    response_model=CadBuilding3dRead,
    summary="Общий вид здания: этажи проекта (листы CAD) с отметками и контуром плиты",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_building3d(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep, storage: StorageDep
) -> CadBuilding3dRead:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return await cad_building3d.build_building3d(
        session, storage, workspace_id=context.tenant, project_id=project_id
    )


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
