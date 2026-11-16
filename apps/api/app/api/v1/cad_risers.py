"""Реестр стояков листа во вкладке CAD (ADR-0041): ввод и чтение человеком по проекту ИОС.

Реестр - вход задания трасс `cad_mep_route` (генератор cad_mep.v6); без него трассы строятся
по подписям шахт АР, как раньше. Маршруты закрыты флагом пространства `cad.export` на сервере;
доступ - по пространству, проекту и ревизии, чужое - 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import AuthDep, SessionDep, StorageDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_risers import (
    CadRisersCopyOut,
    CadRisersSheetsOut,
    CadSheetRisersOut,
    CadSheetRisersPut,
)
from app.errors import DomainError, ErrorCode, not_found
from app.services import cad as cad_service
from app.services import cad_risers, cad_risers_copy
from app.services import projects as projects_service

router = APIRouter(
    tags=["cad-risers"],
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


@router.get(
    "/projects/{project_id}/cad/risers",
    response_model=CadSheetRisersOut,
    summary="Реестр стояков листа по проекту ИОС; не введён - пустой список",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_sheet_risers(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    revision_id: Annotated[uuid.UUID, Query()],
    page_index: Annotated[int, Query(ge=0)],
    view: Annotated[int, Query(ge=0)],
) -> CadSheetRisersOut:
    await _revision_scope(session, context, project_id, revision_id)
    row = await cad_risers.load_row(
        session, revision_id=revision_id, page_index=page_index, view=view
    )
    return CadSheetRisersOut(
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        risers=await cad_risers.load_risers(
            session, revision_id=revision_id, page_index=page_index, view=view
        ),
        updated_at=row.updated_at if row is not None else None,
    )


@router.get(
    "/projects/{project_id}/cad/risers/sheets",
    response_model=CadRisersSheetsOut,
    summary="Листы ревизии с непустым реестром стояков (источники копирования)",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_cad_risers_sheets(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    revision_id: Annotated[uuid.UUID, Query()],
) -> CadRisersSheetsOut:
    await _revision_scope(session, context, project_id, revision_id)
    return CadRisersSheetsOut(
        revision_id=revision_id,
        sheets=await cad_risers_copy.list_sheets(session, revision_id=revision_id),
    )


@router.get(
    "/projects/{project_id}/cad/risers/copy",
    response_model=CadRisersCopyOut,
    summary="Черновик копирования реестра с другого листа: shaft_id переносится по шахтам",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def draft_cad_risers_copy(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
    revision_id: Annotated[uuid.UUID, Query()],
    page_index: Annotated[int, Query(ge=0)],
    view: Annotated[int, Query(ge=0)],
    source_page_index: Annotated[int, Query(ge=0)],
    source_view: Annotated[int, Query(ge=0)],
) -> CadRisersCopyOut:
    await _revision_scope(session, context, project_id, revision_id)
    if (source_page_index, source_view) == (page_index, view):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Лист-источник совпадает с листом, куда копируют"
        )
    risers = await cad_risers.load_risers(
        session, revision_id=revision_id, page_index=source_page_index, view=source_view
    )
    if not risers:
        raise not_found("Реестр стояков листа-источника")
    return await cad_risers_copy.copy_draft(
        session,
        storage,
        workspace_id=context.tenant,
        project_id=project_id,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        source_page_index=source_page_index,
        source_view=source_view,
        risers=risers,
    )


@router.put(
    "/projects/{project_id}/cad/risers",
    response_model=CadSheetRisersOut,
    summary="Сохранить реестр стояков листа (заменяется целиком; пустой список - реестра нет)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_cad_sheet_risers(
    project_id: uuid.UUID,
    body: CadSheetRisersPut,
    session: SessionDep,
    context: AuthDep,
    revision_id: Annotated[uuid.UUID, Query()],
    page_index: Annotated[int, Query(ge=0)],
    view: Annotated[int, Query(ge=0)],
) -> CadSheetRisersOut:
    await _revision_scope(session, context, project_id, revision_id)
    updated_at = await cad_risers.save_risers(
        session,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        risers=body.risers,
        user_id=context.principal.user_id,
    )
    response = CadSheetRisersOut(
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        risers=body.risers,
        updated_at=updated_at,
    )
    await session.commit()
    return response


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
