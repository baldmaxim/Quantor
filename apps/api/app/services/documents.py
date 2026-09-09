"""Сервис документов, ревизий, листов и областей.

Все выборки идут от проекта вниз по цепочке владения, поэтому обратиться к чужому документу
по прямому идентификатору нельзя: запрос всё равно проверит рабочее пространство.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import DocumentKind, GeometryStatus, ProcessingStatus
from app.models import Document, DocumentRevision, Project, RecognitionArtifact, Region, Sheet


@dataclass(frozen=True, slots=True)
class SheetWithCount:
    sheet: Sheet
    region_count: int


# --------------------------------------------------------------------------- документы


async def create_document(
    session: AsyncSession,
    *,
    project: Project,
    display_name: str,
    document_kind: DocumentKind,
    discipline: str | None = None,
) -> Document:
    document = Document(
        project_id=project.id,
        display_name=display_name,
        document_kind=document_kind,
        discipline=discipline,
    )
    session.add(document)
    await session.flush()
    await session.refresh(document)
    return document


async def get_document(
    session: AsyncSession, *, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    query = (
        select(Document)
        .join(Project, Document.project_id == Project.id)
        .where(Document.id == document_id, Project.workspace_id == workspace_id)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_documents(
    session: AsyncSession, *, project_id: uuid.UUID, limit: int, offset: int
) -> list[Document]:
    query = (
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_documents(session: AsyncSession, *, project_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Document).where(Document.project_id == project_id)
    )
    return int(result.scalar_one())


# --------------------------------------------------------------------------- ревизии


async def create_revision(
    session: AsyncSession,
    *,
    document: Document,
    revision_id: uuid.UUID,
    source_filename: str,
    source_mime: str,
    source_size: int,
    source_sha256: str,
    storage_key: str,
    processing_status: ProcessingStatus,
    revision_label: str | None = None,
    source_metadata: dict[str, object] | None = None,
    geometry_status: GeometryStatus = GeometryStatus.NOT_APPLICABLE,
) -> DocumentRevision:
    """Создаёт неизменяемую ревизию.

    Идентификатор передаётся снаружи: ключ объекта в хранилище строится из него ещё
    до записи в базу, иначе файл пришлось бы перекладывать после вставки.
    """
    revision = DocumentRevision(
        id=revision_id,
        document_id=document.id,
        revision_label=revision_label,
        source_filename=source_filename,
        source_mime=source_mime,
        source_size=source_size,
        source_sha256=source_sha256,
        storage_key=storage_key,
        processing_status=processing_status,
        geometry_status=geometry_status,
        source_metadata=dict(source_metadata or {}),
    )
    session.add(revision)
    await session.flush()
    await session.refresh(revision)
    return revision


async def get_revision(
    session: AsyncSession, *, workspace_id: uuid.UUID, revision_id: uuid.UUID
) -> DocumentRevision | None:
    query = (
        select(DocumentRevision)
        .join(Document, DocumentRevision.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(DocumentRevision.id == revision_id, Project.workspace_id == workspace_id)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def find_revision_by_hash(
    session: AsyncSession, *, document_id: uuid.UUID, source_sha256: str
) -> DocumentRevision | None:
    """Тот же файл в том же документе — та же ревизия. Основа идемпотентности загрузки."""
    query = select(DocumentRevision).where(
        DocumentRevision.document_id == document_id,
        DocumentRevision.source_sha256 == source_sha256,
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_revisions(
    session: AsyncSession, *, document_id: uuid.UUID, limit: int, offset: int
) -> list[DocumentRevision]:
    query = (
        select(DocumentRevision)
        .where(DocumentRevision.document_id == document_id)
        .order_by(DocumentRevision.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_revisions(session: AsyncSession, *, document_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(DocumentRevision)
        .where(DocumentRevision.document_id == document_id)
    )
    return int(result.scalar_one())


async def set_processing_status(
    session: AsyncSession,
    *,
    revision: DocumentRevision,
    status: ProcessingStatus,
    error_code: str | None = None,
) -> DocumentRevision:
    """Единственное допустимое изменение ревизии: ход её обработки (ADR-0003)."""
    revision.processing_status = status
    revision.processing_error_code = error_code
    await session.flush()
    return revision


# --------------------------------------------------------------------------- артефакты


async def list_artifacts(
    session: AsyncSession, *, revision_id: uuid.UUID
) -> list[RecognitionArtifact]:
    query = (
        select(RecognitionArtifact)
        .where(RecognitionArtifact.revision_id == revision_id)
        .order_by(RecognitionArtifact.created_at.asc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())


# --------------------------------------------------------------------------- листы


async def list_sheets(
    session: AsyncSession, *, revision_id: uuid.UUID, limit: int, offset: int
) -> list[SheetWithCount]:
    """Листы со счётчиком областей — одним запросом, без обхода связей по каждому листу."""
    region_count = (
        select(func.count(Region.id))
        .where(Region.sheet_id == Sheet.id)
        .correlate(Sheet)
        .scalar_subquery()
    )
    query = (
        select(Sheet, region_count)
        .where(Sheet.revision_id == revision_id)
        .order_by(Sheet.page_index.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return [SheetWithCount(sheet=sheet, region_count=count) for sheet, count in result.all()]


async def count_sheets(session: AsyncSession, *, revision_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Sheet).where(Sheet.revision_id == revision_id)
    )
    return int(result.scalar_one())


async def get_sheet(
    session: AsyncSession, *, workspace_id: uuid.UUID, sheet_id: uuid.UUID
) -> Sheet | None:
    query = (
        select(Sheet)
        .join(DocumentRevision, Sheet.revision_id == DocumentRevision.id)
        .join(Document, DocumentRevision.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(Sheet.id == sheet_id, Project.workspace_id == workspace_id)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------- области


async def list_regions(
    session: AsyncSession,
    *,
    sheet_id: uuid.UUID,
    limit: int,
    offset: int,
    block_type: str | None = None,
    recognition_status: str | None = None,
) -> list[Region]:
    query = select(Region).where(Region.sheet_id == sheet_id)
    if block_type:
        query = query.where(Region.block_type == block_type)
    if recognition_status:
        query = query.where(Region.recognition_status == recognition_status)
    query = query.order_by(Region.ordinal.asc().nullslast(), Region.external_block_id.asc())
    result = await session.execute(query.limit(limit).offset(offset))
    return list(result.scalars().all())


async def count_regions(
    session: AsyncSession,
    *,
    sheet_id: uuid.UUID,
    block_type: str | None = None,
    recognition_status: str | None = None,
) -> int:
    query = select(func.count()).select_from(Region).where(Region.sheet_id == sheet_id)
    if block_type:
        query = query.where(Region.block_type == block_type)
    if recognition_status:
        query = query.where(Region.recognition_status == recognition_status)
    result = await session.execute(query)
    return int(result.scalar_one())
