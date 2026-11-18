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

    # Ручной обмер (ADR-0018). `verify` отделён от `edit` намеренно: подтверждение — это
    # ответственность за число перед заказчиком, и она не обязана совпадать с правом
    # это число внести.
    TAKEOFF_READ = "takeoff.read"
    TAKEOFF_EDIT = "takeoff.edit"
    TAKEOFF_VERIFY = "takeoff.verify"

    # Расчётный контур (ADR-0030). `verify` отдельно от `edit` по той же причине, что у
    # обмера: подтвердить факт или решить конфликт источников — ответственность за число,
    # и она не обязана совпадать с правом это число внести.
    CALC_READ = "calc.read"
    CALC_EDIT = "calc.edit"
    CALC_VERIFY = "calc.verify"

    # Обмен расчётами с TENDER (ADR-0051). Чтение и загрузка расчётов — рабочие действия;
    # выпуск базы объекта и отзыв версии расчёта — решения координатора (администратора
    # пространства): выпуск неизменяем, а отзыв убирает расчёт из показа.
    TENDER_CALC_READ = "tender.calc.read"
    TENDER_CALC_UPLOAD = "tender.calc.upload"
    TENDER_BASE_RELEASE = "tender.base.release"
    TENDER_CALC_WITHDRAW = "tender.calc.withdraw"


# Читатель: видит проекты и документы своего пространства, не меняет ничего.
_VIEWER: Final[frozenset[Permission]] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.FEATURE_FLAGS_READ,
        # Читатель видит обмеры и масштаб: величина без основания непроверяема, а
        # основание — это и есть калибровка с измерениями.
        Permission.TAKEOFF_READ,
        Permission.CALC_READ,
        Permission.TENDER_CALC_READ,
    }
)

# Проверяющий: дополнительно видит служебную картину — задания, состояние интеграций,
# действующие настройки. Проверять чужую работу вслепую нельзя.
_REVIEWER: Final[frozenset[Permission]] = _VIEWER | {
    Permission.JOBS_READ,
    Permission.INTEGRATION_READ,
    Permission.SETTINGS_READ,
    Permission.MODELS_READ,
    # Подтверждать обмер, но не вносить его: разделение автора и проверяющего —
    # смысл роли, а не формальность.
    Permission.TAKEOFF_VERIFY,
    Permission.CALC_VERIFY,
}

# Инженер: рабочие действия с проектами. Удаления здесь намеренно нет — удалённый проект
# уносит с собой ревизии и распознанные области, и это решение уровня администратора.
_ENGINEER: Final[frozenset[Permission]] = _REVIEWER | {
    Permission.PROJECT_CREATE,
    Permission.PROJECT_UPDATE,
    Permission.DOCUMENT_UPLOAD,
    Permission.TAKEOFF_EDIT,
    Permission.CALC_EDIT,
    Permission.TENDER_CALC_UPLOAD,
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
    Permission.TENDER_BASE_RELEASE,
    Permission.TENDER_CALC_WITHDRAW,
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


# Область персонального токена `qtk_…` (ADR-0051): права токена — права роли владельца,
# суженные до этого набора. Токен читает проекты и документы, читает выпуски базы и расчёты
# и загружает расчёты; выпуск базы, отзыв, администрирование и выпуск токенов ему недоступны.
API_TOKEN_PERMISSIONS: Final[frozenset[Permission]] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.TENDER_CALC_READ,
        Permission.TENDER_CALC_UPLOAD,
    }
)


# Область `read` (API для агентов, 2026-11-18): только чтение - пространство, проекты, документы и
# их разбор (виды, оси, «Здание», модель), задания, выпуски базы и расчёты. Ничего не меняет.
READ_TOKEN_PERMISSIONS: Final[frozenset[Permission]] = frozenset(
    {
        Permission.WORKSPACE_READ,
        Permission.PROJECT_READ,
        Permission.DOCUMENT_READ,
        Permission.JOBS_READ,
        Permission.TENDER_CALC_READ,
    }
)

# Область `upload`: чтение и загрузка документов (новые ревизии, IFC), а с ней всё, что на портале
# закрыто тем же правом: построение модели здания из IFC, задания разбора чертежей. Как у человека с
# этой ролью, но без создания проектов, расчёта, выпуска базы и токенов.
UPLOAD_TOKEN_PERMISSIONS: Final[frozenset[Permission]] = READ_TOKEN_PERMISSIONS | frozenset(
    {Permission.DOCUMENT_UPLOAD}
)


def permissions_for(role: Role) -> frozenset[Permission]:
    """Набор разрешений роли."""
    return ROLE_PERMISSIONS[role]
