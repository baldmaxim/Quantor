"""Приём файлов в проект."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

from app.api.v1.deps import SchedulerDep, SessionDep, StorageDep, WorkspaceDep, require
from app.auth.permissions import Permission
from app.core.config import get_settings
from app.domain import JobStatus
from app.errors import ErrorCode, http_error, not_found
from app.schemas import UploadedFileType, UploadRead
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import uploads as uploads_service
from app.services.uploads import CHUNK_SIZE, SUPPORTED_EXTENSIONS

router = APIRouter(prefix="/projects/{project_id}", tags=["uploads"])


async def _stream(upload: UploadFile) -> AsyncIterator[bytes]:
    """Читает тело запроса кусками.

    Starlette держит загруженный файл во временном файле на диске, поэтому потребление
    памяти не зависит от размера документа — но только если читать его так, а не целиком.
    """
    while chunk := await upload.read(CHUNK_SIZE):
        yield chunk


@router.post(
    "/uploads",
    response_model=UploadRead,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить файл в проект",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def upload_file(
    project_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    storage: StorageDep,
    schedule: SchedulerDep,
    file: Annotated[UploadFile, File(description="Файл проекта")],
    document_id: Annotated[
        uuid.UUID | None,
        Form(description="Добавить как новую ревизию существующего документа"),
    ] = None,
) -> UploadRead:
    """Принимает файл, кладёт его в хранилище и заводит документ с ревизией.

    Распознавание здесь не выполняется: для ZIP-пакета создаётся задание импорта в состоянии
    «в очереди», для остальных типов ревизия сохраняется с честным статусом обработки.
    """
    project = await projects_service.get_project(
        session, workspace_id=workspace.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    document = None
    if document_id is not None:
        document = await documents_service.get_document(
            session, workspace_id=workspace.tenant, document_id=document_id
        )
        if document is None or document.project_id != project.id:
            raise not_found("Документ")

    if not file.filename:
        raise http_error(ErrorCode.VALIDATION_FAILED, message="Имя файла не передано")

    settings = get_settings()
    outcome = await uploads_service.receive_upload(
        session,
        storage,
        project=project,
        filename=file.filename,
        chunks=_stream(file),
        max_size=settings.max_upload_size_bytes,
        document=document,
    )
    await session.commit()

    # Импорт запускается только после того, как записи зафиксированы: иначе фоновая задача
    # не найдёт ни задания, ни ревизии.
    if outcome.job is not None and outcome.job.status is JobStatus.QUEUED:
        schedule(outcome.job.id)

    return UploadRead.from_outcome(outcome)


@router.get(
    "/upload-capabilities",
    response_model=list[UploadedFileType],
    summary="Какие файлы принимает портал",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_upload_capabilities(
    project_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> list[UploadedFileType]:
    """Список поддерживаемых расширений и того, что портал с ними сделает.

    Интерфейс берёт подписи отсюда, а не хранит свою копию: иначе при подключении нового
    обработчика обещания на экране разойдутся с поведением сервера.
    """
    project = await projects_service.get_project(
        session, workspace_id=workspace.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    settings = get_settings()
    return [
        UploadedFileType(
            extension=extension,
            document_kind=kind.document_kind,
            capability=kind.capability,
            schedules_import=kind.schedules_import,
            max_size_bytes=settings.max_upload_size_bytes,
        )
        for extension, kind in SUPPORTED_EXTENSIONS.items()
    ]
