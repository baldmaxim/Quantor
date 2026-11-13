"""Очередь CAD проекта (исполнитель берёт задания по одному): что идёт, что ждёт, сколько впереди.
Там же сводка распознавания листов проекта (`/summary`).

Маршрут закрыт флагом пространства `cad.export`; доступ - по пространству и проекту, чужое - 404.
Задания других пространств в ответ не попадают, только общие счётчики исполнителя.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_queue import CadQueueRead
from app.contracts.cad_summary import CadProjectSummaryRead
from app.errors import not_found
from app.services import cad_queue, cad_summary
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/cad",
    tags=["cad-queue"],
    dependencies=[require_feature("cad.export")],
)


@router.get(
    "/queue",
    response_model=CadQueueRead,
    summary="Очередь CAD проекта: выполняется, ждёт, недавно завершено",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_queue(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CadQueueRead:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return await cad_queue.build_queue(session, workspace_id=context.tenant, project_id=project_id)


@router.get(
    "/summary",
    response_model=CadProjectSummaryRead,
    summary="Сводка распознавания CAD проекта: листы готово / идёт / ошибка / не запускалось",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_summary(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CadProjectSummaryRead:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return await cad_summary.build_summary(
        session, workspace_id=context.tenant, project_id=project_id
    )


qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
