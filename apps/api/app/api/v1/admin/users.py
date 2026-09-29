"""Пользователи и доступ: заявки, одобрение, роли, отключение, временный пароль (ADR-0031).

Каждое изменение пишется в журнал в той же транзакции. Пароль в журнал не попадает ни в
каком виде: событие фиксирует факт выдачи, а не значение.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.v1.deps import (
    DEFAULT_PAGE_SIZE,
    AuthDep,
    LimitDep,
    OffsetDep,
    SessionDep,
    require,
)
from app.auth.permissions import Permission
from app.domain import ApprovalStatus, AuditAction, Role
from app.errors import not_found
from app.models import UserIdentity
from app.schemas import (
    AdminSetPasswordRequest,
    AdminUserRead,
    AdminWorkspaceRead,
    Page,
    SessionWorkspace,
    UserApproveRequest,
    UserMembershipRequest,
)
from app.services import audit as audit_service
from app.services import local_auth
from app.services import users as users_service

router = APIRouter()


def _to_read(view: users_service.UserView) -> AdminUserRead:
    user = view.user
    return AdminUserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_local=user.issuer == local_auth.LOCAL_ISSUER,
        approval_status=user.approval_status,
        is_active=user.is_active,
        is_platform_admin=user.platform_role is Role.PLATFORM_ADMIN,
        must_change_password=view.credential.must_change_password if view.credential else False,
        locked_until=view.credential.locked_until if view.credential else None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        memberships=[
            SessionWorkspace(
                id=item.workspace_id,
                slug=item.workspace_slug,
                name=item.workspace_name,
                role=item.role,
            )
            for item in view.memberships
        ],
    )


def _summary(user: UserIdentity) -> dict[str, object]:
    return {
        "approval_status": user.approval_status.value,
        "is_active": user.is_active,
    }


async def _user_or_404(session: SessionDep, user_id: uuid.UUID) -> UserIdentity:
    user = await session.get(UserIdentity, user_id)
    if user is None:
        raise not_found("Пользователь")
    return user


async def _read(session: SessionDep, user: UserIdentity) -> AdminUserRead:
    await session.refresh(user)
    return _to_read(await users_service.get_view(session, user))


@router.get(
    "/users",
    response_model=Page[AdminUserRead],
    summary="Пользователи",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def list_admin_users(
    session: SessionDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
    status: Annotated[
        ApprovalStatus | None, Query(description="Состояние заявки: pending, approved, rejected")
    ] = None,
) -> Page[AdminUserRead]:
    """Пользователи установки, новые сверху. Фильтр `pending` — очередь заявок."""
    views, total = await users_service.list_users(
        session, status=status, limit=limit, offset=offset
    )
    return Page(items=[_to_read(view) for view in views], total=total, limit=limit, offset=offset)


@router.get(
    "/workspaces",
    response_model=list[AdminWorkspaceRead],
    summary="Рабочие пространства",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def list_admin_workspaces(session: SessionDep) -> list[AdminWorkspaceRead]:
    """Пространства установки — для выбора при выдаче доступа."""
    return [
        AdminWorkspaceRead.model_validate(item)
        for item in await users_service.list_workspaces(session)
    ]


@router.post(
    "/users/{user_id}/approve",
    response_model=AdminUserRead,
    summary="Одобрить заявку",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def approve_admin_user(
    user_id: uuid.UUID, payload: UserApproveRequest, session: SessionDep, context: AuthDep
) -> AdminUserRead:
    """Одобряет заявку и сразу выдаёт роль в пространстве."""
    user = await _user_or_404(session, user_id)
    before = _summary(user)
    await users_service.approve(
        session, user=user, workspace_id=payload.workspace_id, role=payload.role
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.USER_APPROVED,
        resource_type="user",
        resource_id=str(user.id),
        before=before,
        after={
            **_summary(user),
            "workspace_id": str(payload.workspace_id),
            "role": payload.role.value,
        },
    )
    await session.commit()
    return await _read(session, user)


@router.post(
    "/users/{user_id}/reject",
    response_model=AdminUserRead,
    summary="Отклонить заявку",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def reject_admin_user(
    user_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> AdminUserRead:
    user = await _user_or_404(session, user_id)
    before = _summary(user)
    await users_service.reject(session, user=user)
    await audit_service.record(
        session,
        context,
        action=AuditAction.USER_REJECTED,
        resource_type="user",
        resource_id=str(user.id),
        before=before,
        after=_summary(user),
    )
    await session.commit()
    return await _read(session, user)


@router.post(
    "/users/{user_id}/disable",
    response_model=AdminUserRead,
    summary="Отключить пользователя",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def disable_admin_user(
    user_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> AdminUserRead:
    """Отключает вход и гасит все сеансы пользователя. История действий остаётся."""
    user = await _user_or_404(session, user_id)
    before = _summary(user)
    await users_service.set_active(
        session, user=user, active=False, actor_id=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.USER_DISABLED,
        resource_type="user",
        resource_id=str(user.id),
        before=before,
        after=_summary(user),
    )
    await session.commit()
    return await _read(session, user)


@router.post(
    "/users/{user_id}/enable",
    response_model=AdminUserRead,
    summary="Включить пользователя",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def enable_admin_user(
    user_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> AdminUserRead:
    user = await _user_or_404(session, user_id)
    before = _summary(user)
    await users_service.set_active(
        session, user=user, active=True, actor_id=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.USER_ENABLED,
        resource_type="user",
        resource_id=str(user.id),
        before=before,
        after=_summary(user),
    )
    await session.commit()
    return await _read(session, user)


@router.put(
    "/users/{user_id}/membership",
    response_model=AdminUserRead,
    summary="Роль в пространстве",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def set_admin_user_membership(
    user_id: uuid.UUID, payload: UserMembershipRequest, session: SessionDep, context: AuthDep
) -> AdminUserRead:
    """Назначает одобренному пользователю роль в пространстве или меняет её."""
    user = await _user_or_404(session, user_id)
    await users_service.set_membership(
        session, user=user, workspace_id=payload.workspace_id, role=payload.role
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.USER_MEMBERSHIP_SET,
        resource_type="user",
        resource_id=str(user.id),
        after={"workspace_id": str(payload.workspace_id), "role": payload.role.value},
    )
    await session.commit()
    return await _read(session, user)


@router.post(
    "/users/{user_id}/password",
    response_model=AdminUserRead,
    summary="Выдать временный пароль",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def set_admin_user_password(
    user_id: uuid.UUID, payload: AdminSetPasswordRequest, session: SessionDep, context: AuthDep
) -> AdminUserRead:
    """Задаёт временный пароль. Пользователь сменит его при входе, его сеансы гаснут."""
    user = await _user_or_404(session, user_id)
    await local_auth.set_password_by_admin(
        session, user=user, password=payload.password.get_secret_value()
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.USER_CREDENTIAL_RESET,
        resource_type="user",
        resource_id=str(user.id),
        after={"must_change_password": True},
    )
    await session.commit()
    return await _read(session, user)
