"""Отделка помещений во вкладке CAD (ADR-0042): шаблоны проекта, назначение зонам, ведомость.

Маршруты закрыты флагом пространства `cad.export` на сервере; доступ - по пространству, проекту и
ревизии, чужое - 404. Шаблон - параметры проекта (вводит человек); количества ведомости сервер
считает при чтении по зонам и уровням листа и нигде не хранит. Ведомость - рабочая таблица пилота,
не ВОР Quantor, не смета и не `Measurement`; в итоги обмера, calc и MEP не входит.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, StorageDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_finishes import (
    CadFinishAssign,
    CadFinishAssignResult,
    CadFinishSheetRead,
    CadFinishTemplatePatch,
    CadFinishTemplateRead,
    CadFinishTemplateWrite,
)
from app.errors import not_found
from app.models import CadFinishTemplate
from app.services import cad as cad_service
from app.services import cad_finish_templates, cad_finishes, cad_partitions, cad_zones
from app.services import projects as projects_service
from app.services.cad_walls_version import current_walls_generator

router = APIRouter(
    tags=["cad-finishes"],
    dependencies=[require_feature("cad.export")],
)


async def _require_project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> None:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")


async def _template(
    session: SessionDep, context: AuthDep, project_id: uuid.UUID, template_id: uuid.UUID
) -> CadFinishTemplate:
    await _require_project(session, context, project_id)
    row = await cad_finish_templates.get_template(
        session, project_id=project_id, template_id=template_id
    )
    if row is None:
        raise not_found("Шаблон отделки")
    return row


@router.get(
    "/projects/{project_id}/cad/finish-templates",
    response_model=list[CadFinishTemplateRead],
    summary="Шаблоны отделки проекта",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_finish_templates(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CadFinishTemplateRead]:
    await _require_project(session, context, project_id)
    rows = await cad_finish_templates.list_templates(session, project_id=project_id)
    return [cad_finish_templates.template_read(row) for row in rows]


@router.post(
    "/projects/{project_id}/cad/finish-templates",
    response_model=CadFinishTemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать шаблон отделки проекта",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_finish_template(
    project_id: uuid.UUID,
    body: CadFinishTemplateWrite,
    session: SessionDep,
    context: AuthDep,
) -> CadFinishTemplateRead:
    """409 `CAD_FINISH_TEMPLATE_NAME_TAKEN` - название занято; `CAD_FINISH_ROOM_TYPE_TAKEN` - тип
    помещения уже у другого шаблона проекта."""
    await _require_project(session, context, project_id)
    row = await cad_finish_templates.create_template(
        session, project_id=project_id, body=body, user_id=context.principal.user_id
    )
    result = cad_finish_templates.template_read(row)
    await session.commit()
    return result


@router.patch(
    "/projects/{project_id}/cad/finish-templates/{template_id}",
    response_model=CadFinishTemplateRead,
    summary="Изменить шаблон отделки",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def update_cad_finish_template(
    project_id: uuid.UUID,
    template_id: uuid.UUID,
    body: CadFinishTemplatePatch,
    session: SessionDep,
    context: AuthDep,
) -> CadFinishTemplateRead:
    row = await _template(session, context, project_id, template_id)
    row = await cad_finish_templates.update_template(session, row=row, body=body)
    result = cad_finish_templates.template_read(row)
    await session.commit()
    return result


@router.delete(
    "/projects/{project_id}/cad/finish-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить шаблон отделки (явные назначения зонам снимаются)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def delete_cad_finish_template(
    project_id: uuid.UUID, template_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> Response:
    row = await _template(session, context, project_id, template_id)
    await cad_finish_templates.delete_template(session, row=row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/cad/zones/finish-assign",
    response_model=CadFinishAssignResult,
    summary="Назначить шаблон отделки зонам проекта (null снимает); двери пропускаются",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def assign_cad_finish_template(
    project_id: uuid.UUID,
    body: CadFinishAssign,
    session: SessionDep,
    context: AuthDep,
) -> CadFinishAssignResult:
    await _require_project(session, context, project_id)
    if body.template_id is not None:
        found = await cad_finish_templates.get_template(
            session, project_id=project_id, template_id=body.template_id
        )
        if found is None:
            raise not_found("Шаблон отделки")
    result = await cad_finish_templates.assign_template(
        session, workspace_id=context.tenant, project_id=project_id, body=body
    )
    await session.commit()
    return result


@router.get(
    "/projects/{project_id}/revisions/{revision_id}/cad/finishes",
    response_model=CadFinishSheetRead,
    summary="Ведомость отделки листа: зоны, слои, итоги, предупреждения (рабочая таблица, не ВОР)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_finishes(
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    settings: SettingsDep,
    page_index: Annotated[int, Query(ge=0)],
) -> CadFinishSheetRead:
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
    zones = await cad_zones.list_zones(session, revision_id=revision_id, page_index=page_index)
    templates = await cad_finish_templates.list_templates(session, project_id=project_id)
    context_sheet = await cad_finishes.load_finish_context(
        session,
        storage,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        current_generator=current_walls_generator(settings),
    )
    return cad_finishes.build_finish_sheet(
        revision_id=revision_id,
        page_index=page_index,
        zones=await cad_zones.zones_read(session, zones),
        templates=[cad_finish_templates.template_read(row) for row in templates],
        levels_wall_height_mm=context_sheet.wall_height_mm,
        walls=context_sheet.walls,
        apartment_without_finish=await cad_partitions.apartment_without_finish(
            session, project_id=project_id
        ),
    )


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
