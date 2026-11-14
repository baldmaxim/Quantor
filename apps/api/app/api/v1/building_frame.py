"""Каркас здания (ADR-0043, С2): сборка из паспортов, правка, подтверждение и проверки.

Маршруты закрыты флагом пространства `project.consistency` на сервере; чтение - право чтения
документов, сборка и правка - право загрузки. Чужой проект - 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.building_frame import (
    FrameBulkOut,
    FrameBulkStatus,
    FrameNodeCreate,
    FrameNodeOut,
    FrameNodePatch,
    FrameOut,
    FrameRebuildOut,
)
from app.errors import not_found
from app.services import building_frame
from app.services import projects as projects_service

router = APIRouter(
    tags=["building-frame"],
    dependencies=[require_feature("project.consistency")],
)


async def _project_id(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> uuid.UUID:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project.id


@router.get(
    "/projects/{project_id}/frame",
    response_model=FrameOut,
    summary="Каркас здания проекта и проверки комплектности по подтверждённым данным",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_building_frame(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> FrameOut:
    await _project_id(session, context, project_id)
    return await building_frame.frame_view(session, project_id=project_id)


@router.post(
    "/projects/{project_id}/frame/rebuild",
    response_model=FrameRebuildOut,
    summary="Пересобрать кандидатов каркаса из подтверждённых паспортов листов",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def rebuild_building_frame(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> FrameRebuildOut:
    await _project_id(session, context, project_id)
    result = await building_frame.rebuild(session, project_id=project_id)
    await session.commit()
    return result


@router.post(
    "/projects/{project_id}/frame/nodes",
    response_model=FrameNodeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить узел каркаса вручную; недостающие корпус и секция создаются",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_frame_node(
    project_id: uuid.UUID, body: FrameNodeCreate, session: SessionDep, context: AuthDep
) -> FrameNodeOut:
    await _project_id(session, context, project_id)
    response = await building_frame.create_node(session, project_id=project_id, body=body)
    await session.commit()
    return response


@router.post(
    "/projects/{project_id}/frame/bulk-status",
    response_model=FrameBulkOut,
    summary="Единый статус пачке узлов каркаса; чужой id - 404, ничего не меняется",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def bulk_frame_status(
    project_id: uuid.UUID, body: FrameBulkStatus, session: SessionDep, context: AuthDep
) -> FrameBulkOut:
    await _project_id(session, context, project_id)
    updated = await building_frame.bulk_status(
        session,
        project_id=project_id,
        ids=body.ids,
        status=body.status,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return FrameBulkOut(updated=updated)


@router.patch(
    "/projects/{project_id}/frame/nodes/{node_id}",
    response_model=FrameNodeOut,
    summary="Правка уровня (номер, отметка, высота) и/или статуса узла каркаса",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def patch_frame_node(
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    body: FrameNodePatch,
    session: SessionDep,
    context: AuthDep,
) -> FrameNodeOut:
    await _project_id(session, context, project_id)
    response = await building_frame.patch_node(
        session,
        project_id=project_id,
        node_id=node_id,
        patch=body,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return response


@router.delete(
    "/projects/{project_id}/frame/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить узел, добавленный вручную; узел из паспортов можно только отклонить",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def delete_frame_node(
    project_id: uuid.UUID, node_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> None:
    await _project_id(session, context, project_id)
    await building_frame.delete_node(session, project_id=project_id, node_id=node_id)
    await session.commit()


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
