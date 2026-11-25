"""Приём файлов в проект."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import SchedulerDep, SessionDep, StorageDep, WorkspaceDep, require
from app.auth.permissions import Permission
from app.core.config import get_settings
from app.domain import JobStatus
from app.errors import DomainError, ErrorCode, http_error, not_found
from app.models import Document, DocumentRevision, Job, TenderImportItem
from app.schemas import UploadedFileType, UploadRead
from app.services import documents as documents_service
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.services import tender_imports as tender_imports_service
from app.services import uploads as uploads_service
from app.services.uploads import CHUNK_SIZE, SUPPORTED_EXTENSIONS, UploadOutcome

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
    response: Response,
    file: Annotated[UploadFile, File(description="Файл проекта")],
    document_id: Annotated[
        uuid.UUID | None,
        Form(description="Добавить как новую ревизию существующего документа"),
    ] = None,
    tender_import_id: Annotated[
        uuid.UUID | None,
        Form(description="Пакетный импорт: к какому импорту относится файл"),
    ] = None,
    tender_import_item: Annotated[
        str | None,
        Form(description="Пакетный импорт: ключ позиции перечня"),
    ] = None,
) -> UploadRead:
    """Принимает файл, кладёт его в хранилище и заводит документ с ревизией.

    Распознавание здесь не выполняется: для ZIP-пакета создаётся задание импорта в состоянии
    «в очереди», для остальных типов ревизия сохраняется с честным статусом обработки.

    С полями `tender_import_id` и `tender_import_item` файл привязывается к позиции пакетного
    импорта: заявленные хеш и размер сверяются, повтор уже принятой позиции возвращает прежний
    результат (200), а не создаёт вторую ревизию.
    """
    project = await projects_service.get_project(
        session, workspace_id=workspace.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    if (tender_import_id is None) != (tender_import_item is None):
        raise http_error(
            ErrorCode.VALIDATION_FAILED,
            message="Поля tender_import_id и tender_import_item передаются вместе",
        )
    if tender_import_id is not None and document_id is not None:
        raise http_error(
            ErrorCode.VALIDATION_FAILED,
            message="document_id нельзя сочетать с пакетным импортом",
        )

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

    item = None
    previously_failed = False
    if tender_import_id is not None and tender_import_item is not None:
        if not file.filename.lower().endswith(".zip"):
            raise http_error(
                ErrorCode.VALIDATION_FAILED,
                message="В пакетном импорте принимаются только ZIP-пакеты распознавалки",
            )
        # Строка позиции берётся под блокировкой до приёма файла: две загрузки одной позиции
        # идут по очереди, вторая видит результат первой.
        _, item = await tender_imports_service.lock_item(
            session,
            workspace_id=workspace.tenant,
            project_id=project.id,
            import_id=tender_import_id,
            item_key=tender_import_item,
        )
        view = await tender_imports_service.item_view(session, project_id=project.id, item=item)
        previously_failed = view.state == "failed"
        if item.package_revision_id is not None and not previously_failed:
            known = await _known_outcome(session, item=item)
            if known is not None:
                response.status_code = status.HTTP_200_OK
                return UploadRead.from_outcome(known)
        elif item.package_revision_id is None and view.state in ("imported", "conflict"):
            raise DomainError(ErrorCode.TENDER_IMPORT_ITEM_DONE, issue={"state": view.state})

    outcome = await uploads_service.receive_upload(
        session,
        storage,
        project=project,
        filename=file.filename,
        chunks=_stream(file),
        max_size=settings.max_upload_size_bytes,
        document=document,
        expected_sha256=item.sha256 if item is not None else None,
        expected_size=item.size if item is not None else None,
    )
    if item is not None:
        tender_imports_service.attach_outcome(
            item, revision_id=outcome.revision.id, job=outcome.job
        )
        # Повтор упавшей позиции: тот же пакет и то же задание, отказ которого можно повторить.
        if (
            previously_failed
            and outcome.is_duplicate
            and outcome.job is not None
            and jobs_service.is_retryable(outcome.job)
        ):
            await jobs_service.retry(session, job=outcome.job)
        if outcome.is_duplicate:
            response.status_code = status.HTTP_200_OK
    await session.commit()

    # Импорт запускается только после того, как записи зафиксированы: иначе фоновая задача
    # не найдёт ни задания, ни ревизии.
    if outcome.job is not None and outcome.job.status is JobStatus.QUEUED:
        schedule(outcome.job.id)

    return UploadRead.from_outcome(outcome)


async def _known_outcome(session: AsyncSession, *, item: TenderImportItem) -> UploadOutcome | None:
    """Прежний результат приёма позиции: ревизия пакета, её документ и задание импорта."""
    if item.package_revision_id is None:
        return None
    revision = await session.get(DocumentRevision, item.package_revision_id)
    if revision is None:
        return None
    document = await session.get(Document, revision.document_id)
    if document is None:
        return None
    return UploadOutcome(
        document=document,
        revision=revision,
        job=await session.get(Job, item.job_id) if item.job_id is not None else None,
        is_duplicate=True,
        sheet_count=await documents_service.count_sheets(session, revision_id=revision.id),
    )


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
