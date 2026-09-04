"""Импорт распознанного пакета.

Единственная часть портала, которая понимает текущий формат распознавалки. Она не
распознаёт заново: её задача — открыть уже распознанный проект (ADR-0007).

Что получается на выходе:

```text
Document(recognized_package)          загруженный архив, неизменяемый источник
  └── DocumentRevision → ZIP в хранилище
Document(pdf)                         то, что открывает просмотрщик
  └── DocumentRevision → PDF, извлечённый из архива
        ├── Sheet × числу страниц
        ├── Region × числу областей
        └── RecognitionArtifact: blocks.json, results.md, results.html
```

Импорт идемпотентен: идентификаторы производных объектов детерминированно выводятся из
идентификатора ревизии пакета, поэтому повторный запуск не создаёт вторую копию, а
завершается сразу.
"""

from __future__ import annotations

import asyncio
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import (
    COORDINATE_SPACE_NORMALIZED_TOP_LEFT,
    ArtifactKind,
    DocumentKind,
    ProcessingStatus,
    RegionShape,
)
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, Project, RecognitionArtifact, Region, Sheet
from app.services import documents as documents_service
from app.services.legacy import archive as archive_reader
from app.services.legacy import markdown, package
from app.services.legacy.archive import ArchiveLimits, ArchiveMember
from app.storage.base import ObjectStorage
from app.storage.keys import artifact_key, revision_key
from app.storage.s3 import CHUNK_SIZE

log = get_logger(__name__)

# Пространство имён для детерминированных идентификаторов производных объектов.
# Постоянное: от него зависит идемпотентность повторного импорта.
_NAMESPACE: Final = uuid.UUID("6b0b8a2e-1f34-4d0a-9a3f-5b2d7f6c8e10")

# Артефакты пакета читаются целиком, поэтому у них отдельный, более скромный предел.
MAX_ARTIFACT_BYTES: Final = 64 * 1024 * 1024

ARTIFACT_KINDS: Final[dict[str, ArtifactKind]] = {
    package.BLOCKS_SUFFIX: ArtifactKind.BLOCKS_JSON,
    package.RESULTS_MD_SUFFIX: ArtifactKind.RESULTS_MD,
    package.RESULTS_HTML_SUFFIX: ArtifactKind.RESULTS_HTML,
}

