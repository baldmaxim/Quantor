"""Персональные API-токены пользователя (ADR-0051): список, выпуск, отзыв.

Только сеанс браузера: токеном токены не выпускаются и не отзываются, иначе украденный токен
размножался бы. Маршруты закрыты флагом пространства `tender.exchange`. Значение токена
показывается один раз, в ответе создания; в журнале аудита — имя и префикс, не токен.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.context import AuthContext, CredentialKind
from app.auth.permissions import Permission
from app.contracts.tender_exchange import (
    PersonalTokenCreate,
    PersonalTokenCreated,
    PersonalTokenRead,
)
from app.domain import AuditAction
from app.errors import DomainError, ErrorCode, not_found
from app.models import ApiToken
from app.services import api_tokens as tokens_service
from app.services import audit as audit_service

router = APIRouter(
    prefix="/me/api-tokens",
    tags=["api-tokens"],
    dependencies=[require_feature("tender.exchange")],
)


def _session_only(context: AuthContext) -> None:
    """Токены ведёт человек в сеансе: персональный токен для этого не годится."""
    if context.credential is CredentialKind.API_TOKEN:
        raise DomainError(
            ErrorCode.PERMISSION_DENIED,
            "Персональные токены выпускаются и отзываются только в сеансе портала",
        )


def _read(row: ApiToken) -> PersonalTokenRead:
    return PersonalTokenRead(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scopes=list(row.scopes),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        active=tokens_service.is_active(row),
    )


@router.get(
    "",
    response_model=list[PersonalTokenRead],
    summary="Мои персональные токены в этом пространстве",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def list_personal_tokens(session: SessionDep, context: AuthDep) -> list[PersonalTokenRead]:
    _session_only(context)
    rows = await tokens_service.list_for_user(
        session, user_id=context.principal.user_id, workspace_id=context.tenant
    )
    return [_read(row) for row in rows]


@router.post(
    "",
    response_model=PersonalTokenCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Выпустить персональный токен; значение виден один раз",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def create_personal_token(
    body: PersonalTokenCreate, session: SessionDep, context: AuthDep
) -> PersonalTokenCreated:
    _session_only(context)
    row, token = await tokens_service.create(
        session,
        user_id=context.principal.user_id,
        workspace_id=context.tenant,
        name=body.name,
        expires_in_days=body.expires_in_days,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.API_ACCESS_CREATED,
        resource_type="api_token",
        resource_id=str(row.id),
        after={
            "name": row.name,
            "prefix": row.prefix,
            "scopes": list(row.scopes),
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        },
    )
    await session.commit()
    return PersonalTokenCreated(**_read(row).model_dump(), token=token)


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отозвать персональный токен",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def revoke_personal_token(
    token_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> Response:
    _session_only(context)
    row = await tokens_service.get_own(
        session,
        token_id=token_id,
        user_id=context.principal.user_id,
        workspace_id=context.tenant,
    )
    if row is None:
        raise not_found("Токен")
    already = row.revoked_at is not None
    await tokens_service.revoke(session, row)
    if not already:
        await audit_service.record(
            session,
            context,
            action=AuditAction.API_ACCESS_REVOKED,
            resource_type="api_token",
            resource_id=str(row.id),
            after={"name": row.name, "prefix": row.prefix},
        )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
