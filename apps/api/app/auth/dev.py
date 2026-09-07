"""Вход без провайдера — только для локальной работы и тестов.

Смысл режима в одном свойстве: он выдаёт контекст **не обращаясь к базе**. На этом держатся
три существующих проверки, ломать которые нельзя:

- недоступная база отвечает 503, а не 401: иначе диагностика уводит чинить вход, пока лежит
  база;
- выборка листов укладывается в отведённое число запросов;
- тесты оболочки работают на клиенте без базы вовсе.

Режим выключен снаружи локальной среды: за это отвечает валидатор `Settings`, роняющий
запуск. Здесь дополнительной проверки нет намеренно — два места, решающих один вопрос,
рано или поздно расходятся.
"""

from __future__ import annotations

import uuid
from typing import Final

from app.auth.context import AuthContext, CredentialKind, Principal
from app.auth.permissions import permissions_for
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import Role, UserKind

# Постоянный идентификатор dev-личности: одинаков между перезапусками, иначе журнал
# действий после рестарта указывал бы на другого человека.
DEV_USER_ID: Final[uuid.UUID] = uuid.UUID("00000000-0000-4000-8000-000000000002")

DEV_ISSUER: Final = "dev"
DEV_SUBJECT: Final = "dev"

# Заголовок для ручной проверки интерфейса под другой ролью. Работает только здесь,
# то есть только в локальной среде.
DEV_ROLE_HEADER: Final = "X-Dev-Role"


def dev_principal() -> Principal:
    return Principal(
        user_id=DEV_USER_ID,
        issuer=DEV_ISSUER,
        subject=DEV_SUBJECT,
        email="dev@localhost",
        display_name="Разработчик",
        kind=UserKind.HUMAN,
        platform_role=Role.PLATFORM_ADMIN,
    )


def dev_context(role_header: str | None = None) -> AuthContext:
    """Контекст dev-режима. Ни одного запроса к базе.

    По умолчанию — администратор платформы: локально удобнее видеть весь портал целиком,
    а ограничения проверяются заголовком и тестами.
    """
    role = _parse_role(role_header)
    principal = dev_principal()
    if role is not Role.PLATFORM_ADMIN:
        # Под чужой ролью платформенных прав быть не должно, иначе проверка «инженер
        # не администратор» в dev-режиме показывала бы неправду.
        principal = Principal(
            user_id=principal.user_id,
            issuer=principal.issuer,
            subject=principal.subject,
            email=principal.email,
            display_name=principal.display_name,
            kind=principal.kind,
            platform_role=None,
        )

    return AuthContext(
        principal=principal,
        workspace_id=DEV_WORKSPACE_ID,
        role=role,
        permissions=permissions_for(role),
        credential=CredentialKind.DEV,
        is_dev_mode=True,
    )


def _parse_role(raw: str | None) -> Role:
    """Роль из заголовка. Неизвестное значение игнорируется, а не роняет запрос."""
    if not raw:
        return Role.PLATFORM_ADMIN
    try:
        return Role(raw.strip().lower())
    except ValueError:
        return Role.PLATFORM_ADMIN