ARTIFACT_CONTENT_TYPES: Final[dict[ArtifactKind, str]] = {
    ArtifactKind.BLOCKS_JSON: "application/json",
    ArtifactKind.RESULTS_MD: "text/markdown; charset=utf-8",
    # Не text/html: этот файл нигде не отображается как разметка и хранится как данные.
    ArtifactKind.RESULTS_HTML: "application/octet-stream",
}


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Итог импорта — то, что задание записывает в свой payload."""

    document_id: uuid.UUID
    revision_id: uuid.UUID
    sheet_count: int
    region_count: int
    artifact_count: int
    already_imported: bool


def derived_document_id(package_revision_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{package_revision_id}:document")


def derived_revision_id(package_revision_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{package_revision_id}:revision")


def _sheet_id(revision_id: uuid.UUID, page_index: int) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{revision_id}:sheet:{page_index}")


def _region_id(revision_id: uuid.UUID, block_id: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{revision_id}:region:{block_id}")


def _artifact_id(revision_id: uuid.UUID, kind: ArtifactKind) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{revision_id}:artifact:{kind.value}")


def limits_from(settings: Settings) -> ArchiveLimits:
    return ArchiveLimits(
        max_files=settings.archive_max_files,
        max_total_uncompressed_bytes=settings.archive_max_total_bytes,
        max_file_bytes=settings.archive_max_file_bytes,
        max_compression_ratio=settings.archive_max_compression_ratio,
    )


async def import_package(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    package_revision: DocumentRevision,
    project: Project,
    settings: Settings,
) -> ImportResult:
    """Разбирает архив и создаёт граф объектов проекта.

    Ничего не выполняется до того, как архив признан безопасным: сначала проверки по
    оглавлению, затем чтение.
    """
    revision_id = derived_revision_id(package_revision.id)

    existing = await session.get(DocumentRevision, revision_id)
    if existing is not None:
        return ImportResult(
            document_id=existing.document_id,
            revision_id=existing.id,
            sheet_count=await _count_sheets(session, revision_id),
            region_count=await _count_regions(session, revision_id),
            artifact_count=await _count_artifacts(session, revision_id),
            already_imported=True,
        )

    with tempfile.TemporaryDirectory(prefix="quantor-import-") as workdir:
        archive_path = Path(workdir) / "package.zip"
        await _download(storage, package_revision.storage_key, archive_path)

        layout, blocks, sections = await asyncio.to_thread(
            _read_archive, archive_path, limits_from(settings)
        )

        pdf_path = Path(workdir) / "source.pdf"
        await asyncio.to_thread(_extract_member, archive_path, layout.pdf, pdf_path, settings)

        return await _persist(
            session,
            storage,
            project=project,
            package_revision=package_revision,
            revision_id=revision_id,
            pdf_path=pdf_path,
            pdf_name=Path(layout.pdf.name).name,
            blocks=blocks,
            sections=sections,
            layout=layout,
            archive_path=archive_path,
        )


def _read_archive(
    archive_path: Path, limits: ArchiveLimits
) -> tuple[package.PackageLayout, package.BlocksDocument, dict[str, str]]:
    """Синхронная часть: проверка архива и разбор его текстовых файлов.

    Выполняется в отдельном потоке — zipfile блокирующий, и держать на нём цикл событий
    во время разбора пятидесятимегабайтного пакета нельзя.
    """
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive_reader.inspect(archive, limits)
            layout = package.locate(members)

            blocks_raw = archive_reader.read_member(
                archive, layout.blocks, max_bytes=MAX_ARTIFACT_BYTES
            )
            blocks = package.parse_blocks(blocks_raw)

            sections: dict[str, str] = {}
            if layout.results_md is not None:
                md_raw = archive_reader.read_member(
                    archive, layout.results_md, max_bytes=MAX_ARTIFACT_BYTES
                )
                sections = markdown.index_sections(markdown.decode(md_raw))
    except zipfile.BadZipFile as error:
        raise DomainError(ErrorCode.CORRUPT_ARCHIVE, "Файл не является корректным ZIP") from error

    return layout, blocks, sections


def _extract_member(
    archive_path: Path, member: ArchiveMember, target: Path, settings: Settings
) -> None:
    """Извлекает файл архива на диск кусками, не собирая его в памяти."""
    with zipfile.ZipFile(archive_path) as archive, target.open("wb") as output:
        for chunk in archive_reader.iter_member(
            archive, member, chunk_size=CHUNK_SIZE, max_bytes=settings.archive_max_file_bytes
        ):
            output.write(chunk)


async def _download(storage: ObjectStorage, key: str, target: Path) -> None:
    """Скачивает архив из хранилища на диск. В память он не помещается и не должен."""
    with target.open("wb") as output:
        async for chunk in storage.iter_stream(key, chunk_size=CHUNK_SIZE):
            output.write(chunk)


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_SIZE):
            yield chunk


async def _persist(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project: Project,
    package_revision: DocumentRevision,
    revision_id: uuid.UUID,
    pdf_path: Path,
    pdf_name: str,
    blocks: package.BlocksDocument,
    sections: dict[str, str],
    layout: package.PackageLayout,
    archive_path: Path,
) -> ImportResult:
    """Создаёт документ, ревизию, листы, области и артефакты.

    Всё в одной транзакции: наполовину видимый проект хуже, чем неудавшийся импорт.
    """
    pdf_key = revision_key(revision_id, pdf_name)
    stored_pdf = await storage.put_stream(
        pdf_key,
        _file_chunks(pdf_path),
        content_type="application/pdf",
        original_filename=pdf_name,
        metadata={"project-id": str(project.id)},
    )

    document = Document(
        id=derived_document_id(package_revision.id),
        project_id=project.id,
        display_name=pdf_name,
        document_kind=DocumentKind.PDF,
    )
    session.add(document)

    revision = DocumentRevision(
        id=revision_id,
        document_id=document.id,
        source_filename=pdf_name,
        source_mime="application/pdf",
        source_size=stored_pdf.size,
        source_sha256=stored_pdf.sha256,
        storage_key=pdf_key,
        processing_status=ProcessingStatus.READY,
        source_metadata={
            "package_format": "recognized-package/legacy-v1",
            "schema_version": blocks.schema_version,
            "coordinate_space": COORDINATE_SPACE_NORMALIZED_TOP_LEFT,
            "page_count": len(blocks.pages),
            "block_count": len(blocks.blocks),
            # Происхождение: по этой ссылке видно, из какого архива получен документ.
            "imported_from_revision_id": str(package_revision.id),
            "package_sha256": package_revision.source_sha256,
        },
    )
    session.add(revision)
    await session.flush()

    sheets_by_index: dict[int, uuid.UUID] = {}
    for page in blocks.pages:
        sheet_id = _sheet_id(revision_id, page.page_index)
        sheets_by_index[page.page_index] = sheet_id
        session.add(
            Sheet(
                id=sheet_id,
                revision_id=revision_id,
                page_index=page.page_index,
                page_label=str(page.page_index + 1),
                width_px=page.width_px,
                height_px=page.height_px,
                rotation=page.rotation,
            )
        )
    await session.flush()

    for block in blocks.blocks:
        session.add(
            Region(
                id=_region_id(revision_id, block.block_id),
                sheet_id=sheets_by_index[block.page_index],
                external_block_id=block.block_id,
                ordinal=block.ordinal,
                block_type=block.block_type,
                shape_type=block.shape_type,
                coords_norm=block.coords_norm,
                polygon_points=block.polygon_points
                if block.shape_type is RegionShape.POLYGON
                else None,
                recognition_status=block.status,
                # Сырой текст секции сохраняется как есть: семантику Summary/Description
                # разбирать на этом этапе нельзя — формат ещё изменится.
                raw_content_md=sections.get(block.block_id),
                legacy_metadata=block.legacy_metadata,
            )
        )

    artifact_count = await _store_artifacts(
        session, storage, revision_id=revision_id, layout=layout, archive_path=archive_path
    )

    await documents_service.set_processing_status(
        session, revision=package_revision, status=ProcessingStatus.READY
    )
    await session.flush()

    return ImportResult(
        document_id=document.id,
        revision_id=revision_id,
        sheet_count=len(blocks.pages),
        region_count=len(blocks.blocks),
        artifact_count=artifact_count,
        already_imported=False,
    )


async def _store_artifacts(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    revision_id: uuid.UUID,
    layout: package.PackageLayout,
    archive_path: Path,
) -> int:
    """Сохраняет файлы пакета как артефакты с контрольными суммами.

    results.html хранится, но источником правды не является и как разметка не отображается.
    """
    candidates: list[tuple[ArchiveMember, ArtifactKind]] = [
        (layout.blocks, ArtifactKind.BLOCKS_JSON)
    ]
    if layout.results_md is not None:
        candidates.append((layout.results_md, ArtifactKind.RESULTS_MD))
    if layout.results_html is not None:
        candidates.append((layout.results_html, ArtifactKind.RESULTS_HTML))

    for member, kind in candidates:
        payload = await asyncio.to_thread(_read_bytes, archive_path, member)
        artifact_id = _artifact_id(revision_id, kind)
        key = artifact_key(revision_id, artifact_id, member.name)
        stored = await storage.put_bytes(
            key,
            payload,
            content_type=ARTIFACT_CONTENT_TYPES[kind],
            original_filename=Path(member.name).name,
        )
        session.add(
            RecognitionArtifact(
                id=artifact_id,
                revision_id=revision_id,
                artifact_kind=kind,
                schema_version=1 if kind is ArtifactKind.BLOCKS_JSON else None,
                sha256=stored.sha256,
                storage_key=key,
                source_filename=Path(member.name).name,
                artifact_metadata={"size": stored.size},
            )
        )

    return len(candidates)


def _read_bytes(archive_path: Path, member: ArchiveMember) -> bytes:
    with zipfile.ZipFile(archive_path) as archive:
        return archive_reader.read_member(archive, member, max_bytes=MAX_ARTIFACT_BYTES)


async def _count_sheets(session: AsyncSession, revision_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Sheet).where(Sheet.revision_id == revision_id)
    )
    return int(result.scalar_one())


async def _count_artifacts(session: AsyncSession, revision_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(RecognitionArtifact)
        .where(RecognitionArtifact.revision_id == revision_id)
    )
    return int(result.scalar_one())


async def _count_regions(session: AsyncSession, revision_id: uuid.UUID) -> int:
    query = (
        select(func.count())
        .select_from(Region)
        .join(Sheet, Region.sheet_id == Sheet.id)
        .where(Sheet.revision_id == revision_id)
    )
    result = await session.execute(query)
    return int(result.scalar_one())
