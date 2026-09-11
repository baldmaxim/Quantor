"""Общие зависимости обработчиков API v1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, params
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.resolver import get_auth_context, require
from app.core.config import Settings, get_settings
from app.core.features import REGISTRY
from app.db.session import get_session
from app.errors import DomainError, ErrorCode
from app.integrations.tenderhub import TenderHubClient
from app.schemas import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.services import feature_flags as flags_service
from app.services.job_runner import JobScheduler, get_job_scheduler
from app.storage import get_object_storage
from app.storage.base import ObjectStorage

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Контекст запроса. Имя `WorkspaceDep` сохранено намеренно: обработчики читают
# `workspace.workspace_id`, и появление настоящей аутентификации не должно было
# превращаться в правку каждого маршрута. Теперь за этим именем стоит проверенная
# личность и её права, а не константа.
AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
WorkspaceDep = AuthDep

# Хранилище приходит зависимостью, а не берётся из модуля: так его можно подменить
# в тестах, не поднимая MinIO и не патча импорты.
StorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]

# Запуск фонового задания — тоже зависимость: иначе тест загрузки поднимал бы реальный импорт.
SchedulerDep = Annotated[JobScheduler, Depends(get_job_scheduler)]

# Настройки зависимостью нужны интеграциям: тест подменяет адрес и ключ, не трогая окружение.
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_tenderhub_client(settings: SettingsDep) -> AsyncIterator[TenderHubClient]:
    """Клиент внешней системы на время запроса.

    Зависимостью, а не прямым вызовом: тест подменяет транспорт и проверяет разбор
    ответов, ни разу не выходя в сеть.
    """
    async with TenderHubClient(settings) as client:
        yield client


TenderHubDep = Annotated[TenderHubClient, Depends(get_tenderhub_client)]


class FeatureCheck:
    """Возможность включена для пространства запроса (ADR-0023).

    Объект, а не замыкание, по той же причине, что и `PermissionCheck`: тест покрытия
    читает ключ флага прямо из зависимости маршрута.

    Флаг вычисляется тем же провайдером, что и `/api/v1/meta`, — иначе интерфейс и сервер
    однажды разойдутся в ответе на вопрос «включено ли». Проверка стоит после опознания:
    запрос без сеанса по-прежнему получает 401, а не сведения о флагах.
    """

    __slots__ = ("key",)

    def __init__(self, key: str) -> None:
        if key not in REGISTRY:
            # Опечатка в ключе закрыла бы маршрут навсегда — пусть лучше не стартует приложение.
            raise ValueError(f"Флага «{key}» нет в реестре")
        self.key = key

    async def __call__(self, session: SessionDep, settings: SettingsDep, context: AuthDep) -> None:
        evaluated = await flags_service.evaluate_all(
            session,
            settings,
            flags_service.EvaluationContext(workspace_id=context.workspace_id),
        )
        if not evaluated[self.key].value:
            raise DomainError(ErrorCode.FEATURE_DISABLED)


def require_feature(key: str) -> params.Depends:
    """Маршрут доступен, только пока возможность включена для пространства запроса."""
    return params.Depends(dependency=FeatureCheck(key))


LimitDep = Annotated[
    int,
    Query(ge=1, le=MAX_PAGE_SIZE, description="Сколько записей вернуть"),
]
OffsetDep = Annotated[int, Query(ge=0, description="Сколько записей пропустить")]

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "AuthDep",
    "LimitDep",
    "OffsetDep",
    "SchedulerDep",
    "SessionDep",
    "SettingsDep",
    "StorageDep",
    "TenderHubDep",
    "WorkspaceDep",
    "require",
    "require_feature",
]
