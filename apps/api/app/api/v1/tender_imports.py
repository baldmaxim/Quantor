"""Пакетный импорт тендерной документации: запуск и статус.

Файлы здесь не передаются: клиент присылает перечень ZIP-пакетов с хешами, портал отвечает, что
уже есть и что догрузить обычным приёмом файлов (`POST /projects/{id}/uploads` с полями
`tender_import_id` и `tender_import_item`). Состояние позиций вычисляется при чтении.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.v1.deps import (
    OptionalTenderHubDep,
    SessionDep,
    SettingsDep,
    WorkspaceDep,
    require,
)
from app.auth.permissions import Permission
from app.contracts.tender_imports import TenderImportRead, TenderImportStart
from app.services import tender_imports as tender_imports_service

router = APIRouter(prefix="/tender-imports", tags=["tender-imports"])


@router.post(
    "",
    response_model=TenderImportRead,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить пакетный импорт тендерной документации",
    responses={status.HTTP_200_OK: {"model": TenderImportRead}},
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_tender_import(
    payload: TenderImportStart,
    response: Response,
    session: SessionDep,
    workspace: WorkspaceDep,
    settings: SettingsDep,
    client: OptionalTenderHubDep,
) -> TenderImportRead:
    """Находит или создаёт объект и запись комплекта; 201 - импорт создан, 200 - найден прежний."""
    read, created = await tender_imports_service.start(
        session, workspace, settings=settings, payload=payload, client=client
    )
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return read


@router.get(
    "/{import_id}",
    response_model=TenderImportRead,
    summary="Состояние пакетного импорта",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_tender_import(
    import_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    settings: SettingsDep,
) -> TenderImportRead:
    return await tender_imports_service.get_status(
        session, workspace, settings=settings, import_id=import_id
    )
