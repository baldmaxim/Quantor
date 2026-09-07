"""Диагностика и управление связями TenderHUB."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, TenderHubDep, require
from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.domain import AuditAction, AuditResult, ProjectSource
from app.errors import DomainError, ErrorCode, not_found
from app.models import Project
from app.schemas import (
    ProjectRead,
    TenderBindingPreviewRead,
    TenderHubProbeRead,
    TenderHubStatusRead,
    TenderRebindRequest,
)
from app.services import audit as audit_service
from app.services import projects as projects_service
from app.services import tenderhub_binding

router = APIRouter(prefix="/integrations/tenderhub")

# Проверка связи по кнопке должна отвечать быстро: администратор смотрит на неё и ждёт.
# Рабочий таймаут интеграции (20 с) для этого слишком велик.
PROBE_TIMEOUT_SECONDS = 5.0


@router.get(
    "",
    response_model=TenderHubStatusRead,
    summary="Состояние интеграции",
    dependencies=[require(Permission.INTEGRATION_READ)],
)
async def read_tenderhub_status(
    session: SessionDep, context: AuthDep, settings: SettingsDep
) -> TenderHubStatusRead:
    """Настроена ли интеграция и сколько проектов с ней связано.

    Ключ доступа не показывается ни целиком, ни частями: наружу уходит только факт
    его наличия (ADR-0011).
    """
    linked = await session.scalar(
        select(func.count())
        .select_from(Project)
        .where(
            Project.workspace_id == context.workspace_id,
            Project.source == ProjectSource.TENDERHUB,
        )
    )
    return TenderHubStatusRead(
        configured=settings.tenderhub_enabled,
        credential_state="configured" if settings.tenderhub_enabled else "missing",
        base_url=settings.tenderhub_api_url,
        linked_project_count=int(linked or 0),
    )


@router.post(
    "/test-connection",
    response_model=TenderHubProbeRead,
    summary="Проверить связь с TenderHUB",
    dependencies=[require(Permission.INTEGRATION_MANAGE)],
)
async def test_tenderhub_connection(context: AuthDep, client: TenderHubDep) -> TenderHubProbeRead:
    """Явное действие, а не проба при открытии страницы.

    Страница состояния не должна ходить во внешнюю систему сама: тогда её открытие
    зависит от чужой доступности, а администратор приходит туда как раз тогда, когда
    что-то сломалось.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    error_code: str | None = None
    count: int | None = None

    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            tenders = await client.list_tenders()
        count = len(tenders)
    except DomainError as error:
        error_code = error.code.value
    except TimeoutError:
        error_code = ErrorCode.TENDERHUB_UNAVAILABLE.value

    duration_ms = round((loop.time() - started) * 1000, 2)
    await audit_service.record_out_of_band(
        context,
        action=AuditAction.TENDERHUB_CONNECTION_TESTED,
        resource_type="integration",
        resource_id="tenderhub",
        result=AuditResult.SUCCESS if error_code is None else AuditResult.FAILURE,
        after={"duration_ms": duration_ms, "tender_count": count},
        error_code=error_code,
    )

    return TenderHubProbeRead(
        ok=error_code is None,
        checked_at=datetime.now(UTC),
        duration_ms=duration_ms,
        error_code=error_code,
        tender_count=count,
    )


async def _project_or_404(
    session: AsyncSession, context: AuthContext, project_id: uuid.UUID
) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.workspace_id, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


@router.post(
    "/projects/{project_id}/rebind/preview",
    response_model=TenderBindingPreviewRead,
    summary="Предпросмотр перепривязки",
    dependencies=[require(Permission.INTEGRATION_MANAGE)],
)
async def preview_tenderhub_rebind(
    project_id: uuid.UUID,
    payload: TenderRebindRequest,
    session: SessionDep,
    context: AuthDep,
    client: TenderHubDep,
) -> TenderBindingPreviewRead:
    """Что именно изменится и что этому мешает. Ничего не меняет."""
    project = await _project_or_404(session, context, project_id)
    plan = await tenderhub_binding.preview(
        session,
        client,
        workspace_id=context.workspace_id,
        project=project,
        tender_id=payload.tender_id,
    )
    return TenderBindingPreviewRead(
        project_id=plan.project_id,
        current_external_id=plan.current_external_id,
        current_external_ref=plan.current_external_ref,
        target_external_id=plan.target_external_id,
        target_external_ref=plan.target_external_ref,
        target_title=plan.target_title,
        target_client_name=plan.target_client_name,
        conflicting_project_id=plan.conflicting_project_id,
        conflicting_project_name=plan.conflicting_project_name,
        is_noop=plan.is_noop,
    )


@router.post(
    "/projects/{project_id}/rebind",
    response_model=ProjectRead,
    summary="Перепривязать проект к другому тендеру",
    dependencies=[require(Permission.INTEGRATION_MANAGE)],
)
async def rebind_tenderhub_project(
    project_id: uuid.UUID,
    payload: TenderRebindRequest,
    session: SessionDep,
    context: AuthDep,
    client: TenderHubDep,
) -> ProjectRead:
    """Перенос связи. Документы, ревизии и задания остаются на месте."""
    if not payload.confirm:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Перепривязка выполняется только с явным подтверждением",
        )
    project = await _project_or_404(session, context, project_id)
    updated = await tenderhub_binding.rebind(
        session, context, client, project=project, tender_id=payload.tender_id
    )
    return ProjectRead.model_validate(updated)


@router.post(
    "/projects/{project_id}/unlink",
    response_model=ProjectRead,
    summary="Отвязать проект от тендера",
    dependencies=[require(Permission.INTEGRATION_MANAGE)],
)
async def unlink_tenderhub_project(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> ProjectRead:
    """Разрыв связи. Проект и вся его работа остаются в портале."""
    project = await _project_or_404(session, context, project_id)
    updated = await tenderhub_binding.unlink(session, context, project=project)
    return ProjectRead.model_validate(updated)
