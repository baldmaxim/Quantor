"""Разрешение и изменение управляемых настроек.

Порядок старшинства зафиксирован и проверяется тестом отдельно на каждой ступени:

    умолчание кода  <  системное переопределение  <  переопределение пространства
                    <  аварийное переопределение окружения

Аварийный уровень стоит последним намеренно: это рычаг на случай, когда неудачное
переопределение в базе положило портал, и добраться до админки уже нельзя. Из интерфейса
он только читается.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.core import settings_registry as registry
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.settings_registry import (
    ResolvedSetting,
    SettingDefinition,
    SettingValue,
    SettingValueError,
)
from app.domain import AuditAction, OverrideScope, ValueSource
from app.errors import DomainError, ErrorCode
from app.models import SettingOverride
from app.services import audit as audit_service

log = get_logger(__name__)


def parse_deployment_overrides(raw: str) -> dict[str, SettingValue]:
    """Разбирает `documents.content_url_ttl_seconds=900,projects.default_sort=name`.

    Неизвестный ключ и негодное значение игнорируются с записью в лог: опечатка в
    окружении не должна мешать порталу запуститься, но и молча пропасть не должна.
    """
    parsed: dict[str, SettingValue] = {}
    for chunk in raw.split(","):
        key, _, raw_value = chunk.partition("=")
        key = key.strip()
        definition = registry.get(key)
        if definition is None:
            if key:
                log.warning("settings_override_unknown_key", key=key)
            continue
        try:
            parsed[key] = registry.validate(definition, _coerce(definition, raw_value.strip()))
        except SettingValueError as error:
            log.warning("settings_override_invalid", key=key, reason=str(error))
    return parsed


def _coerce(definition: SettingDefinition, raw: str) -> object:
    """Приводит строку из окружения к типу настройки. Разбор строгий: `1` не станет `true`."""
    match definition.value_type:
        case registry.SettingType.BOOL:
            return raw.lower() in ("1", "true", "yes", "on")
        case registry.SettingType.INTEGER:
            return int(raw) if raw.lstrip("-").isdigit() else raw
        case registry.SettingType.STRING_LIST:
            return [item for item in raw.split("|") if item]
        case _:
            return raw


def _ceiling(definition: SettingDefinition, settings: Settings) -> int | None:
    """Верхний предел настройки, заданный возможностями установки."""
    if definition.deployment_ceiling_field is None:
        return None
    value = getattr(settings, definition.deployment_ceiling_field, None)
    return value if isinstance(value, int) else None


async def _overrides(
    session: AsyncSession, *, workspace_id: uuid.UUID | None
) -> dict[tuple[str, OverrideScope], SettingOverride]:
    """Все переопределения, влияющие на этот контекст, одним запросом.

    Одним, а не по ключу на настройку: страница настроек показывает весь реестр сразу,
    и запрос на каждую строку превратил бы её в десяток обращений к базе.
    """
    query = select(SettingOverride).where(
        (SettingOverride.workspace_id.is_(None)) | (SettingOverride.workspace_id == workspace_id)
    )
    rows = (await session.execute(query)).scalars().all()
    return {(row.key, row.scope): row for row in rows}


async def effective(
    session: AsyncSession, *, workspace_id: uuid.UUID | None, settings: Settings
) -> dict[str, ResolvedSetting]:
    """Действующие значения всех настроек реестра вместе с происхождением."""
    overrides = await _overrides(session, workspace_id=workspace_id)
    deployment = parse_deployment_overrides(settings.settings_overrides)

    resolved: dict[str, ResolvedSetting] = {}
    for key, definition in registry.DEFINITIONS.items():
        value: SettingValue = definition.default_value
        source = ValueSource.DEFAULT
        updated_by: str | None = None
        updated_at: str | None = None
        inherited: dict[str, SettingValue] = {ValueSource.DEFAULT.value: definition.default_value}

        system = overrides.get((key, OverrideScope.SYSTEM))
        if system is not None:
            value = system.value
            source = ValueSource.SYSTEM
            updated_by = str(system.updated_by_user_id) if system.updated_by_user_id else None
            updated_at = system.updated_at.isoformat()
            inherited[ValueSource.SYSTEM.value] = system.value

        workspace = overrides.get((key, OverrideScope.WORKSPACE))
        if workspace is not None and workspace.workspace_id == workspace_id:
            value = workspace.value
            source = ValueSource.WORKSPACE
            updated_by = str(workspace.updated_by_user_id) if workspace.updated_by_user_id else None
            updated_at = workspace.updated_at.isoformat()
            inherited[ValueSource.WORKSPACE.value] = workspace.value

        if key in deployment:
            value = deployment[key]
            source = ValueSource.DEPLOYMENT
            updated_by = None
            updated_at = None

        resolved[key] = ResolvedSetting(
            definition=definition,
            value=value,
            source=source.value,
            updated_by=updated_by,
            updated_at=updated_at,
            inherited=inherited,
        )
    return resolved


async def value_of(
    session: AsyncSession, key: str, *, workspace_id: uuid.UUID | None, settings: Settings
) -> SettingValue:
    """Одно действующее значение. Для мест, которым нужна ровно одна настройка."""
    resolved = await effective(session, workspace_id=workspace_id, settings=settings)
    return resolved[key].value


def _definition_or_404(key: str) -> SettingDefinition:
    definition = registry.get(key)
    if definition is None:
        raise DomainError(ErrorCode.SETTING_UNKNOWN, f"Настройки «{key}» нет в реестре")
    return definition


def _check_scope(context: AuthContext, definition: SettingDefinition, scope: OverrideScope) -> None:
    """Право на уровень, а не только на настройку.

    Системный уровень меняет поведение всей установки, поэтому доступен только
    администратору платформы: иначе арендатор менял бы её из своей админки.
    """
    context.require(definition.requires_permission)
    if not definition.allows(scope):
        raise DomainError(
            ErrorCode.SETTING_SCOPE_INVALID,
            f"Настройка не переопределяется на уровне «{scope.value}»",
        )
    if scope is OverrideScope.SYSTEM:
        context.require(Permission.SYSTEM_ADMIN)


async def set_override(
    session: AsyncSession,
    context: AuthContext,
    *,
    key: str,
    scope: OverrideScope,
    value: object,
    settings: Settings,
) -> ResolvedSetting:
    """Записывает переопределение и возвращает получившееся действующее значение."""
    definition = _definition_or_404(key)
    _check_scope(context, definition, scope)

    try:
        checked = registry.validate(definition, value, ceiling=_ceiling(definition, settings))
    except SettingValueError as error:
        raise DomainError(ErrorCode.SETTING_VALUE_INVALID, str(error)) from error

    workspace_id = context.workspace_id if scope is OverrideScope.WORKSPACE else None
    existing = await _find(session, key=key, scope=scope, workspace_id=workspace_id)
    before: dict[str, Any] | None = {"value": existing.value} if existing else None

    if existing is None:
        session.add(
            SettingOverride(
                key=key,
                scope=scope,
                workspace_id=workspace_id,
                value=checked,
                updated_by_user_id=context.principal.user_id,
            )
        )
    else:
        existing.value = checked
        existing.updated_by_user_id = context.principal.user_id
    await session.flush()

    await audit_service.record(
        session,
        context,
        action=AuditAction.SETTING_OVERRIDE_SET,
        resource_type="setting",
        resource_id=key,
        before=before,
        after={"value": checked, "scope": scope.value},
    )
    await session.commit()

    resolved = await effective(session, workspace_id=context.workspace_id, settings=settings)
    return resolved[key]


async def delete_override(
    session: AsyncSession,
    context: AuthContext,
    *,
    key: str,
    scope: OverrideScope,
    settings: Settings,
) -> ResolvedSetting:
    """Снимает переопределение. Настройка возвращается к унаследованному значению."""
    definition = _definition_or_404(key)
    _check_scope(context, definition, scope)

    workspace_id = context.workspace_id if scope is OverrideScope.WORKSPACE else None
    existing = await _find(session, key=key, scope=scope, workspace_id=workspace_id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()
        await audit_service.record(
            session,
            context,
            action=AuditAction.SETTING_OVERRIDE_DELETED,
            resource_type="setting",
            resource_id=key,
            before={"value": existing.value, "scope": scope.value},
        )
        await session.commit()

    resolved = await effective(session, workspace_id=context.workspace_id, settings=settings)
    return resolved[key]


async def _find(
    session: AsyncSession, *, key: str, scope: OverrideScope, workspace_id: uuid.UUID | None
) -> SettingOverride | None:
    query = select(SettingOverride).where(
        SettingOverride.key == key, SettingOverride.scope == scope
    )
    query = (
        query.where(SettingOverride.workspace_id.is_(None))
        if workspace_id is None
        else query.where(SettingOverride.workspace_id == workspace_id)
    )
    return (await session.execute(query)).scalar_one_or_none()
