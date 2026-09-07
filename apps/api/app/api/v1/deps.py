"""Общие зависимости обработчиков API v1."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.resolver import get_auth_context, require
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.integrations.tenderhub import TenderHubClient
from app.schemas import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
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
]
