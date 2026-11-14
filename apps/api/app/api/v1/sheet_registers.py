"""Ведомости листов (ADR-0043, С2, «ведомость ↔ листы»): разбор, выдача и подтверждение.

Маршруты закрыты флагом пространства `project.consistency` на сервере; чтение - право чтения
документов, запуск разбора и подтверждение - право загрузки. Чужой проект - 404. Проверки
«ведомость ↔ листы» отдаёт каркас здания (`GET /projects/{id}/frame`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.sheet_registers import (
    SheetRegisterBulkOut,
    SheetRegisterBulkStatus,
    SheetRegistersOut,
)
from app.errors import not_found
from app.models import Project
from app.schemas import JobRead
from app.services import projects as projects_service
from app.services import sheet_registers

router = APIRouter(
    tags=["sheet-registers"],
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
    "/projects/{project_id}/sheet-registers/extract",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить разбор ведомостей листов по тексту страниц; активное задание возвращается",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_sheet_register_extract(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> JobRead:
    project = await _project(session, context, project_id)
    job = await sheet_registers.schedule_extract(session, project=project)
    response = JobRead.model_validate(job)
    await session.commit()
    return response


@router.get(
    "/projects/{project_id}/sheet-registers",
    response_model=SheetRegistersOut,
    summary="Ведомости листов последних ревизий PDF и итог последнего разбора",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_sheet_registers(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> SheetRegistersOut:
    await _project(session, context, project_id)
    return await sheet_registers.registers_view(
        session, workspace_id=context.tenant, project_id=project_id
    )


@router.post(
    "/projects/{project_id}/sheet-registers/bulk-status",
    response_model=SheetRegisterBulkOut,
    summary="Единый статус пачке ведомостей листов; чужой id - 404, ничего не меняется",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def bulk_sheet_register_status(
    project_id: uuid.UUID, body: SheetRegisterBulkStatus, session: SessionDep, context: AuthDep
) -> SheetRegisterBulkOut:
    await _project(session, context, project_id)
    updated = await sheet_registers.bulk_status(
        session,
        project_id=project_id,
        ids=body.ids,
        status=body.status,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return SheetRegisterBulkOut(updated=updated)


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
