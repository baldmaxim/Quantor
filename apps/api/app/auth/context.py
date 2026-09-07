"""Контекст запроса: кто спрашивает, в каком пространстве и что ему можно.

Собирается только на сервере. Ничто из тела запроса сюда не попадает: пользователь,
приславший `{"role": "platform_admin"}`, должен получить ровно то же, что и без этого поля.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.auth.permissions import Permission
from app.domain import Role, UserKind
from app.errors import DomainError, ErrorCode


class CredentialKind(StrEnum):
    """Чем подтверждён запрос.

    Нужно не для отчётности: у cookie есть проблема CSRF, у токена в заголовке её нет,
    и проверка должна знать, какой случай перед ней.
    """

    DEV = "dev"
    SESSION = "session"
    BEARER = "bearer"


@dataclass(frozen=True, slots=True)
class Principal:
    """Личность, стоящая за запросом."""

    user_id: uuid.UUID
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    kind: UserKind
    platform_role: Role | None

    @property
    def is_platform_admin(self) -> bool:
        return self.platform_role is Role.PLATFORM_ADMIN

    @property
    def label(self) -> str:
        """Как назвать актора в журнале, когда личности уже может не быть в базе."""
        return self.email or self.display_name or f"{self.issuer}:{self.subject}"


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Результат аутентификации и авторизации запроса.

    Поле `workspace_id` намеренно называется так же, как раньше в `WorkspaceContext`:
    все существующие обработчики читают именно его, и подмена источника контекста не должна
    превращаться в правку каждого маршрута.
    """

    principal: Principal
    workspace_id: uuid.UUID
    role: Role
    permissions: frozenset[Permission]
    credential: CredentialKind
    is_dev_mode: bool
    session_id: uuid.UUID | None = None

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def require(self, permission: Permission) -> None:
        """Проверка права. Отказ — 403: кто спрашивает, уже известно."""
        if permission not in self.permissions:
            raise DomainError(
                ErrorCode.PERMISSION_DENIED,
                f"Недостаточно прав: требуется {permission.value}",
            )
