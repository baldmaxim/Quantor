"""Паспорт листа (ADR-0043, С1): запуск разбора комплекта, таблица листов, правка и подтверждение.

Маршруты закрыты флагом пространства `project.consistency` на сервере; чтение - право чтения
документов, запуск и правка - право загрузки. Чужой проект - 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.sheet_passports import (
    LIST_MAX,
    SheetPassportBulkOut,
    SheetPassportBulkStatus,
    SheetPassportExtractSummary,
    SheetPassportListOut,
    SheetPassportOut,
    SheetPassportPatch,
    SheetPassportStatus,
)
from app.errors import not_found
from app.models import Project
from app.schemas import JobRead
from app.services import projects as projects_service
from app.services import sheet_passports

router = APIRouter(
    tags=["sheet-passports"],
    dependencies=[require_feature("project.consistency")],
)


async def _project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


@router.post(
    "/projects/{project_id}/sheet-passports/extract",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить разбор паспортов листов проекта; активное задание возвращается как есть",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_sheet_passport_extract(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> JobRead:
    project = await _project(session, context, project_id)
    job = await sheet_passports.schedule_extract(session, project=project)
    response = JobRead.model_validate(job)
    await session.commit()
    return response


@router.get(
    "/projects/{project_id}/sheet-passports/extract-summary",
    response_model=SheetPassportExtractSummary | None,
    summary="Итог последнего разбора листов проекта; null, если заданий не было",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_sheet_passport_extract_summary(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> SheetPassportExtractSummary | None:
    await _project(session, context, project_id)
    return await sheet_passports.latest_extract_summary(
        session, workspace_id=context.tenant, project_id=project_id
    )


@router.get(
    "/projects/{project_id}/sheet-passports",
    response_model=SheetPassportListOut,
    summary="Паспорта листов проекта: по файлу и странице, с фильтрами",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_sheet_passports(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    status_filter: Annotated[SheetPassportStatus | None, Query(alias="status")] = None,
    section_mark: Annotated[str | None, Query(max_length=32)] = None,
    revision_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=LIST_MAX)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SheetPassportListOut:
    await _project(session, context, project_id)
    items, total = await sheet_passports.list_passports(
        session,
        project_id=project_id,
        status=status_filter,
        section_mark=section_mark,
        revision_id=revision_id,
        limit=limit,
        offset=offset,
    )
    return SheetPassportListOut(items=items, total=total)


@router.post(
    "/projects/{project_id}/sheet-passports/bulk-status",
    response_model=SheetPassportBulkOut,
    summary="Единый статус пачке паспортов; чужой id - 404, ничего не меняется",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def bulk_sheet_passport_status(
    project_id: uuid.UUID, body: SheetPassportBulkStatus, session: SessionDep, context: AuthDep
) -> SheetPassportBulkOut:
    await _project(session, context, project_id)
    updated = await sheet_passports.bulk_status(
        session,
        project_id=project_id,
        ids=body.ids,
        status=body.status,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return SheetPassportBulkOut(updated=updated)


@router.patch(
    "/projects/{project_id}/sheet-passports/{passport_id}",
    response_model=SheetPassportOut,
    summary="Правка полей паспорта и/или статуса; правленое поле получает источник manual",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def patch_sheet_passport(
    project_id: uuid.UUID,
    passport_id: uuid.UUID,
    body: SheetPassportPatch,
    session: SessionDep,
    context: AuthDep,
) -> SheetPassportOut:
    await _project(session, context, project_id)
    response = await sheet_passports.patch_passport(
        session,
        project_id=project_id,
        passport_id=passport_id,
        patch=body,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return response


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
