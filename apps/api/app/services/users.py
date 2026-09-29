"""Пользователи и доступ: заявки, одобрение, членство, отключение (ADR-0031).

Операции администратора платформы. Проверка права — на границе HTTP; здесь только
правила состояний: что с каким пользователем можно сделать и что при этом гаснет.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import sessions
from app.domain import WORKSPACE_ROLES, ApprovalStatus, Role, WorkspaceStatus
from app.errors import DomainError, ErrorCode
from app.models import LocalCredential, UserIdentity, Workspace, WorkspaceMembership
from app.services.identity import MembershipView


@dataclass(frozen=True, slots=True)
class UserView:
    """Пользователь вместе с тем, что нужно решению администратора."""

    user: UserIdentity
    credential: LocalCredential | None
    memberships: list[MembershipView]


async def list_users(
    session: AsyncSession,
    *,
    status: ApprovalStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[UserView], int]:
    """Страница пользователей: новые заявки сверху."""
    query = select(UserIdentity)
    count = select(func.count()).select_from(UserIdentity)
    if status is not None:
        query = query.where(UserIdentity.approval_status == status)
        count = count.where(UserIdentity.approval_status == status)

    total = (await session.execute(count)).scalar_one()
    rows = (
        (
            await session.execute(
                query.order_by(UserIdentity.created_at.desc(), UserIdentity.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return await _views(session, list(rows)), total


async def get_view(session: AsyncSession, user: UserIdentity) -> UserView:
    return (await _views(session, [user]))[0]


async def _views(session: AsyncSession, users: list[UserIdentity]) -> list[UserView]:
    """Досборка страницы двумя запросами, а не двумя на каждого пользователя."""
    ids = [user.id for user in users]
    if not ids:
        return []

    credentials = {
        row.user_id: row
        for row in (
            await session.execute(select(LocalCredential).where(LocalCredential.user_id.in_(ids)))
        )
        .scalars()
        .all()
    }

    memberships: dict[uuid.UUID, list[MembershipView]] = defaultdict(list)
    rows = await session.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id.in_(ids))
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )
    for membership, workspace in rows.tuples():
        memberships[membership.user_id].append(
            MembershipView(
                workspace_id=workspace.id,
                workspace_slug=workspace.slug,
                workspace_name=workspace.name,
                role=membership.role,
            )
        )

    return [
        UserView(user=user, credential=credentials.get(user.id), memberships=memberships[user.id])
        for user in users
    ]


async def list_workspaces(session: AsyncSession) -> list[Workspace]:
    query = select(Workspace).order_by(Workspace.name.asc(), Workspace.id.asc())
    return list((await session.execute(query)).scalars().all())


def _check_workspace_role(role: Role) -> None:
    if role not in WORKSPACE_ROLES:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Роль в пространстве: workspace_admin, engineer, reviewer или viewer",
        )


async def _active_workspace(session: AsyncSession, workspace_id: uuid.UUID) -> Workspace:
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None or workspace.status is not WorkspaceStatus.ACTIVE:
        raise DomainError(ErrorCode.WORKSPACE_NOT_FOUND)
    return workspace


async def upsert_membership(
    session: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID, role: Role
) -> WorkspaceMembership:
    """Членство с заданной ролью: заводится или меняет роль."""
    _check_workspace_role(role)
    membership = (
        await session.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = WorkspaceMembership(user_id=user_id, workspace_id=workspace_id, role=role)
        session.add(membership)
    else:
        membership.role = role
    await session.flush()
    return membership


async def approve(
    session: AsyncSession,
    *,
    user: UserIdentity,
    workspace_id: uuid.UUID,
    role: Role,
) -> None:
    """Одобрение заявки сразу с пространством и ролью.

    Одобрить «вообще» нельзя: пользователь без членства входит и видит пустой портал с
    отказом на каждом экране. Отклонённую заявку одобрить можно — передумать законно.
    """
    if user.approval_status is ApprovalStatus.APPROVED:
        raise DomainError(
            ErrorCode.USER_STATE_INVALID, "Пользователь уже одобрен — назначьте роль в пространстве"
        )
    _check_workspace_role(role)
    await _active_workspace(session, workspace_id)
    user.approval_status = ApprovalStatus.APPROVED
    await upsert_membership(session, user_id=user.id, workspace_id=workspace_id, role=role)


async def reject(session: AsyncSession, *, user: UserIdentity) -> None:
    """Отклонение заявки. Отклоняется только ожидающая: одобренного отключают, а не отклоняют."""
    if user.approval_status is not ApprovalStatus.PENDING:
        raise DomainError(ErrorCode.USER_STATE_INVALID, "Отклонить можно только новую заявку")
    user.approval_status = ApprovalStatus.REJECTED
    await session.flush()


async def set_active(
    session: AsyncSession, *, user: UserIdentity, active: bool, actor_id: uuid.UUID
) -> None:
    """Отключение и включение. Отключение гасит все сеансы сразу, а не по их истечении."""
    if not active and user.id == actor_id:
        raise DomainError(ErrorCode.USER_SELF_ACTION, "Нельзя отключить собственную учётную запись")
    user.is_active = active
    if not active:
        await sessions.revoke_all_for_user(session, user.id)
    await session.flush()


async def set_membership(
    session: AsyncSession, *, user: UserIdentity, workspace_id: uuid.UUID, role: Role
) -> None:
    """Роль одобренного пользователя в пространстве."""
    if user.approval_status is not ApprovalStatus.APPROVED:
        raise DomainError(ErrorCode.USER_STATE_INVALID, "Сначала одобрите заявку")
    await _active_workspace(session, workspace_id)
    await upsert_membership(session, user_id=user.id, workspace_id=workspace_id, role=role)
