"""Зоны листа во вкладке CAD (ADR-0036): помещения квартир, помещения МОП, двери.

Разметка человека - эталон для движка и вход будущего расчёта отделки, не обмер. Маршруты
закрыты флагом пространства `cad.export` на сервере; доступ - по пространству, проекту и
ревизии, чужое - 404. Площадь, периметр и ширину считает сервер по калибровке листа.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.cad_constructions import _sheet
from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_zones import CadZoneCreate, CadZoneRead, CadZoneUpdate
from app.contracts.cad_zones_auto import CadZonesJobRead
from app.errors import not_found
from app.models import CadZone
from app.services import cad as cad_service
from app.services import cad_zones, cad_zones_auto
from app.services import projects as projects_service

router = APIRouter(
    tags=["cad-zones"],
    dependencies=[require_feature("cad.export")],
)


async def _revision_scope(
    session: SessionDep, context: AuthDep, project_id: uuid.UUID, revision_id: uuid.UUID
) -> None:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    if (
        await cad_service.revision_in_project(session, project=project, revision_id=revision_id)
        is None
    ):
        raise not_found("Ревизия")


async def _zone(session: SessionDep, context: AuthDep, zone_id: uuid.UUID) -> CadZone:
    zone = await cad_zones.get_zone(session, workspace_id=context.tenant, zone_id=zone_id)
    if zone is None:
        raise not_found("Зона")
    return zone


@router.get(
    "/projects/{project_id}/cad/zones",
    response_model=list[CadZoneRead],
    summary="Зоны ревизии (помещения и двери) с площадью, периметром и шириной",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_zones(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    revision_id: Annotated[uuid.UUID, Query()],
    page_index: Annotated[int | None, Query(ge=0)] = None,
) -> list[CadZoneRead]:
    await _revision_scope(session, context, project_id, revision_id)
    zones = await cad_zones.list_zones(session, revision_id=revision_id, page_index=page_index)
    return await cad_zones.zones_read(session, zones)


@router.post(
    "/projects/{project_id}/cad/zones",
    response_model=CadZoneRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать зону листа",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_zone(
    project_id: uuid.UUID,
    body: CadZoneCreate,
    session: SessionDep,
    context: AuthDep,
) -> CadZoneRead:
    await _revision_scope(session, context, project_id, body.revision_id)
    zone = await cad_zones.create_zone(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        body=body,
        user_id=context.principal.user_id,
    )
    result = (await cad_zones.zones_read(session, [zone]))[0]
    await session.commit()
    return result


@router.patch(
    "/cad/zones/{zone_id}",
    response_model=CadZoneRead,
    summary="Изменить зону листа",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def update_cad_zone(
    zone_id: uuid.UUID,
    body: CadZoneUpdate,
    session: SessionDep,
    context: AuthDep,
) -> CadZoneRead:
    zone = await _zone(session, context, zone_id)
    zone = await cad_zones.update_zone(session, zone=zone, body=body)
    result = (await cad_zones.zones_read(session, [zone]))[0]
    await session.commit()
    return result


@router.delete(
    "/cad/zones/{zone_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить зону листа",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def delete_cad_zone(zone_id: uuid.UUID, session: SessionDep, context: AuthDep) -> Response:
    zone = await _zone(session, context, zone_id)
    await cad_zones.delete_zone(session, zone=zone)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}/zones/auto",
    response_model=CadZonesJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить автоматическую разметку зон вида: поставить задание cad_zones",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_cad_zones_auto(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    page_index: int,
    view: int,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> CadZonesJobRead:
    """409 `CAD_ZONES_NOT_EMPTY` - на листе уже есть зоны; 409 `CAD_ZONES_BUSY` - разметка идёт."""
    sheet = await _sheet(session, context, project_id, job_id, page_index, view)
    job = await cad_zones_auto.schedule_manual(
        session, parent=sheet.parent, page_index=page_index, view=view, settings=settings
    )
    response = CadZonesJobRead(
        job_id=job.id,
        parent_job_id=sheet.parent.id,
        page_index=page_index,
        view=view,
        status=job.status,
        attempt=job.attempt,
        created_at=job.created_at,
    )
    await session.commit()
    return response


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
