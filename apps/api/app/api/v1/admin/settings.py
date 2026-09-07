"""Управляемые настройки портала."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, require
from app.auth.permissions import Permission
from app.core import settings_registry as registry
from app.core.settings_registry import ResolvedSetting
from app.domain import OverrideScope, ValueSource
from app.schemas import SettingOverrideWrite, SettingStateRead
from app.services import portal_settings

router = APIRouter(prefix="/settings")


def _to_read(resolved: ResolvedSetting) -> SettingStateRead:
    definition = resolved.definition
    return SettingStateRead(
        key=definition.key,
        title=definition.title,
        description=definition.description,
        category=definition.category,
        value_type=definition.value_type.value,
        value=resolved.value,
        default_value=definition.default_value,
        source=ValueSource(resolved.source),
        allowed_scopes=sorted(definition.allowed_scopes),
        # Значение из окружения портал не меняет: это аварийный рычаг, и «сохранить»
        # на нём было бы кнопкой, которая молча ничего не делает.
        editable=resolved.source != ValueSource.DEPLOYMENT.value,
        restart_required=definition.restart_required,
        is_secret=definition.is_secret,
        minimum=definition.minimum,
        maximum=definition.maximum,
        choices=list(definition.choices),
        updated_by=resolved.updated_by,
        updated_at=resolved.updated_at,
    )


@router.get(
    "",
    response_model=list[SettingStateRead],
    summary="Настройки с действующими значениями",
    dependencies=[require(Permission.SETTINGS_READ)],
)
async def list_settings(
    session: SessionDep, context: AuthDep, settings: SettingsDep
) -> list[SettingStateRead]:
    resolved = await portal_settings.effective(
        session, workspace_id=context.workspace_id, settings=settings
    )
    return [_to_read(resolved[key]) for key in registry.all_keys()]


@router.put(
    "/{key}",
    response_model=SettingStateRead,
    summary="Переопределить настройку",
    # Базовое право объявлено здесь и видно в контракте. Системный уровень требует
    # дополнительно system.admin — это зависит от тела запроса и проверяется в сервисе.
    dependencies=[require(Permission.SETTINGS_MANAGE)],
)
async def set_setting_override(
    key: str,
    payload: SettingOverrideWrite,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> SettingStateRead:
    resolved = await portal_settings.set_override(
        session,
        context,
        key=key,
        scope=payload.scope,
        value=payload.value,
        settings=settings,
    )
    return _to_read(resolved)


@router.delete(
    "/{key}",
    response_model=SettingStateRead,
    summary="Снять переопределение",
    dependencies=[require(Permission.SETTINGS_MANAGE)],
)
async def delete_setting_override(
    key: str,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
    scope: Annotated[OverrideScope, Query(description="С какого уровня снять")],
) -> SettingStateRead:
    resolved = await portal_settings.delete_override(
        session, context, key=key, scope=scope, settings=settings
    )
    return _to_read(resolved)
