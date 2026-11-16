"""Фасады АР во вкладке CAD: задание, кандидаты видов и решения человека (ADR-0048).

Маршруты закрыты флагом пространства `cad.export` на сервере; доступ - по пространству, проекту и
ревизии, чужое - 404. Принятые виды - данные для следующего шага (окна фасада в проёмы плана);
отклонённые и непринятые кандидаты в расчёт не входят.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import ValidationError

from app.api.v1.cad import _read_artifact_json
from app.api.v1.deps import (
    AuthDep,
    SessionDep,
    SettingsDep,
    StorageDep,
    require,
    require_feature,
)
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.cad_facades import (
    FacadeIssueRead,
    FacadesDecide,
    FacadesDecided,
    FacadesFile,
    FacadesJobCreate,
    FacadesJobRead,
    FacadesRead,
)
from app.errors import DomainError, ErrorCode, not_found
from app.models import DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_facades
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/cad/facades",
    tags=["cad-facades"],
    dependencies=[require_feature("cad.export")],
)


async def _scope(
    session: SessionDep, context: AuthDep, project_id: uuid.UUID, revision_id: uuid.UUID
) -> tuple[Project, DocumentRevision]:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    revision = await cad_service.revision_in_project(
        session, project=project, revision_id=revision_id
    )
    if revision is None:
        raise not_found("Ревизия")
    return project, revision


def _job_read(job: Job) -> FacadesJobRead:
    raw = job.payload.get("page_indexes")
    return FacadesJobRead(
        job_id=job.id,
        revision_id=uuid.UUID(str(job.payload["revision_id"])),
        status=job.status.value,
        attempt=job.attempt,
        error_code=job.error_code,
        error_message=job.error_message,
        page_indexes=[int(item) for item in raw] if isinstance(raw, list) else None,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/jobs",
    response_model=FacadesJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Поставить распознавание видов фасадов АР по исходному PDF ревизии",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_facades_job(
    project_id: uuid.UUID,
    body: FacadesJobCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> FacadesJobRead:
    project, revision = await _scope(session, context, project_id, body.revision_id)
    job = await cad_facades.schedule(
        session,
        project=project,
        revision=revision,
        page_indexes=body.page_indexes,
        settings=settings,
    )
    result = _job_read(job)
    await session.commit()
    return result


@router.get(
    "",
    response_model=FacadesRead,
    summary="Фасады ревизии: последнее задание, кандидаты видов, замечания генератора",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_facades(
    project_id: uuid.UUID,
    revision_id: Annotated[uuid.UUID, Query()],
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> FacadesRead:
    await _scope(session, context, project_id, revision_id)
    latest, done = await cad_facades.latest_jobs(
        session, workspace_id=context.tenant, project_id=project_id, revision_id=revision_id
    )
    views = await cad_facades.list_views(session, project_id=project_id, revision_id=revision_id)
    issues: list[FacadeIssueRead] = []
    if done is not None:
        attempt = cad_service.result_of(done).get("attempt")
        raw = (
            await _read_artifact_json(storage, done, revision_id, attempt, cad_facades.FACADES_JSON)
            if type(attempt) is int
            else None
        )
        if raw is not None:
            try:
                document = FacadesFile.model_validate(raw)
            except ValidationError as error:
                raise DomainError(
                    ErrorCode.CAD_ENGINE_FAILED, "facades.json вне контракта"
                ) from error
            issues = [
                FacadeIssueRead(
                    code=item.code,
                    message=item.message,
                    page_index=item.page_index,
                    bbox=item.bbox,
                )
                for item in document.issues
            ]
    return FacadesRead(
        revision_id=revision_id,
        job=None if latest is None else _job_read(latest),
        result_job_id=None if done is None else done.id,
        views=[cad_facades.view_read(row) for row in views],
        issues=issues,
    )


@router.post(
    "/views/decide",
    response_model=FacadesDecided,
    summary="Принять, отклонить или вернуть в кандидаты виды фасадов (решение человека)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def decide_cad_facade_views(
    project_id: uuid.UUID,
    body: FacadesDecide,
    session: SessionDep,
    context: AuthDep,
) -> FacadesDecided:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    rows = await cad_facades.decide(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        view_ids=body.view_ids,
        decision=body.decision,
        user_id=context.principal.user_id,
    )
    result = FacadesDecided(views=[cad_facades.view_read(row) for row in rows])
    await session.commit()
    return result


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
