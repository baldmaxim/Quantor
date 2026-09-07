"""Управление флагами возможностей."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, require
from app.auth.permissions import Permission
from app.core.features import REGISTRY
from app.domain import OverrideScope
from app.schemas import FlagOverrideWrite, FlagStateRead
from app.services import feature_flags as flags_service

router = APIRouter(prefix="/feature-flags")


def _to_read(key: str, evaluation: flags_service.FlagEvaluation) -> FlagStateRead:
    definition = REGISTRY[key]
    return FlagStateRead(
        key=key,
        title=definition.title,
        description=definition.description,
        stage=definition.stage,
        effective=evaluation.value,
        default=definition.default,
        source=evaluation.source,
        reason=evaluation.reason,
        admin_editable=definition.admin_editable,
        workspace_scoped=definition.workspace_scoped,
        follows_configuration=definition.follows_configuration,
    )


@router.get(
    "",
    response_model=list[FlagStateRead],
    summary="Флаги возможностей",
    dependencies=[require(Permission.FEATURE_FLAGS_READ)],
)
async def list_feature_flags(
    session: SessionDep, context: AuthDep, settings: SettingsDep
) -> list[FlagStateRead]:
    evaluated = await flags_service.evaluate_all(
        session, settings, flags_service.EvaluationContext(workspace_id=context.workspace_id)
    )
    return [_to_read(key, evaluated[key]) for key in REGISTRY]


@router.put(
    "/{key}",
    response_model=FlagStateRead,
    summary="Переопределить флаг",
    dependencies=[require(Permission.FEATURE_FLAGS_MANAGE)],
)
async def set_feature_flag_override(
    key: str,
    payload: FlagOverrideWrite,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
) -> FlagStateRead:
    evaluation = await flags_service.set_override(
        session,
        context,
        key=key,
        scope=payload.scope,
        enabled=payload.enabled,
        reason=payload.reason,
        settings=settings,
    )
    return _to_read(key, evaluation)


@router.delete(
    "/{key}",
    response_model=FlagStateRead,
    summary="Снять переопределение флага",
    dependencies=[require(Permission.FEATURE_FLAGS_MANAGE)],
)
async def delete_feature_flag_override(
    key: str,
    session: SessionDep,
    context: AuthDep,
    settings: SettingsDep,
    scope: Annotated[OverrideScope, Query(description="С какого уровня снять")],
) -> FlagStateRead:
    evaluation = await flags_service.delete_override(
        session, context, key=key, scope=scope, settings=settings
    )
    return _to_read(key, evaluation)
