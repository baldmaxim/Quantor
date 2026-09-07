"""Разрешения и их наборы.

Бизнес-код проверяет разрешение, а не имя роли. Разница не стилистическая: когда через
месяц выяснится, что проверяющему нужен доступ к заданиям, правится одна строка в
`ROLE_PERMISSIONS`, а не десяток обработчиков, где упомянуто слово `reviewer`.

Роли строятся вложением: каждая следующая добавляет к предыдущей, а не перечисляет всё
заново. Список, переписанный целиком, расходится с соседним при первой же правке.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

from app.domain import Role


class Permission(StrEnum):
    """Что именно разрешено сделать.

    Значения — часть контракта: они попадают в ответ `/auth/session` и в журнал аудита,
    поэтому переименование значения ломает клиента так же, как переименование поля.
    """

    SYSTEM_ADMIN = "system.admin"

    WORKSPACE_READ = "workspace.read"
    WORKSPACE_MANAGE = "workspace.manage"
    WORKSPACE_MEMBERS_MANAGE = "workspace.members.manage"

    PROJECT_READ = "project.read"
    PROJECT_CREATE = "project.create"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"

    DOCUMENT_READ = "document.read"
    DOCUMENT_UPLOAD = "document.upload"

    INTEGRATION_READ = "integration.read"
    INTEGRATION_MANAGE = "integration.manage"

    FEATURE_FLAGS_READ = "feature_flags.read"
    FEATURE_FLAGS_MANAGE = "feature_flags.manage"

    SETTINGS_READ = "settings.read"
    SETTINGS_MANAGE = "settings.manage"

    JOBS_READ = "jobs.read"
    JOBS_MANAGE = "jobs.manage"

    MODELS_READ = "models.read"
    MODELS_MANAGE = "models.manage"

    AUDIT_READ = "audit.read"


# Читатель: видит проекты и документы своего пространства, не меняет ничего.
_VIEWER: Final[frozenset[Permission]] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.FEATURE_FLAGS_READ,
    }
)

# Проверяющий: дополнительно видит служебную картину — задания, состояние интеграций,
# действующие настройки. Проверять чужую работу вслепую нельзя.
_REVIEWER: Final[frozenset[Permission]] = _VIEWER | {
    Permission.JOBS_READ,
    Permission.INTEGRATION_READ,
    Permission.SETTINGS_READ,
    Permission.MODELS_READ,
}

# Инженер: рабочие действия с проектами. Удаления здесь намеренно нет — удалённый проект
# уносит с собой ревизии и распознанные области, и это решение уровня администратора.
_ENGINEER: Final[frozenset[Permission]] = _REVIEWER | {
    Permission.PROJECT_CREATE,
    Permission.PROJECT_UPDATE,
    Permission.DOCUMENT_UPLOAD,
}

# Администратор пространства: управляет своим пространством целиком, но не платформой.
# SETTINGS_MANAGE и FEATURE_FLAGS_MANAGE выданы, однако системный уровень переопределения
# дополнительно требует SYSTEM_ADMIN — иначе арендатор менял бы поведение всей установки.
_WORKSPACE_ADMIN: Final[frozenset[Permission]] = _ENGINEER | {
    Permission.PROJECT_DELETE,
    Permission.WORKSPACE_MANAGE,
    Permission.WORKSPACE_MEMBERS_MANAGE,
    Permission.INTEGRATION_MANAGE,
    Permission.FEATURE_FLAGS_MANAGE,
    Permission.SETTINGS_MANAGE,
    Permission.JOBS_MANAGE,
    Permission.AUDIT_READ,
}

# Машинная личность: только чтение. Ключ, умеющий писать, рано или поздно окажется
# в чужом скрипте, и объяснить последствия будет нечем.
_SERVICE: Final[frozenset[Permission]] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.JOBS_READ,
    }
)

ROLE_PERMISSIONS: Final[MappingProxyType[Role, frozenset[Permission]]] = MappingProxyType(
    {
        # Администратор платформы получает всё перечислением множества, а не проверкой
        # «если это администратор — пропустить». Особый случай в бизнес-коде — это ветка,
        # которую забывают продублировать в следующем обработчике.
        Role.PLATFORM_ADMIN: frozenset(Permission),
        Role.WORKSPACE_ADMIN: _WORKSPACE_ADMIN,
        Role.ENGINEER: _ENGINEER,
        Role.REVIEWER: _REVIEWER,
        Role.VIEWER: _VIEWER,
        Role.SERVICE: _SERVICE,
    }
)


def permissions_for(role: Role) -> frozenset[Permission]:
    """Набор разрешений роли."""
    return ROLE_PERMISSIONS[role]
