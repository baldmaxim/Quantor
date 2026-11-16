"""Ручная привязка корпуса к площадке в 3D «Весь объект» (ADR-0052).

Маршруты закрыты флагом пространства `cad.export` на сервере; доступ - по пространству и проекту,
чужое - 404. Чтение - `DOCUMENT_READ`, запись и отзыв - `DOCUMENT_UPLOAD`. Привязка не правится:
новая привязка того же листа-источника отзывает прежнюю, отзыв оставляет запись.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_site_pins import (
    CadSitePinCreate,
    CadSitePinRead,
    CadSitePinRevoke,
    CadSitePinsRead,
    site_pin_read,
)
from app.errors import not_found
from app.models import Project
from app.services import cad_site_pins
from app.services import projects as projects_service

router = APIRouter(tags=["cad-building3d"], dependencies=[require_feature("cad.export")])


async def _project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


@router.get(
    "/projects/{project_id}/cad/building3d/site-pins",
    response_model=CadSitePinsRead,
    summary="Действующие ручные привязки корпусов к площадке",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_site_pins(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CadSitePinsRead:
    project = await _project(session, context, project_id)
    rows = await cad_site_pins.list_active(session, project_id=project.id)
    return CadSitePinsRead(
        items=[site_pin_read(row, await cad_site_pins.author_name(session, row)) for row in rows]
    )


@router.post(
    "/projects/{project_id}/cad/building3d/site-pins",
    response_model=CadSitePinRead,
    status_code=status.HTTP_201_CREATED,
    summary="Привязать корпус к площадке по двум парам точек (прежняя привязка листа отзывается)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_site_pin(
    project_id: uuid.UUID, body: CadSitePinCreate, session: SessionDep, context: AuthDep
) -> CadSitePinRead:
    project = await _project(session, context, project_id)
    pin = await cad_site_pins.create_pin(
        session, project=project, body=body, user_id=context.principal.user_id
    )
    result = site_pin_read(pin, await cad_site_pins.author_name(session, pin))
    await session.commit()
    return result


@router.delete(
    "/projects/{project_id}/cad/building3d/site-pins/{pin_id}",
    response_model=CadSitePinRead,
    summary="Отозвать привязку корпуса к площадке; запись остаётся",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def revoke_site_pin(
    project_id: uuid.UUID,
    pin_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    body: Annotated[CadSitePinRevoke | None, Body()] = None,
) -> CadSitePinRead:
    project = await _project(session, context, project_id)
    pin = await cad_site_pins.pin_in_project(session, project_id=project.id, pin_id=pin_id)
    await cad_site_pins.revoke_pin(
        session,
        pin=pin,
        reason=None if body is None else body.reason,
        user_id=context.principal.user_id,
    )
    result = site_pin_read(pin, await cad_site_pins.author_name(session, pin))
    await session.commit()
    return result


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
