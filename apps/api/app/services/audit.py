"""Запись административных действий.

Событие пишется в той же транзакции, что и само изменение: откатилось изменение —
не осталось и записи о нём. Журнал, рассказывающий о том, чего не произошло, хуже
пустого.

Исключение — отказы. Отказ в праве и упавшее действие записываются отдельной сессией,
потому что транзакция, о которой они рассказывают, к этому моменту уже откачена.

Секреты вычищаются на записи, а не на чтении. Вычищенное на чтении уже лежит в базе
и уже уехало в резервную копию.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.core.logging import get_logger
from app.core.request_context import get_client_ip, get_request_id, get_user_agent
from app.db.session import get_session_factory
from app.domain import AuditAction, AuditResult
from app.models import AuditEvent

log = get_logger(__name__)

# Части имён полей, значение которых наружу не выносится ни при каких условиях.
_SENSITIVE_PARTS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "credential",
    "authorization",
    "cookie",
    "private",
)

_MASK = "***"
_MAX_TEXT = 500


def _is_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE_PARTS)


def redact(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Оставляет только безопасное и пригодное для хранения.

    Значения подозрительных полей заменяются маской, вложенные структуры обходятся
    рекурсивно, длинные строки обрезаются: журнал — это сводка, а не копия документа.
    """
    if payload is None:
        return None

    result: dict[str, Any] = {}
    for key, value in payload.items():
        if _is_sensitive(key):
            result[key] = _MASK
        elif isinstance(value, dict):
            result[key] = redact(value)
        elif isinstance(value, list):
            result[key] = [_scalar(item) for item in value[:50]]
        else:
            result[key] = _scalar(value)
    return result


def _scalar(value: object) -> Any:
    """Приводит значение к тому, что переживёт JSONB и не утащит лишнего."""
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return redact(value)
    # Всё остальное — в строку: неизвестный объект не должен ронять запись события.
    return str(value)[:_MAX_TEXT]


def _event(
    context: AuthContext | None,
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None,
    result: AuditResult,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    error_code: str | None,
) -> AuditEvent:
    principal = context.principal if context else None
    return AuditEvent(
        actor_user_id=principal.user_id if principal else None,
        actor_label=principal.label if principal else None,
        actor_role=context.role.value if context else None,
        credential=context.credential.value if context else None,
        workspace_id=context.workspace_id if context else None,
        action=action.value,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        error_code=error_code,
        before_summary=redact(before),
        after_summary=redact(after),
        request_id=get_request_id(),
        ip=get_client_ip(),
        user_agent=get_user_agent(),
    )


async def record(
    session: AsyncSession,
    context: AuthContext | None,
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    result: AuditResult = AuditResult.SUCCESS,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> AuditEvent:
    """Пишет событие в текущую транзакцию."""
    event = _event(
        context,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        before=before,
        after=after,
        error_code=error_code,
    )
    session.add(event)
    await session.flush()
    return event


async def record_out_of_band(
    context: AuthContext | None,
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    result: AuditResult = AuditResult.DENIED,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> None:
    """Пишет событие собственной сессией.

    Для отказов: транзакция запроса к этому моменту уже откачена, и запись в неё
    пропала бы вместе с ней. Ошибка записи журнала не должна ронять ответ клиенту —
    поэтому здесь она только логируется.
    """
    factory = get_session_factory()
    try:
        async with factory() as session:
            await record(
                session,
                context,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                before=before,
                after=after,
                error_code=error_code,
            )
            await session.commit()
    except Exception as error:  # pragma: no cover — отказ базы проверяется отдельно
        log.error("audit_write_failed", action=action.value, error_type=type(error).__name__)


def scoped(workspace_id: uuid.UUID | None) -> Select[tuple[AuditEvent]]:
    """Выборка журнала. Без пространства — вся установка, для администратора платформы."""
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    if workspace_id is not None:
        return query.where(AuditEvent.workspace_id == workspace_id)
    return query
