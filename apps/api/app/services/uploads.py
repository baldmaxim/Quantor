"""Приём файлов.

Загрузка на этом этапе — это доставка неизменяемого файла в хранилище и создание записей
о нём. Никакого распознавания здесь нет: пакет только ставится в очередь на импорт (промт 06).

Три правила, вокруг которых построен модуль:

1. Память не зависит от размера файла: содержимое читается кусками и сразу уходит в хранилище.
2. Тип определяется по содержимому, а не по расширению: расширение подделывается тривиально.
3. Повторная загрузка того же файла не создаёт вторую ревизию — сравнение идёт по SHA-256.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import DocumentKind, JobType, ProcessingStatus
from app.errors import DomainError, ErrorCode, InvariantError
from app.models import Document, DocumentRevision, Job, Project
from app.services import documents as documents_service
from app.services import jobs as jobs_service
from app.storage.base import ObjectStorage
from app.storage.keys import display_filename, extension_of, revision_key

# Размер куска при чтении тела запроса.
CHUNK_SIZE: Final = 1024 * 1024

# Сигнатуры содержимого. Расширению не доверяем: и `.pdf`, и `.zip` подделываются переименованием.
PDF_MAGIC: Final = b"%PDF-"
ZIP_MAGIC: Final = b"PK\x03\x04"
# Пустой и однофайловый архивы имеют другие сигнатуры, но валидными пакетами не являются.
ZIP_EMPTY_MAGIC: Final = b"PK\x05\x06"
ZIP_SPANNED_MAGIC: Final = b"PK\x07\x08"


@dataclass(frozen=True, slots=True)
class FileKind:
    """Что портал делает с файлом такого типа."""

    document_kind: DocumentKind
    processing_status: ProcessingStatus
    content_type: str
    # Ставится ли в очередь импорт распознанного пакета.
    schedules_import: bool
    # Текст для интерфейса: честно говорит, что произойдёт с файлом.
    capability: str


# Пакет распознавалки — единственный тип, который портал сейчас умеет разбирать.
RECOGNIZED_PACKAGE = FileKind(
    document_kind=DocumentKind.RECOGNIZED_PACKAGE,
    processing_status=ProcessingStatus.PENDING,
    content_type="application/zip",
    schedules_import=True,
    capability="Импортировать",
)
RAW_PDF = FileKind(
    document_kind=DocumentKind.PDF,
    processing_status=ProcessingStatus.UNPROCESSED,
    content_type="application/pdf",
    schedules_import=False,
    capability="Сохранить, распознавание будет на следующем этапе",
)


def _bim(kind: DocumentKind, content_type: str) -> FileKind:
    return FileKind(
        document_kind=kind,
        processing_status=ProcessingStatus.PROCESSOR_UNAVAILABLE,
        content_type=content_type,
        schedules_import=False,
        capability="Сохранить, обработчик пока не подключён",
    )


# Модели BIM принимаются на хранение неизменно, но не разбираются (ADR-0002, CLAUDE.md).
SUPPORTED_EXTENSIONS: Final[dict[str, FileKind]] = {
    "zip": RECOGNIZED_PACKAGE,
    "pdf": RAW_PDF,
    "rvt": _bim(DocumentKind.REVIT, "application/octet-stream"),
    "nwd": _bim(DocumentKind.NAVISWORKS, "application/octet-stream"),
    "nwc": _bim(DocumentKind.NAVISWORKS, "application/octet-stream"),
    "ifc": _bim(DocumentKind.IFC, "application/octet-stream"),
}


@dataclass(frozen=True, slots=True)
class UploadOutcome:
    """Результат приёма файла."""

    document: Document
    revision: DocumentRevision
    job: Job | None
    # True, если такой файл уже был загружен и создана не новая, а найдена прежняя ревизия.
    is_duplicate: bool


def classify(filename: str) -> FileKind:
    """Определяет, что делать с файлом, по расширению. Содержимое проверяется отдельно."""
    extension = extension_of(filename)
    kind = SUPPORTED_EXTENSIONS.get(extension)
    if kind is None:
        raise DomainError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            "Поддерживаются ZIP-пакет распознавалки, PDF, а также RVT, NWD, NWC и IFC на хранение",
        )
    return kind


def verify_signature(head: bytes, kind: FileKind) -> None:
    """Сверяет начало файла с объявленным типом.

    Проверяются только те форматы, у которых сигнатура однозначна. Для BIM-моделей проверки
    нет: разбирать их портал всё равно не будет, а сигнатуры у них разные и плохо
    документированы.
    """
    if kind is RECOGNIZED_PACKAGE:
        if head.startswith((ZIP_EMPTY_MAGIC, ZIP_SPANNED_MAGIC)):
            raise DomainError(
                ErrorCode.CORRUPT_ARCHIVE,
                "Архив пуст или разбит на части — такой пакет не подходит",
            )
        if not head.startswith(ZIP_MAGIC):
            raise DomainError(
                ErrorCode.MIME_MISMATCH, "Файл с расширением .zip не является ZIP-архивом"
            )
    elif kind is RAW_PDF and not head.startswith(PDF_MAGIC):
        raise DomainError(ErrorCode.MIME_MISMATCH, "Файл с расширением .pdf не является PDF")


async def limit_stream(chunks: AsyncIterator[bytes], *, max_size: int) -> AsyncIterator[bytes]:
    """Пропускает поток через себя и обрывает его, как только превышен предел размера.

    Проверять размер после загрузки поздно: файл уже занял место в хранилище, а процесс —
    время. Заголовок Content-Length подделывается, поэтому считаем фактические байты.
    """
    received = 0
    async for chunk in chunks:
        received += len(chunk)
        if received > max_size:
            raise DomainError(
                ErrorCode.UPLOAD_TOO_LARGE,
                f"Файл больше допустимых {max_size // (1024 * 1024)} МБ",
            )
        yield chunk


async def find_project_revision_by_hash(
    session: AsyncSession, *, project_id: uuid.UUID, source_sha256: str
) -> DocumentRevision | None:
    """Ищет уже загруженный такой же файл в пределах проекта."""
    query = (
        select(DocumentRevision)
        .join(Document, DocumentRevision.document_id == Document.id)
        .where(Document.project_id == project_id, DocumentRevision.source_sha256 == source_sha256)
        .order_by(DocumentRevision.created_at.asc())
        .limit(1)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def receive_upload(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project: Project,
    filename: str,
    chunks: AsyncIterator[bytes],
    max_size: int,
    document: Document | None = None,
) -> UploadOutcome:
    """Принимает файл: проверка, потоковая запись в хранилище, записи в базе.

    Идентификатор ревизии выбирается заранее, чтобы файл сразу лёг по своему окончательному
    ключу. Если после загрузки выяснится, что такой файл уже есть, объект удаляется,
    а возвращается прежняя ревизия — повтор не должен плодить копии.
    """
    display_name = display_filename(filename)
    kind = classify(display_name)

    revision_id = uuid.uuid4()
    key = revision_key(revision_id, display_name)

    stored = await storage.put_stream(
        key,
        _verified(chunks, kind=kind, max_size=max_size),
        content_type=kind.content_type,
        original_filename=display_name,
        metadata={"project-id": str(project.id)},
    )

    if stored.size == 0:
        await storage.delete(key)
        raise DomainError(ErrorCode.EMPTY_FILE, "Файл пуст")

    existing = await find_project_revision_by_hash(
        session, project_id=project.id, source_sha256=stored.sha256
    )
    if existing is not None:
        await storage.delete(key)
        existing_document = await session.get(Document, existing.document_id)
        if existing_document is None:
            raise InvariantError(f"ревизия {existing.id} осталась без документа")
        existing_job = await jobs_service.find_by_idempotency_key(
            session, idempotency_key=_import_key(project.id, stored.sha256)
        )
        return UploadOutcome(
            document=existing_document, revision=existing, job=existing_job, is_duplicate=True
        )

    target = document or await documents_service.create_document(
        session,
        project=project,
        display_name=display_name,
        document_kind=kind.document_kind,
    )

    revision = await documents_service.create_revision(
        session,
        document=target,
        revision_id=revision_id,
        source_filename=display_name,
        source_mime=kind.content_type,
        source_size=stored.size,
        source_sha256=stored.sha256,
        storage_key=key,
        processing_status=kind.processing_status,
    )

    job: Job | None = None
    if kind.schedules_import:
        # Ключ идемпотентности из хэша пакета: повторная загрузка не запустит второй импорт.
        job = await jobs_service.enqueue(
            session,
            job_type=JobType.LEGACY_IMPORT,
            workspace_id=project.workspace_id,
            project_id=project.id,
            idempotency_key=_import_key(project.id, stored.sha256),
            payload={"revision_id": str(revision.id)},
        )

    return UploadOutcome(document=target, revision=revision, job=job, is_duplicate=False)


def _import_key(project_id: uuid.UUID, sha256: str) -> str:
    return f"legacy_import:{project_id}:{sha256}"


async def _verified(
    chunks: AsyncIterator[bytes], *, kind: FileKind, max_size: int
) -> AsyncIterator[bytes]:
    """Сверяет сигнатуру по первому куску и дальше просто пропускает поток."""
    limited = limit_stream(chunks, max_size=max_size)
    head_checked = False
    async for chunk in limited:
        if not head_checked and chunk:
            verify_signature(chunk[:8], kind)
            head_checked = True
        yield chunk
