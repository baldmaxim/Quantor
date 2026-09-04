"""Общие зависимости обработчиков API v1."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace import WorkspaceContext, get_workspace_context
from app.db.session import get_session
from app.schemas import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.storage import get_object_storage
from app.storage.base import ObjectStorage

SessionDep = Annotated[AsyncSession, Depends(get_session)]
WorkspaceDep = Annotated[WorkspaceContext, Depends(get_workspace_context)]

# Хранилище приходит зависимостью, а не берётся из модуля: так его можно подменить
# в тестах, не поднимая MinIO и не патча импорты.
StorageDep = Annotated[ObjectStorage, Depends(get_object_storage)]

LimitDep = Annotated[
    int,
    Query(ge=1, le=MAX_PAGE_SIZE, description="Сколько записей вернуть"),
]
OffsetDep = Annotated[int, Query(ge=0, description="Сколько записей пропустить")]

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "LimitDep",
    "OffsetDep",
    "SessionDep",
    "StorageDep",
    "WorkspaceDep",
]
