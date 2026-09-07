"""Рабочие пространства, личности, членство и сессии.

Четыре таблицы одного назначения: ответить на вопрос «кто спрашивает и что ему можно».
Пароли здесь не хранятся ни в каком виде — личность удостоверяет внешний провайдер
(ADR-0012).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import PLATFORM_ROLES, WORKSPACE_ROLES, Role, UserKind, WorkspaceStatus
from app.models.mixins import CreatedAtMixin, TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.project import Project


def _values(roles: frozenset[Role]) -> str:
    """Список значений для CHECK. Сортировка нужна ради стабильного текста миграции."""
    return ", ".join(f"'{role.value}'" for role in sorted(roles))


class Workspace(TimestampMixin, Base):
    """Рабочее пространство — граница арендатора.

    До Stage 1.5 это был свободный UUID в `projects`. Теперь у него есть строка, и внешний
    ключ не даёт создать проект в пространстве, которого нет.
    """

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[WorkspaceStatus] = mapped_column(
        str_enum(WorkspaceStatus, name="workspace_status"),
        nullable=False,
        default=WorkspaceStatus.ACTIVE,
        server_default=WorkspaceStatus.ACTIVE.value,
    )

    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", passive_deletes=True
    )
    projects: Mapped[list[Project]] = relationship(back_populates="workspace")

    __table_args__ = (Index("ix_workspaces_status_name", "status", "name"),)


class UserIdentity(TimestampMixin, Base):
    """Личность, пришедшая от провайдера входа.

    Ключ — пара (издатель, субъект): один и тот же адрес почты у разных провайдеров
    принадлежит разным людям, и склеивать их по почте нельзя.
    """

    __tablename__ = "user_identities"

    id: Mapped[uuid.UUID] = uuid_pk()

    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)

    email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false"
    )
    display_name: Mapped[str | None] = mapped_column(String(200))

    kind: Mapped[UserKind] = mapped_column(
        str_enum(UserKind, name="user_kind"),
        nullable=False,
        default=UserKind.HUMAN,
        server_default=UserKind.HUMAN.value,
    )

    # Роль уровня платформы. Пусто у обычного пользователя: его права целиком приходят
    # из членства в пространствах.
    platform_role: Mapped[Role | None] = mapped_column(str_enum(Role, name="platform_role"))

    # Отключение вместо удаления: уволенный сотрудник не должен уносить с собой историю
    # действий из журнала аудита.
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[WorkspaceMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_user_identities_issuer_subject"),
        # В платформенное поле нельзя положить роль пространства: иначе `viewer` уровня
        # установки означал бы неизвестно что, и проверка прав давала бы пустой набор.
        CheckConstraint(
            f"platform_role is null or platform_role in ({_values(PLATFORM_ROLES)})",
            name="platform_role_is_platform_level",
        ),
        Index("ix_user_identities_email", "email"),
    )


class WorkspaceMembership(TimestampMixin, Base):
    """Участие личности в рабочем пространстве и её роль там."""

    __tablename__ = "workspace_memberships"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[Role] = mapped_column(str_enum(Role, name="membership_role"), nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[UserIdentity] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_memberships_workspace_user"),
        # Платформенную роль через членство выдать нельзя. Без этого администратором
        # установки становился бы любой, кто может добавить строку в своём же пространстве.
        CheckConstraint(
            f"role in ({_values(WORKSPACE_ROLES)})",
            name="role_is_workspace_level",
        ),
        Index("ix_workspace_memberships_user_id_created_at", "user_id", "created_at"),
    )


class AuthSession(CreatedAtMixin, Base):
    """Сеанс работы в браузере.

    Строка в базе, а не самодостаточный токен в cookie: только так выход действительно
    обесценивает сеанс, а администратор может отозвать скомпрометированный.

    В cookie уходит случайный непрозрачный токен, здесь лежит его SHA-256. Утечка дампа
    базы не даёт войти ни в один сеанс.
    """

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # IPv6 в текстовом виде — 45 символов. Хранится для разбора инцидентов, не для аналитики.
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    user: Mapped[UserIdentity] = relationship()

    __table_args__ = (
        Index("ix_auth_sessions_user_id_created_at", "user_id", "created_at"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )
