"""Сервис проектов.

Каждый запрос ограничен рабочим пространством: доступ к чужому проекту не должен зависеть
от того, вспомнил ли разработчик добавить условие в конкретном обработчике.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import ProjectStatus
from app.models import Document, DocumentRevision, Project, Sheet


class ProjectSort(StrEnum):
    RECENT = "recent"
    NAME = "name"


@dataclass(frozen=True, slots=True)
class ProjectWithCounts:
    project: Project
    document_count: int
    sheet_count: int


def _scoped(workspace_id: uuid.UUID) -> Select[tuple[Project]]:
    return select(Project).where(Project.workspace_id == workspace_id)


async def create_project(session: AsyncSession, *, workspace_id: uuid.UUID, name: str) -> Project:
    project = Project(workspace_id=workspace_id, name=name.strip(), status=ProjectStatus.ACTIVE)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project


async def get_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project | None:
    result = await session.execute(_scoped(workspace_id).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def update_project(
    session: AsyncSession,
    *,
    project: Project,
    name: str | None = None,
    status: ProjectStatus | None = None,
) -> Project:
    if name is not None:
        project.name = name.strip()
    if status is not None:
        project.status = status
    await session.flush()
    await session.refresh(project)
    return project


def _document_count_subquery() -> Any:
    return (
        select(func.count(Document.id))
        .where(Document.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )


def _sheet_count_subquery() -> Any:
    return (
        select(func.count(Sheet.id))
        .select_from(Sheet)
        .join(DocumentRevision, Sheet.revision_id == DocumentRevision.id)
        .join(Document, DocumentRevision.document_id == Document.id)
        .where(Document.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )


async def get_project_with_counts(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectWithCounts | None:
    """Проект вместе со счётчиками — одним запросом, чтобы карточка не делала три обращения."""
    query = select(Project, _document_count_subquery(), _sheet_count_subquery()).where(
        Project.workspace_id == workspace_id, Project.id == project_id
    )
    row = (await session.execute(query)).first()
    if row is None:
        return None
    project, documents, sheets = row
    return ProjectWithCounts(project=project, document_count=documents, sheet_count=sheets)


async def count_projects(
    session: AsyncSession, *, workspace_id: uuid.UUID, search: str | None = None
) -> int:
    query = select(func.count()).select_from(Project).where(Project.workspace_id == workspace_id)
    if search:
        query = query.where(Project.name.ilike(f"%{search}%"))
    result = await session.execute(query)
    return int(result.scalar_one())


async def list_projects(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    limit: int,
    offset: int,
    search: str | None = None,
    sort: ProjectSort = ProjectSort.RECENT,
) -> list[ProjectWithCounts]:
    """Список проектов со счётчиками документов и листов.

    Счётчики берутся подзапросами, а не обходом связей: иначе на каждый проект уходит
    отдельный запрос, и список из тридцати проектов превращается в шестьдесят обращений к базе.
    """
    query = (
        select(Project, _document_count_subquery(), _sheet_count_subquery())
        .where(Project.workspace_id == workspace_id)
        .limit(limit)
        .offset(offset)
    )
    if search:
        query = query.where(Project.name.ilike(f"%{search}%"))
    query = query.order_by(
        Project.name.asc() if sort is ProjectSort.NAME else Project.updated_at.desc()
    )

    result = await session.execute(query)
    return [
        ProjectWithCounts(project=project, document_count=documents, sheet_count=sheets)
        for project, documents, sheets in result.all()
    ]
