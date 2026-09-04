"""Проекты и их документы."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.v1.deps import DEFAULT_PAGE_SIZE, LimitDep, OffsetDep, SessionDep, WorkspaceDep
from app.errors import not_found
from app.schemas import (
    DocumentRead,
    JobRead,
    Page,
    ProjectCreate,
    ProjectJobSummary,
    ProjectRead,
    ProjectSummary,
    ProjectUpdate,
)
from app.services import documents as documents_service
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.services.projects import ProjectSort

router = APIRouter(prefix="/projects", tags=["projects"])


def _summary(row: projects_service.ProjectWithCounts) -> ProjectSummary:
    return ProjectSummary(
        **ProjectRead.model_validate(row.project).model_dump(),
        document_count=row.document_count,
        sheet_count=row.sheet_count,
        last_job=ProjectJobSummary.model_validate(row.last_job) if row.last_job else None,
    )


@router.get("", response_model=Page[ProjectSummary], summary="Список проектов")
async def list_projects(
    session: SessionDep,
    workspace: WorkspaceDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
    search: str | None = None,
    sort: ProjectSort = ProjectSort.RECENT,
) -> Page[ProjectSummary]:
    rows = await projects_service.list_projects(
        session,
        workspace_id=workspace.workspace_id,
        limit=limit,
        offset=offset,
        search=search,
        sort=sort,
    )
    total = await projects_service.count_projects(
        session, workspace_id=workspace.workspace_id, search=search
    )
    return Page(items=[_summary(row) for row in rows], total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать проект",
)
async def create_project(
    payload: ProjectCreate, session: SessionDep, workspace: WorkspaceDep
) -> ProjectRead:
    project = await projects_service.create_project(
        session, workspace_id=workspace.workspace_id, name=payload.name
    )
    await session.commit()
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectSummary, summary="Проект")
async def read_project(
    project_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> ProjectSummary:
    row = await projects_service.get_project_with_counts(
        session, workspace_id=workspace.workspace_id, project_id=project_id
    )
    if row is None:
        raise not_found("Проект")

    return _summary(row)


@router.patch("/{project_id}", response_model=ProjectRead, summary="Изменить проект")
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    session: SessionDep,
    workspace: WorkspaceDep,
) -> ProjectRead:
    project = await projects_service.get_project(
        session, workspace_id=workspace.workspace_id, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    updated = await projects_service.update_project(
        session, project=project, name=payload.name, status=payload.status
    )
    await session.commit()
    return ProjectRead.model_validate(updated)


@router.get(
    "/{project_id}/documents", response_model=Page[DocumentRead], summary="Документы проекта"
)
async def list_project_documents(
    project_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
) -> Page[DocumentRead]:
    project = await projects_service.get_project(
        session, workspace_id=workspace.workspace_id, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    rows = await documents_service.list_documents(
        session, project_id=project.id, limit=limit, offset=offset
    )
    total = await documents_service.count_documents(session, project_id=project.id)
    return Page(
        items=[DocumentRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}/jobs", response_model=Page[JobRead], summary="Задания проекта")
async def list_project_jobs(
    project_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
) -> Page[JobRead]:
    project = await projects_service.get_project(
        session, workspace_id=workspace.workspace_id, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    rows = await jobs_service.list_jobs(session, project_id=project.id, limit=limit, offset=offset)
    total = await jobs_service.count_jobs(session, project_id=project.id)
    return Page(
        items=[JobRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
