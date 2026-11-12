"""Разрезы АР во вкладке CAD: задание, кандидаты уровней и решения человека.

Маршруты закрыты флагом пространства `cad.export` на сервере; доступ - по пространству, проекту и
ревизии, чужое - 404. Принятая высота «чистый пол - низ плиты» уходит в запуск трасс механики
(`cad_mep`); отклонённые и непринятые кандидаты в расчёт не входят.
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
from app.contracts.cad_sections import (
    SectionIssueRead,
    SectionPageRead,
    SectionsDecide,
    SectionsDecided,
    SectionsFile,
    SectionsJobCreate,
    SectionsJobRead,
    SectionsRead,
)
from app.errors import DomainError, ErrorCode, not_found
from app.models import DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_sections
from app.services import projects as projects_service

router = APIRouter(
    prefix="/projects/{project_id}/cad/sections",
    tags=["cad-sections"],
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


def _job_read(job: Job) -> SectionsJobRead:
    raw = job.payload.get("page_indexes")
    return SectionsJobRead(
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
    response_model=SectionsJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Поставить распознавание разрезов АР по исходному PDF ревизии",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def create_cad_sections_job(
    project_id: uuid.UUID,
    body: SectionsJobCreate,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> SectionsJobRead:
    project, revision = await _scope(session, context, project_id, body.revision_id)
    job = await cad_sections.schedule(
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
    response_model=SectionsRead,
    summary="Разрезы ревизии: последнее задание, кандидаты уровней, замечания генератора",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_cad_sections(
    project_id: uuid.UUID,
    revision_id: Annotated[uuid.UUID, Query()],
    session: SessionDep,
    context: AuthDep,
    storage: StorageDep,
) -> SectionsRead:
    await _scope(session, context, project_id, revision_id)
    latest, done = await cad_sections.latest_jobs(
        session, workspace_id=context.tenant, project_id=project_id, revision_id=revision_id
    )
    levels = await cad_sections.list_levels(session, project_id=project_id, revision_id=revision_id)
    issues: list[SectionIssueRead] = []
    pages: list[SectionPageRead] = []
    if done is not None:
        attempt = cad_service.result_of(done).get("attempt")
        raw = (
            await _read_artifact_json(
                storage, done, revision_id, attempt, cad_sections.SECTIONS_JSON
            )
            if type(attempt) is int
            else None
        )
        if raw is not None:
            try:
                document = SectionsFile.model_validate(raw)
            except ValidationError as error:
                raise DomainError(
                    ErrorCode.CAD_ENGINE_FAILED, "sections.json вне контракта"
                ) from error
            issues = [
                SectionIssueRead(
                    code=item.code,
                    message=item.message,
                    page_index=item.page_index,
                    bbox=item.bbox,
                )
                for item in document.issues
            ]
            pages = [
                SectionPageRead(
                    page_index=page.page_index,
                    title=page.title,
                    corps=page.corps,
                    section=page.section,
                    cuts=page.cuts,
                    page_size_pt=page.page_size_pt,
                    rotation=page.rotation,
                )
                for page in document.sections
            ]
    return SectionsRead(
        revision_id=revision_id,
        job=None if latest is None else _job_read(latest),
        result_job_id=None if done is None else done.id,
        levels=[cad_sections.level_read(row) for row in levels],
        issues=issues,
        pages=pages,
    )


@router.post(
    "/levels/decide",
    response_model=SectionsDecided,
    summary="Принять, отклонить или вернуть в кандидаты уровни разрезов (решение человека)",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def decide_cad_section_levels(
    project_id: uuid.UUID,
    body: SectionsDecide,
    session: SessionDep,
    context: AuthDep,
) -> SectionsDecided:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    rows = await cad_sections.decide(
        session,
        workspace_id=context.tenant,
        project_id=project_id,
        level_ids=body.level_ids,
        decision=body.decision,
        user_id=context.principal.user_id,
    )
    result = SectionsDecided(levels=[cad_sections.level_read(row) for row in rows])
    await session.commit()
    return result


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
