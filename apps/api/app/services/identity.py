"""Личности, пространства и членство: выборки и провизионирование.

Сервис, а не обработчик: те же операции нужны и входу через провайдера, и будущим
административным маршрутам, и тестам. Проверок прав здесь нет — они делаются выше,
на границе HTTP, где известен контекст запроса.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain import Role, UserKind, WorkspaceStatus
from app.models import UserIdentity, Workspace, WorkspaceMembership


@dataclass(frozen=True, slots=True)
class MembershipView:
    """Членство в пригодном для ответа виде: без ленивых связей и лишних полей."""

    workspace_id: uuid.UUID
    workspace_slug: str
    workspace_name: str
    role: Role


async def get_user_by_subject(
    session: AsyncSession, *, issuer: str, subject: str
) -> UserIdentity | None:
    query = select(UserIdentity).where(
        UserIdentity.issuer == issuer, UserIdentity.subject == subject
    )
    return (await session.execute(query)).scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> UserIdentity | None:
    return await session.get(UserIdentity, user_id)


async def upsert_identity(
    session: AsyncSession,
    *,
    issuer: str,
    subject: str,
    email: str | None,
    email_verified: bool,
    display_name: str | None,
    platform_admin_hints: frozenset[str] = frozenset(),
) -> UserIdentity:
    """Находит личность по (издатель, субъект) или заводит её при первом входе.

    Почта и имя обновляются с каждым входом: они принадлежат провайдеру, и хранить свою
    устаревшую копию незачем. Ключ склейки — субъект, а не почта: один и тот же адрес
    у разных провайдеров принадлежит разным людям.
    """
    user = await get_user_by_subject(session, issuer=issuer, subject=subject)
    if user is None:
        user = UserIdentity(
            issuer=issuer,
            subject=subject,
            email=email,
            email_verified=email_verified,
            display_name=display_name,
            kind=UserKind.HUMAN,
        )
        # Первые администраторы назначаются окружением: их идентификатор зависит от
        # провайдера, которого на момент миграции ещё не существовало.
        if _matches_hint(user, platform_admin_hints):
            user.platform_role = Role.PLATFORM_ADMIN
        session.add(user)
        await session.flush()
        return user

    user.email = email
    user.email_verified = email_verified
    user.display_name = display_name
    # Подсказка окружения повышает права и у уже заведённой личности: иначе восстановить
    # доступ после потери единственного администратора было бы нечем.
    if user.platform_role is None and _matches_hint(user, platform_admin_hints):
        user.platform_role = Role.PLATFORM_ADMIN
    await session.flush()
    return user


def _matches_hint(user: UserIdentity, hints: frozenset[str]) -> bool:
    if not hints:
        return False
    candidates = {user.subject.lower(), f"{user.issuer}:{user.subject}".lower()}
    if user.email:
        candidates.add(user.email.lower())
    return bool(candidates & hints)


async def list_memberships(session: AsyncSession, user_id: uuid.UUID) -> list[MembershipView]:
    """Пространства пользователя. Порядок устойчив: список не должен прыгать между запросами."""
    query = (
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.workspace))
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == user_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
        .order_by(WorkspaceMembership.created_at.asc(), WorkspaceMembership.id.asc())
    )
    rows = (await session.execute(query)).scalars().all()
    return [
        MembershipView(
            workspace_id=row.workspace_id,
            workspace_slug=row.workspace.slug,
            workspace_name=row.workspace.name,
            role=row.role,
        )
        for row in rows
    ]


async def get_membership_role(
    session: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> Role | None:
    """Роль пользователя в конкретном пространстве, если он там состоит."""
    query = (
        select(WorkspaceMembership.role)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
            Workspace.status == WorkspaceStatus.ACTIVE,
        )
    )
    return (await session.execute(query)).scalar_one_or_none()


async def workspace_exists(session: AsyncSession, workspace_id: uuid.UUID) -> bool:
    query = select(Workspace.id).where(
        Workspace.id == workspace_id, Workspace.status == WorkspaceStatus.ACTIVE
    )
    return (await session.execute(query)).scalar_one_or_none() is not None
