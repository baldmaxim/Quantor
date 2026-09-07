"""Построение контекста запроса: кто спрашивает и что ему можно.

Единственное место, где рождается `AuthContext`. Ничто из тела запроса сюда не попадает:
пользователь, приславший `{"workspace_id": ...}` или `{"role": ...}`, получает ровно то же,
что и без них.

Порядок проверок задан жёстко и проверяется тестом: сначала личность, потом пространство,
потом подтверждение небезопасного запроса. В dev-режиме путь не касается базы вовсе —
на этом держится 503 при недоступной базе вместо вводящего в заблуждение 401.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, params
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import csrf, oidc, sessions
from app.auth.context import AuthContext, CredentialKind, Principal
from app.auth.dev import DEV_ROLE_HEADER, dev_context
from app.auth.permissions import Permission, permissions_for
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.domain import Role
from app.errors import DomainError, ErrorCode, http_error
from app.models import UserIdentity
from app.services import identity as identity_service

log = get_logger(__name__)

# Явное переключение пространства администратором платформы. Заголовок, а не поле тела:
# смена арендатора не должна быть побочным эффектом обычного запроса.
WORKSPACE_HEADER = "X-Workspace-Id"

_BEARER_PREFIX = "bearer "


def _unauthenticated(code: ErrorCode = ErrorCode.UNAUTHENTICATED) -> Exception:
    """401 с заголовком, без которого ответ формально неполон."""
    return http_error(code, headers={"WWW-Authenticate": "Bearer"})


async def get_auth_context(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthContext:
    """Контекст текущего запроса."""
    if settings.auth_mode == "dev":
        return dev_context(request.headers.get(DEV_ROLE_HEADER))

    principal, credential, session_id = await _authenticate(request, settings, session)

    # Подтверждение — после опознания и только для cookie: у запроса с заголовком
    # Authorization подделывать нечего, браузер его сам не добавляет.
    if credential is CredentialKind.SESSION:
        csrf.verify(
            request.method,
            request.cookies.get(settings.auth_csrf_cookie_name),
            request.headers.get(csrf.CSRF_HEADER),
        )

    workspace_id, role = await _resolve_workspace(request, session, principal)

    return AuthContext(
        principal=principal,
        workspace_id=workspace_id,
        role=role,
        permissions=permissions_for(role),
        credential=credential,
        is_dev_mode=False,
        session_id=session_id,
    )


async def _authenticate(
    request: Request, settings: Settings, session: AsyncSession
) -> tuple[Principal, CredentialKind, uuid.UUID | None]:
    """Опознаёт личность по cookie или заголовку."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith(_BEARER_PREFIX):
        claims = await oidc.verify_access_token(settings, header[len(_BEARER_PREFIX) :].strip())
        user = await identity_service.get_user_by_subject(
            session, issuer=str(claims.get("iss", "")), subject=str(claims.get("sub", ""))
        )
        if user is None or not user.is_active:
            # Токен настоящий, но такой личности портал не знает. Это не «неверный токен»,
            # а «доступ не выдан», и 401 здесь честнее 403: сеанса нет вовсе.
            raise _unauthenticated(ErrorCode.CREDENTIAL_INVALID)
        return _principal(user), CredentialKind.BEARER, None

    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise _unauthenticated()

    row = await sessions.resolve(session, token)
    if row is None:
        raise _unauthenticated(ErrorCode.SESSION_EXPIRED)

    user = await identity_service.get_user(session, row.user_id)
    if user is None or not user.is_active:
        raise _unauthenticated(ErrorCode.SESSION_EXPIRED)

    await sessions.touch(session, row)
    return _principal(user), CredentialKind.SESSION, row.id


def _principal(user: UserIdentity) -> Principal:
    return Principal(
        user_id=user.id,
        issuer=user.issuer,
        subject=user.subject,
        email=user.email,
        display_name=user.display_name,
        kind=user.kind,
        platform_role=user.platform_role,
    )


async def _resolve_workspace(
    request: Request, session: AsyncSession, principal: Principal
) -> tuple[uuid.UUID, Role]:
    """Выбирает пространство запроса и роль в нём.

    Заголовок — явное переключение. Без него берётся первое членство: порядок устойчив,
    иначе пользователь с двумя пространствами видел бы разные проекты через раз.
    """
    requested = _requested_workspace(request)
    memberships = await identity_service.list_memberships(session, principal.user_id)

    if requested is not None:
        for membership in memberships:
            if membership.workspace_id == requested:
                return requested, membership.role
        if principal.is_platform_admin:
            # Администратор платформы входит в чужое пространство только так — заголовком,
            # то есть намеренно. Молчаливого доступа «просто потому что админ» нет.
            if not await identity_service.workspace_exists(session, requested):
                raise DomainError(ErrorCode.WORKSPACE_NOT_FOUND)
            log.info(
                "workspace_override",
                user_id=str(principal.user_id),
                workspace_id=str(requested),
            )
            return requested, Role.PLATFORM_ADMIN
        raise DomainError(ErrorCode.WORKSPACE_FORBIDDEN)

    if memberships:
        first = memberships[0]
        return first.workspace_id, first.role

    raise DomainError(
        ErrorCode.WORKSPACE_FORBIDDEN,
        "Пользователь не состоит ни в одном рабочем пространстве",
    )


def _requested_workspace(request: Request) -> uuid.UUID | None:
    raw = request.headers.get(WORKSPACE_HEADER)
    if not raw:
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError as error:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, f"{WORKSPACE_HEADER}: ожидается UUID"
        ) from error


async def optional_context(
    request: Request, settings: Settings, session: AsyncSession
) -> AuthContext | None:
    """Контекст, если он есть, и None, если нет.

    Для публичных маршрутов, которым сеанс полезен, но не обязателен. Отказ здесь —
    это ответ «не вошёл», а не ошибка: `/api/v1/meta` обязан работать до входа, иначе
    страница входа не сможет узнать даже версию API.
    """
    try:
        return await get_auth_context(request, settings, session)
    except (DomainError, HTTPException):
        return None


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


async def require_authenticated(context: AuthDep) -> AuthContext:
    """Запрет по умолчанию.

    Висит на самом маршрутизаторе, а не расставляется по обработчикам: забыть добавить
    её к новому маршруту невозможно, потому что добавлять нечего.
    """
    return context


class PermissionCheck:
    """Проверка права как объект, а не замыкание.

    Объект нужен ради поля `permission`: тест покрытия перебирает операции приложения
    и читает требуемое право прямо из зависимости. Замыкание пришлось бы опознавать по
    имени, и первое же переименование сломало бы проверку молча — то есть ровно там,
    где она и должна была сработать.
    """

    __slots__ = ("permission",)

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    async def __call__(self, context: AuthDep) -> AuthContext:
        context.require(self.permission)
        return context


def require(permission: Permission) -> params.Depends:
    """Требование конкретного права на операции."""
    # params.Depends, а не Depends(): фабрика в заглушках типов возвращает Any,
    # и строгая проверка справедливо на это ругается.
    return params.Depends(dependency=PermissionCheck(permission))
