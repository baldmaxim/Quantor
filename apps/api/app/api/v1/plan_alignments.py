"""Совмещение планов с уровнем (ADR-0043, С3): запуск, выдача и подтверждение.

Маршруты закрыты флагом пространства `project.consistency` на сервере; чтение - право чтения
документов, запуск и подтверждение - право загрузки. Чужой проект - 404. Проверку «план ↔
уровень» отдаёт каркас здания (`GET /projects/{id}/frame`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.plan_alignments import (
    PlanAlignmentBulkOut,
    PlanAlignmentBulkStatus,
    PlanAlignmentsOut,
)
from app.errors import not_found
from app.models import Project
from app.schemas import JobRead
from app.services import plan_alignments
from app.services import projects as projects_service

router = APIRouter(
    tags=["plan-alignments"],
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
    "/projects/{project_id}/plan-alignments/run",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить совмещение планов с уровнями по осям CAD; активное задание возвращается",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_plan_align(project_id: uuid.UUID, session: SessionDep, context: AuthDep) -> JobRead:
    project = await _project(session, context, project_id)
    job = await plan_alignments.schedule_align(session, project=project)
    response = JobRead.model_validate(job)
    await session.commit()
    return response


@router.get(
    "/projects/{project_id}/plan-alignments",
    response_model=PlanAlignmentsOut,
    summary="Совмещения планов последних ревизий с уровнями и итог последнего запуска",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_plan_alignments(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> PlanAlignmentsOut:
    await _project(session, context, project_id)
    return await plan_alignments.alignments_view(
        session, workspace_id=context.tenant, project_id=project_id
    )


@router.post(
    "/projects/{project_id}/plan-alignments/bulk-status",
    response_model=PlanAlignmentBulkOut,
    summary="Единый статус пачке совмещений планов; чужой id - 404, ничего не меняется",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def bulk_plan_alignment_status(
    project_id: uuid.UUID, body: PlanAlignmentBulkStatus, session: SessionDep, context: AuthDep
) -> PlanAlignmentBulkOut:
    await _project(session, context, project_id)
    updated = await plan_alignments.bulk_status(
        session,
        project_id=project_id,
        ids=body.ids,
        status=body.status,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return PlanAlignmentBulkOut(updated=updated)


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
