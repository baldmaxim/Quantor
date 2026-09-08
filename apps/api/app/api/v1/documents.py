"""Документы, ревизии, листы, области и ссылка на файл ревизии."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.v1.deps import (
    DEFAULT_PAGE_SIZE,
    LimitDep,
    OffsetDep,
    SessionDep,
    StorageDep,
    WorkspaceDep,
    require,
)
from app.auth.permissions import Permission
from app.core.config import get_settings
from app.errors import ErrorCode, http_error, not_found
from app.schemas import (
    ContentUrl,
    DocumentRead,
    DocumentRevisionRead,
    Page,
    RecognitionArtifactRead,
    RegionRead,
    SheetRead,
)
from app.services import documents as documents_service
from app.storage.base import ObjectNotFoundError, StorageUnavailableError

router = APIRouter(tags=["documents"])


@router.get(
    "/documents/{document_id}",
    response_model=DocumentRead,
    summary="Документ",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_document(
    document_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> DocumentRead:
    document = await documents_service.get_document(
        session, workspace_id=workspace.tenant, document_id=document_id
    )
    if document is None:
        raise not_found("Документ")
    return DocumentRead.model_validate(document)


@router.get(
    "/documents/{document_id}/revisions",
    response_model=Page[DocumentRevisionRead],
    summary="Ревизии документа",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_document_revisions(
    document_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
) -> Page[DocumentRevisionRead]:
    document = await documents_service.get_document(
        session, workspace_id=workspace.tenant, document_id=document_id
    )
    if document is None:
        raise not_found("Документ")

    rows = await documents_service.list_revisions(
        session, document_id=document.id, limit=limit, offset=offset
    )
    total = await documents_service.count_revisions(session, document_id=document.id)
    return Page(
        items=[DocumentRevisionRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/revisions/{revision_id}",
    response_model=DocumentRevisionRead,
    summary="Ревизия документа",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_revision(
    revision_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> DocumentRevisionRead:
    revision = await documents_service.get_revision(
        session, workspace_id=workspace.tenant, revision_id=revision_id
    )
    if revision is None:
        raise not_found("Ревизия")
    return DocumentRevisionRead.model_validate(revision)


@router.get(
    "/revisions/{revision_id}/artifacts",
    response_model=list[RecognitionArtifactRead],
    summary="Артефакты распознавания",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_revision_artifacts(
    revision_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> list[RecognitionArtifactRead]:
    revision = await documents_service.get_revision(
        session, workspace_id=workspace.tenant, revision_id=revision_id
    )
    if revision is None:
        raise not_found("Ревизия")

    rows = await documents_service.list_artifacts(session, revision_id=revision.id)
    return [RecognitionArtifactRead.model_validate(row) for row in rows]


@router.get(
    "/revisions/{revision_id}/sheets",
    response_model=Page[SheetRead],
    summary="Листы ревизии",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_revision_sheets(
    revision_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
) -> Page[SheetRead]:
    revision = await documents_service.get_revision(
        session, workspace_id=workspace.tenant, revision_id=revision_id
    )
    if revision is None:
        raise not_found("Ревизия")

    rows = await documents_service.list_sheets(
        session, revision_id=revision.id, limit=limit, offset=offset
    )
    total = await documents_service.count_sheets(session, revision_id=revision.id)
    items = [
        SheetRead(
            id=row.sheet.id,
            revision_id=row.sheet.revision_id,
            page_index=row.sheet.page_index,
            page_label=row.sheet.page_label,
            width_px=row.sheet.width_px,
            height_px=row.sheet.height_px,
            rotation=row.sheet.rotation,
            region_count=row.region_count,
        )
        for row in rows
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/revisions/{revision_id}/content-url",
    response_model=ContentUrl,
    summary="Ссылка на файл ревизии",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def read_revision_content_url(
    revision_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep, storage: StorageDep
) -> ContentUrl:
    """Временная ссылка прямо в хранилище.

    Просмотрщику нужен доступ с поддержкой Range-запросов, чтобы читать только текущую
    страницу документа. Проксировать такой файл через процесс приложения нельзя.
    """
    revision = await documents_service.get_revision(
        session, workspace_id=workspace.tenant, revision_id=revision_id
    )
    if revision is None:
        raise not_found("Ревизия")

    settings = get_settings()
    try:
        url = await storage.presigned_get_url(
            revision.storage_key,
            expires_in=settings.content_url_ttl_seconds,
            download_filename=revision.source_filename,
        )
    except ObjectNotFoundError as error:
        raise http_error(ErrorCode.CONTENT_NOT_AVAILABLE) from error
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error

    return ContentUrl(
        url=url,
        expires_in=settings.content_url_ttl_seconds,
        filename=revision.source_filename,
        content_type=revision.source_mime,
    )


@router.get(
    "/sheets/{sheet_id}/regions",
    response_model=Page[RegionRead],
    summary="Области на листе",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_sheet_regions(
    sheet_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    limit: LimitDep = DEFAULT_PAGE_SIZE,
    offset: OffsetDep = 0,
    block_type: str | None = Query(default=None, description="Фильтр по типу области"),
    recognition_status: str | None = Query(
        default=None, description="Фильтр по статусу распознавания"
    ),
) -> Page[RegionRead]:
    sheet = await documents_service.get_sheet(
        session, workspace_id=workspace.tenant, sheet_id=sheet_id
    )
    if sheet is None:
        raise not_found("Лист")

    rows = await documents_service.list_regions(
        session,
        sheet_id=sheet.id,
        limit=limit,
        offset=offset,
        block_type=block_type,
        recognition_status=recognition_status,
    )
    total = await documents_service.count_regions(
        session,
        sheet_id=sheet.id,
        block_type=block_type,
        recognition_status=recognition_status,
    )
    return Page(
        items=[RegionRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
