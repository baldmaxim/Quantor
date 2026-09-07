"""Управление связью проекта с тендером.

Связь `source=tenderhub` + `external_id` — каноническая: по ней проект узнаётся во
внешней системе. Поэтому её изменение вынесено из обычного редактирования проекта в
отдельную привилегированную операцию с предпросмотром, подтверждением и записью в журнал.

Причина не в осторожности ради осторожности. Перепривязка меняет ответ на вопрос «какой
тендер описывает эта документация», и сделанная случайно — в форме, где рядом лежит поле
названия, — она обнаруживается через месяцы и уже необъяснима.

Данные проекта при этом не трогаются: ни документы, ни ревизии, ни распознанные области.
Отвязка — это разрыв ссылки, а не удаление работы.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.core.logging import get_logger
from app.domain import AuditAction, AuditResult, ProjectSource
from app.errors import DomainError, ErrorCode
from app.integrations.tenderhub import TenderBrief, TenderHubClient
from app.models import Project
from app.services import audit as audit_service
from app.services import projects as projects_service

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BindingPreview:
    """Что именно произойдёт при перепривязке. Показывается до подтверждения."""

    project_id: uuid.UUID
    current_external_id: str | None
    current_external_ref: str | None
    target_external_id: str
    target_external_ref: str | None
    target_title: str
    target_client_name: str | None
    # Проект, который уже занят этим тендером. Не пусто — перепривязка невозможна.
    conflicting_project_id: uuid.UUID | None
    conflicting_project_name: str | None

    @property
    def is_noop(self) -> bool:
        return self.current_external_id == self.target_external_id


def _require_bound_project(project: Project) -> None:
    if project.source is not ProjectSource.TENDERHUB:
        raise DomainError(
            ErrorCode.TENDERHUB_BINDING_IMMUTABLE,
            "Проект заведён вручную: связывать его с тендером этой операцией нельзя",
        )


async def preview(
    session: AsyncSession,
    client: TenderHubClient,
    *,
    workspace_id: uuid.UUID,
    project: Project,
    tender_id: str,
) -> BindingPreview:
    """Готовит перепривязку: читает тендер и ищет конфликт. Ничего не меняет."""
    _require_bound_project(project)

    tender: TenderBrief = await client.get_tender(tender_id)

    occupied = await projects_service.find_by_external_id(
        session,
        workspace_id=workspace_id,
        source=ProjectSource.TENDERHUB,
        external_id=tender_id,
    )
    conflicting = occupied if occupied is not None and occupied.id != project.id else None

    return BindingPreview(
        project_id=project.id,
        current_external_id=project.external_id,
        current_external_ref=project.external_ref,
        target_external_id=tender_id,
        target_external_ref=tender.tender_number,
        target_title=tender.title,
        target_client_name=tender.client_name,
        conflicting_project_id=conflicting.id if conflicting else None,
        conflicting_project_name=conflicting.name if conflicting else None,
    )


async def rebind(
    session: AsyncSession,
    context: AuthContext,
    client: TenderHubClient,
    *,
    project: Project,
    tender_id: str,
) -> Project:
    """Переносит связь на другой тендер. Документы и задания остаются на месте."""
    context.require(Permission.INTEGRATION_MANAGE)

    plan = await preview(
        session, client, workspace_id=context.workspace_id, project=project, tender_id=tender_id
    )
    if plan.conflicting_project_id is not None:
        # Отказ записывается наравне с успехом: попытка перепривязать занятый тендер —
        # ровно то событие, которое потом объясняет, почему связь выглядит странно.
        await audit_service.record_out_of_band(
            context,
            action=AuditAction.TENDERHUB_PROJECT_REBOUND,
            resource_type="project",
            resource_id=str(project.id),
            result=AuditResult.FAILURE,
            before={"external_id": plan.current_external_id},
            after={"external_id": tender_id},
            error_code=ErrorCode.TENDERHUB_BINDING_CONFLICT.value,
        )
        raise DomainError(
            ErrorCode.TENDERHUB_BINDING_CONFLICT,
            f"Тендер уже привязан к проекту «{plan.conflicting_project_name}»",
        )

    before = {
        "external_id": project.external_id,
        "external_ref": project.external_ref,
        "name": project.name,
    }

    project.external_id = plan.target_external_id
    project.external_ref = plan.target_external_ref
    # Каноническое название приходит из внешней системы вместе со связью. Местное имя
    # не трогается: его выбирал человек, и перепривязка не повод его терять.
    project.name = plan.target_title.strip()[:200] or project.name
    project.external_bound_at = datetime.now(UTC)
    await session.flush()

    await audit_service.record(
        session,
        context,
        action=AuditAction.TENDERHUB_PROJECT_REBOUND,
        resource_type="project",
        resource_id=str(project.id),
        before=before,
        after={
            "external_id": project.external_id,
            "external_ref": project.external_ref,
            "name": project.name,
        },
    )
    await session.commit()
    await session.refresh(project)
    log.info("tenderhub_rebound", project_id=str(project.id), external_id=tender_id)
    return project


async def unlink(session: AsyncSession, context: AuthContext, *, project: Project) -> Project:
    """Разрывает связь с тендером. Проект и вся его работа остаются."""
    context.require(Permission.INTEGRATION_MANAGE)
    _require_bound_project(project)

    before = {
        "external_id": project.external_id,
        "external_ref": project.external_ref,
        "source": project.source.value,
    }

    project.source = ProjectSource.MANUAL
    project.external_id = None
    project.external_ref = None
    project.external_bound_at = None
    # Местное имя становится основным: иначе после отвязки проект остался бы под
    # названием тендера, к которому он больше не относится.
    if project.local_alias:
        project.name = project.local_alias
        project.local_alias = None
    await session.flush()

    await audit_service.record(
        session,
        context,
        action=AuditAction.TENDERHUB_PROJECT_UNLINKED,
        resource_type="project",
        resource_id=str(project.id),
        before=before,
        after={"source": ProjectSource.MANUAL.value, "name": project.name},
    )
    await session.commit()
    await session.refresh(project)
    log.info("tenderhub_unlinked", project_id=str(project.id))
    return project
