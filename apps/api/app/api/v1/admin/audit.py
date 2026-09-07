"""Чтение журнала действий.

Операций изменения и удаления здесь нет и не будет: журнал, который можно переписать,
не журнал. Запрет держится на двух уровнях — отсутствие маршрутов и триггер базы.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.v1.deps import DEFAULT_PAGE_SIZE, AuthDep, LimitDep, OffsetDep, SessionDep, require
from app.auth.permissions import Permission
from app.domain import AuditResult
from app.models import AuditEvent
from app.schemas import AuditEventRead, Page

router = APIRouter(prefix="/audit")


@router.get(
    "",
    response_model=Page[AuditEventRead],
    summary="Журнал административных действий",
    dependencies=[require(Permission.AUDIT_READ)],
)
async def list_audit_events(
    session: SessionDep,
    context: AuthDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
    action: Annotated[str | None, Query(description="Фильтр по действию")] = None,
    resource_type: Annotated[str | None, Query(description="Фильтр по типу объекта")] = None,
    result: Annotated[AuditResult | None, Query(description="Фильтр по результату")] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query(description="Фильтр по актору")] = None,
    since: Annotated[datetime | None, Query(description="Не раньше")] = None,
    until: Annotated[datetime | None, Query(description="Не позже")] = None,
) -> Page[AuditEventRead]:
    """Страница журнала.

    Пагинация обязательна: журнал растёт всё время работы установки, и выборка «всё»
    здесь означает выборку, которая однажды не вернётся.

    Администратор платформы видит всю установку; остальные — только своё пространство.
    """
    scope = None if context.principal.is_platform_admin else context.workspace_id

    conditions = []
    if scope is not None:
        conditions.append(AuditEvent.workspace_id == scope)
    if action:
        conditions.append(AuditEvent.action == action)
    if resource_type:
        conditions.append(AuditEvent.resource_type == resource_type)
    if result is not None:
        conditions.append(AuditEvent.result == result)
    if actor_user_id is not None:
        conditions.append(AuditEvent.actor_user_id == actor_user_id)
    if since is not None:
        conditions.append(AuditEvent.created_at >= since)
    if until is not None:
        conditions.append(AuditEvent.created_at <= until)

    total = await session.scalar(select(func.count()).select_from(AuditEvent).where(*conditions))
    rows = (
        (
            await session.execute(
                select(AuditEvent)
                .where(*conditions)
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    return Page(
        items=[AuditEventRead.model_validate(row) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )
