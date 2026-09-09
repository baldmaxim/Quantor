"""Извлечение канонической геометрии страниц ревизии PDF.

Два сценария сходятся в одну операцию (ADR-0016):

```text
обычная загрузка PDF   листов нет  → задание создаёт их из страниц
импорт legacy-пакета   листы есть  → задание их обогащает
```

Идентификаторы листов детерминированы одной формулой, поэтому это upsert, а не две ветки
с разной логикой. Повторный запуск не плодит дубликаты.

Главный инвариант: геометрия либо извлечена для всех страниц ревизии, либо не извлечена
вовсе. При расхождении числа страниц доверять нельзя ни одной, поэтому отказ откатывает
всё, а не оставляет половину.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain import COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT, GeometryStatus
from app.errors import DomainError, ErrorCode
from app.models import DocumentRevision, PageGeometry, Sheet
from app.services.geometry.provider import PageGeometryProvider, RawPageGeometry
from app.storage.base import ObjectStorage
from app.storage.s3 import CHUNK_SIZE

log = get_logger(__name__)

# То же пространство имён, что у импортёра: идентификаторы листов обязаны совпасть,
# иначе задание создало бы второй лист рядом с уже существующим.
_NAMESPACE: Final = uuid.UUID("6b0b8a2e-1f34-4d0a-9a3f-5b2d7f6c8e10")


def sheet_id_for(revision_id: uuid.UUID, page_index: int) -> uuid.UUID:
    """Детерминированный идентификатор листа.

    Формула повторяет `legacy.importer._sheet_id` дословно и намеренно: обогащение
    существующего листа и создание нового — это одна операция, а не две.
    """
    return uuid.uuid5(_NAMESPACE, f"{revision_id}:sheet:{page_index}")


@dataclass(frozen=True, slots=True)
class ExtractResult:
    """Итог извлечения — то, что задание записывает в свой payload."""

    revision_id: uuid.UUID
    page_count: int
    sheets_created: int
    sheets_enriched: int
    parser_name: str
    parser_version: str


def idempotency_key(revision_id: uuid.UUID, provider: PageGeometryProvider) -> str:
    """Ключ идемпотентности задания.

    Версия парсера входит в ключ намеренно: при её смене геометрия могла измениться, и это
    должно приводить к новому заданию, а не прятаться за идемпотентностью прежнего.
    """
    return f"pdf_geometry:{revision_id}:{provider.name}:{provider.version}"


def fingerprint(page: RawPageGeometry, provider: PageGeometryProvider) -> str:
    """Отпечаток геометрии страницы.

    Отвечает одним сравнением на вопрос «та ли это геометрия, по которой посчитана
    величина». Числа берутся канонической десятичной записью — той же, что лежит в базе:
    у двоичной дроби представление зависит от форматирования, у десятичной оно одно.
    """
    parts = [
        COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT,
        str(page.display_width_pt),
        str(page.display_height_pt),
        str(page.rotation),
        ",".join(str(value) for value in page.media_box),
        ",".join(str(value) for value in page.crop_box),
        provider.name,
        provider.version,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


async def extract_for_revision(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    revision: DocumentRevision,
    provider: PageGeometryProvider,
) -> ExtractResult:
    """Извлекает геометрию всех страниц ревизии и записывает её одной транзакцией."""
    pages = await _read_pages(storage, revision=revision, provider=provider)

    existing = await _existing_sheets(session, revision_id=revision.id)
    _check_page_count(revision=revision, pages=pages, existing=existing)

    extracted_at = datetime.now(UTC)
    created = 0
    enriched = 0

    for page in pages:
        sheet = existing.get(page.page_index)
        if sheet is None:
            sheet = Sheet(
                id=sheet_id_for(revision.id, page.page_index),
                revision_id=revision.id,
                page_index=page.page_index,
                page_label=str(page.page_index + 1),
                # Поворот исходной страницы сохраняется как метаданные источника.
                # К нормализованным координатам он второй раз не применяется (ADR-0008).
                rotation=page.rotation,
            )
            session.add(sheet)
            created += 1
        else:
            # Растровые width_px/height_px и rotation листа из пакета не трогаются:
            # это свидетельство распознавалки, а не факт документа.
            enriched += 1

        await session.flush()
        await _upsert_geometry(
            session,
            sheet_id=sheet.id,
            page=page,
            revision=revision,
            provider=provider,
            extracted_at=extracted_at,
        )

    revision.geometry_status = GeometryStatus.READY
    revision.geometry_error_code = None
    await session.flush()

    return ExtractResult(
        revision_id=revision.id,
        page_count=len(pages),
        sheets_created=created,
        sheets_enriched=enriched,
        parser_name=provider.name,
        parser_version=provider.version,
    )


async def _read_pages(
    storage: ObjectStorage,
    *,
    revision: DocumentRevision,
    provider: PageGeometryProvider,
) -> list[RawPageGeometry]:
    """Скачивает PDF во временный файл и читает страницы.

    Файл читается кусками и в память целиком не попадает: полтерабайта проектной
    документации там делать нечего. Временный каталог удаляется даже при исключении.
    """
    import asyncio

    with tempfile.TemporaryDirectory(prefix="quantor-geometry-") as workdir:
        path = Path(workdir) / "source.pdf"
        with path.open("wb") as output:
            async for chunk in storage.iter_stream(revision.storage_key, chunk_size=CHUNK_SIZE):
                output.write(chunk)

        # Разбор синхронный и на большом документе небыстрый: держать на нём цикл
        # событий нельзя — воркер перестал бы слать пульс и потерял бы аренду.
        return await asyncio.to_thread(provider.read, path)


async def _existing_sheets(session: AsyncSession, *, revision_id: uuid.UUID) -> dict[int, Sheet]:
    result = await session.execute(select(Sheet).where(Sheet.revision_id == revision_id))
    return {sheet.page_index: sheet for sheet in result.scalars().all()}


def _check_page_count(
    *,
    revision: DocumentRevision,
    pages: list[RawPageGeometry],
    existing: dict[int, Sheet],
) -> None:
    """Сверяет число страниц с уже существующими листами.

    Расхождение — отказ целиком. Записать геометрию для совпавших страниц и оставить
    остальные без неё значило бы получить документ, часть которого меряется, а часть нет,
    причём молча.
    """
    if not existing:
        return

    if len(existing) != len(pages):
        raise DomainError(
            ErrorCode.PDF_PAGE_COUNT_MISMATCH,
            f"В PDF {len(pages)} страниц, а у ревизии {len(existing)} листов",
        )

    missing = sorted(set(existing) - {page.page_index for page in pages})
    if missing:
        raise DomainError(
            ErrorCode.PDF_PAGE_COUNT_MISMATCH,
            f"Номера страниц не совпадают: у ревизии есть листы {missing}, в PDF их нет",
        )

    declared = revision.source_metadata.get("page_count")
    if isinstance(declared, int) and declared != len(pages):
        raise DomainError(
            ErrorCode.PDF_PAGE_COUNT_MISMATCH,
            f"Пакет объявил {declared} страниц, в PDF их {len(pages)}",
        )


async def _upsert_geometry(
    session: AsyncSession,
    *,
    sheet_id: uuid.UUID,
    page: RawPageGeometry,
    revision: DocumentRevision,
    provider: PageGeometryProvider,
    extracted_at: datetime,
) -> None:
    """Записывает геометрию страницы, заменяя прежнюю.

    Замена, а не вторая строка: у листа одна геометрия, и на это стоит уникальный индекс.
    Переизвлечение другой версией парсера должно давать новый результат, а не спор двух.
    """
    found = await session.execute(select(PageGeometry).where(PageGeometry.sheet_id == sheet_id))
    geometry = found.scalar_one_or_none()

    values = {
        "coordinate_space": COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT,
        "display_width_pt": page.display_width_pt,
        "display_height_pt": page.display_height_pt,
        "pdf_rotation": page.rotation,
        "media_box": [str(value) for value in page.media_box],
        "crop_box": [str(value) for value in page.crop_box],
        "parser_name": provider.name,
        "parser_version": provider.version,
        "source_sha256": revision.source_sha256,
        "geometry_fingerprint": fingerprint(page, provider),
        "extracted_at": extracted_at,
    }

    if geometry is None:
        session.add(PageGeometry(sheet_id=sheet_id, **values))
        return

    for field, value in values.items():
        setattr(geometry, field, value)


def to_decimal(value: object) -> Decimal:
    """Приводит хранимое значение к Decimal.

    Граница «из базы в расчёт» проходит здесь: дальше по коду геометрия — это Decimal,
    а не строка и не float (ADR-0016).
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
