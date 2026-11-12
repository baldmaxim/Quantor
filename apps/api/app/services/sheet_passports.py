"""Паспорт листа (ADR-0043, С1): задание разбора комплекта, хранение и правка кандидатов.

Кандидата собирает исполнитель по текстовому слою PDF (pypdf, без OCR и растра); подтверждает
человек. Тот же проход сохраняет текст страниц ревизии в хранилище (В1, `page_texts`). Поле,
которое правил человек (`evidence.source == "manual"`), повторный разбор не трогает;
подтверждённый и отклонённый паспорт не перезаписывается вовсе. Доступ к проекту
проверяет вызывающий.
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.sheet_passports import (
    PASSPORT_FIELDS,
    FieldEvidenceOut,
    SheetPassportExtractError,
    SheetPassportExtractSummary,
    SheetPassportOut,
    SheetPassportPatch,
    SheetPassportStatus,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import DocumentKind, JobStatus, JobType
from app.errors import ErrorCode, not_found
from app.models import (
    Document,
    DocumentRevision,
    Job,
    Project,
    RevisionPageText,
    SheetPassport,
)
from app.services import jobs as jobs_service
from app.services.consistency.page_texts import (
    PAGE_TEXT_FORMAT,
    REASON_STORE_FAILED,
    StoredPageText,
    store_page_text_file,
)
from app.services.consistency.passport_process import (
    PassportParseError,
    parse_pdf_in_subprocess,
)
from app.services.consistency.sheet_passport import (
    PARSER_VERSION,
    EvidenceSource,
    PassportCandidate,
    dictionary_versions,
)
from app.storage.base import ObjectNotFoundError, ObjectStorage

log = get_logger(__name__)

CHUNK_SIZE: Final = 1024 * 1024
MAX_REPORTED_ERRORS: Final = 50
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


# --------------------------------------------------------------------------- постановка


async def schedule_extract(session: AsyncSession, *, project: Project) -> Job:
    """Ставит задание разбора проекта; уже есть активное - возвращает его.

    Строка проекта берётся под блокировкой: два нажатия подряд не ставят задание дважды.
    """
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    active = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.SHEET_PASSPORT_EXTRACT,
            Job.project_id == project.id,
            Job.status.in_(_ACTIVE),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return active
    return await jobs_service.enqueue(
        session,
        job_type=JobType.SHEET_PASSPORT_EXTRACT,
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )


# --------------------------------------------------------------------------- исполнитель


def _no_nul(text: str) -> str:
    """PostgreSQL не принимает 0x00 ни в text, ни в jsonb."""
    return text.replace("\x00", "")


def _evidence_to_json(candidate: PassportCandidate) -> dict[str, dict[str, str]]:
    return {
        name: {"source": item.source.value, "snippet": _no_nul(item.snippet)}
        for name, item in candidate.evidence.items()
    }


def _field_value(candidate: PassportCandidate, name: str) -> object:
    value = getattr(candidate, name)
    # SheetKind - StrEnum, в базу идёт значением.
    value = value.value if hasattr(value, "value") else value
    return _no_nul(value) if isinstance(value, str) else value


def _fill_row(row: SheetPassport, candidate: PassportCandidate, file_name: str) -> None:
    """Перезаписывает кандидата, кроме полей, правленных человеком."""
    evidence: dict[str, Any] = dict(row.evidence)
    fresh = _evidence_to_json(candidate)
    for name in PASSPORT_FIELDS:
        current = evidence.get(name)
        if isinstance(current, dict) and current.get("source") == EvidenceSource.MANUAL.value:
            continue
        setattr(row, name, _field_value(candidate, name))
        if name in fresh:
            evidence[name] = fresh[name]
        else:
            evidence.pop(name, None)
    row.evidence = evidence
    row.file_name = _no_nul(file_name)
    row.versions = dictionary_versions()


async def _upsert_candidates(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    file_name: str,
    candidates: list[PassportCandidate],
) -> tuple[int, int, int]:
    """Записывает страницы файла; возвращает (создано, обновлено, пропущено)."""
    rows = await session.scalars(
        select(SheetPassport)
        .where(SheetPassport.revision_id == revision_id)
        .execution_options(populate_existing=True)
    )
    existing = {row.page_index: row for row in rows}
    created = updated = skipped = 0
    for candidate in candidates:
        row = existing.get(candidate.page_index)
        if row is None:
            row = SheetPassport(
                project_id=project_id,
                revision_id=revision_id,
                page_index=candidate.page_index,
                file_name=file_name,
                status=SheetPassportStatus.CANDIDATE.value,
                evidence={},
                versions={},
            )
            _fill_row(row, candidate, file_name)
            session.add(row)
            created += 1
        elif row.status != SheetPassportStatus.CANDIDATE.value:
            skipped += 1
        else:
            _fill_row(row, candidate, file_name)
            updated += 1
    await session.flush()
    return created, updated, skipped


@dataclass(frozen=True, slots=True)
class _ParsedFile:
    """Разобранный файл: кандидаты и выгруженный текст (None - выгрузка не удалась)."""

    candidates: list[PassportCandidate]
    text: StoredPageText | None


async def _upsert_page_text(
    session: AsyncSession, *, project_id: uuid.UUID, revision_id: uuid.UUID, stored: StoredPageText
) -> None:
    """Строка указателя на текст ревизии; повторный разбор перезаписывает её."""
    values = {
        "project_id": project_id,
        "storage_key": stored.storage_key,
        "format": stored.format,
        "parser_version": stored.parser_version,
        "pages": stored.pages,
        "empty_pages": stored.empty_pages,
        "size_bytes": stored.size_bytes,
        "sha256": stored.sha256,
    }
    statement = pg_insert(RevisionPageText).values(revision_id=revision_id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[RevisionPageText.revision_id],
            set_={**values, "created_at": func.now()},
        )
    )


async def _download_and_parse(
    storage: ObjectStorage,
    *,
    storage_key: str,
    file_name: str,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    settings: Settings,
) -> _ParsedFile:
    """Файл потоково во временный файл на диске (ADR-0002), разбор - в подпроцессе с пределами.

    Текст страниц выгружается в хранилище, пока жив временный каталог. Сбой выгрузки не
    отнимает кандидатов: `text` остаётся None, и повторный запуск доделает текст.
    """
    with tempfile.TemporaryDirectory(prefix="quantor-passport-") as workdir:
        path = Path(workdir) / "source.pdf"
        with path.open("wb") as output:
            async for chunk in storage.iter_stream(storage_key, chunk_size=CHUNK_SIZE):
                output.write(chunk)
        parsed = await parse_pdf_in_subprocess(
            path,
            file_name,
            memory_limit_mb=settings.sheet_passport_parse_memory_mb,
            timeout_seconds=settings.sheet_passport_parse_timeout_seconds,
        )
        try:
            stored: StoredPageText | None = await store_page_text_file(
                storage,
                project_id=project_id,
                revision_id=revision_id,
                path=parsed.text_path,
                parser_version=PARSER_VERSION,
                max_bytes=settings.sheet_passport_page_text_max_mb * 1024 * 1024,
            )
        except Exception as error:
            stored = None
            log.warning(
                "sheet_passport_page_text_failed",
                revision_id=str(revision_id),
                reason=type(error).__name__,
            )
        return _ParsedFile(candidates=parsed.candidates, text=stored)


async def _already_parsed(session: AsyncSession, revision_id: uuid.UUID) -> bool:
    """Паспорта разобраны текущей версией разборщика и текст страниц сохранён: файл не качаем."""
    versions = await session.scalars(
        select(SheetPassport.versions).where(SheetPassport.revision_id == revision_id)
    )
    parsers = [item.get("parser") for item in versions]
    if not parsers or any(parser != PARSER_VERSION for parser in parsers):
        return False
    stored = await session.scalar(
        select(RevisionPageText.revision_id).where(
            RevisionPageText.revision_id == revision_id,
            RevisionPageText.format == PAGE_TEXT_FORMAT,
            RevisionPageText.parser_version == PARSER_VERSION,
        )
    )
    return stored is not None


async def latest_pdf_revisions(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[DocumentRevision]:
    """Последняя ревизия каждого PDF-документа проекта, по имени файла."""
    rows = await session.scalars(
        select(DocumentRevision)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(Document.project_id == project_id, Document.document_kind == DocumentKind.PDF)
        .distinct(DocumentRevision.document_id)
        .order_by(
            DocumentRevision.document_id,
            DocumentRevision.created_at.desc(),
            DocumentRevision.id.desc(),
        )
    )
    return sorted(rows, key=lambda item: (item.source_filename, str(item.id)))


async def execute_sheet_passport_extract(
    session: AsyncSession, job: Job, *, storage: ObjectStorage, settings: Settings
) -> Job:
    """Тело задания `sheet_passport_extract`: паспорта-кандидаты по текстовому слою PDF проекта.

    Файлы идут по одному, после каждого - коммит. Каждый разбирается подпроцессом с пределом
    памяти и времени. Файл, который не открылся или не уложился в пределы, задание не валит:
    он попадает в итог с именем и классом ошибки (содержимое чужих документов в итог и журнал
    не попадает). Ревизия, уже разобранная текущей версией разборщика и с сохранённым текстом
    страниц, при повторе пропускается. Сбой выгрузки текста (`PageTextStoreFailed`) кандидатов
    не отменяет, но попадает в итог; ревизия без строки текста при повторе разбирается снова.
    """
    raw_project_id = job.payload.get("project_id")
    try:
        project_id = uuid.UUID(str(raw_project_id))
    except ValueError:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=ErrorCode.SHEET_PASSPORT_EXTRACT_FAILED.value,
            error_message="в задании нет ссылки на проект",
        )

    await jobs_service.start(session, job=job, stage="passport")
    revisions = await latest_pdf_revisions(session, project_id=project_id)
    await session.commit()

    files = pages = created = updated = skipped = already = texts = 0
    errors: list[dict[str, str]] = []
    error_count = 0
    total = len(revisions)
    for number, revision in enumerate(revisions, start=1):
        file_name = revision.source_filename
        revision_id = revision.id
        if await _already_parsed(session, revision_id):
            already += 1
            await jobs_service.report_progress(session, job=job, progress=number / total)
            await session.commit()
            continue
        try:
            parsed = await _download_and_parse(
                storage,
                storage_key=revision.storage_key,
                file_name=file_name,
                project_id=project_id,
                revision_id=revision_id,
                settings=settings,
            )
        except ObjectNotFoundError:
            reason = "ObjectNotFoundError"
        except PassportParseError as error:
            reason = error.reason
            log.warning("sheet_passport_file_failed", job_id=str(job.id), reason=reason)
        except Exception as error:
            reason = type(error).__name__
            log.warning("sheet_passport_file_failed", job_id=str(job.id), reason=reason)
        else:
            reason = ""
            try:
                # Своя точка сохранения: отказ базы на одном файле не валит задание целиком.
                async with session.begin_nested():
                    made, changed, left = await _upsert_candidates(
                        session,
                        project_id=project_id,
                        revision_id=revision_id,
                        file_name=file_name,
                        candidates=parsed.candidates,
                    )
                    if parsed.text is not None:
                        await _upsert_page_text(
                            session,
                            project_id=project_id,
                            revision_id=revision_id,
                            stored=parsed.text,
                        )
            except DBAPIError as error:
                reason = "ParseStoreFailed"
                log.warning(
                    "sheet_passport_file_failed",
                    job_id=str(job.id),
                    reason=reason,
                    db_error=type(error.orig).__name__,
                )
                made = changed = left = 0
                parsed = _ParsedFile(candidates=[], text=None)
        if not reason:
            files += 1
            pages += len(parsed.candidates)
            created += made
            updated += changed
            skipped += left
            if parsed.text is not None:
                texts += 1
            else:
                # Кандидаты сохранены, текста нет: файл попадает в итог, повтор доделает текст.
                reason = REASON_STORE_FAILED
        if reason:
            error_count += 1
            if len(errors) < MAX_REPORTED_ERRORS:
                errors.append({"file_name": file_name, "reason": reason})
        await jobs_service.report_progress(session, job=job, progress=number / total)
        await session.commit()

    log.info(
        "sheet_passport_extract_finished",
        job_id=str(job.id),
        files=files,
        already_parsed=already,
        pages=pages,
        page_texts_stored=texts,
        errors=error_count,
    )
    result = await jobs_service.succeed(
        session,
        job=job,
        payload={
            "files_total": total,
            "files_parsed": files,
            "files_already_parsed": already,
            "pages": pages,
            "page_texts_stored": texts,
            "created": created,
            "updated": updated,
            "skipped_reviewed": skipped,
            "error_count": error_count,
            "errors": errors,
            "versions": dictionary_versions(),
        },
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- чтение и правка


def _to_out(row: SheetPassport, document_id: uuid.UUID, document_name: str) -> SheetPassportOut:
    return SheetPassportOut(
        id=row.id,
        project_id=row.project_id,
        revision_id=row.revision_id,
        document_id=document_id,
        document_name=document_name,
        page_index=row.page_index,
        file_name=row.file_name,
        section_mark=row.section_mark,
        sheet_kind=row.sheet_kind,
        stage=row.stage,
        building=row.building,
        section=row.section,
        level_from=row.level_from,
        level_to=row.level_to,
        level_from_ordinal=row.level_from_ordinal,
        level_to_ordinal=row.level_to_ordinal,
        elevation_m=row.elevation_m,
        code=row.code,
        sheet_number=row.sheet_number,
        title=row.title,
        status=SheetPassportStatus(row.status),
        evidence={
            name: FieldEvidenceOut(
                source=str(item.get("source", "")), snippet=str(item.get("snippet", ""))
            )
            for name, item in row.evidence.items()
            if isinstance(item, dict)
        },
        versions={str(key): str(value) for key, value in row.versions.items()},
        confirmed_by=row.confirmed_by,
        confirmed_at=row.confirmed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _scoped(project_id: uuid.UUID) -> Any:
    return (
        select(SheetPassport, Document.id, Document.display_name)
        .join(DocumentRevision, DocumentRevision.id == SheetPassport.revision_id)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(SheetPassport.project_id == project_id)
    )


async def list_passports(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    status: SheetPassportStatus | None,
    section_mark: str | None,
    revision_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[SheetPassportOut], int]:
    conditions = []
    if status is not None:
        conditions.append(SheetPassport.status == status.value)
    if section_mark is not None:
        conditions.append(SheetPassport.section_mark == section_mark)
    if revision_id is not None:
        conditions.append(SheetPassport.revision_id == revision_id)
    total = await session.scalar(
        select(func.count())
        .select_from(SheetPassport)
        .where(SheetPassport.project_id == project_id, *conditions)
    )
    result = await session.execute(
        _scoped(project_id)
        .where(*conditions)
        .order_by(SheetPassport.file_name, SheetPassport.page_index, SheetPassport.id)
        .limit(limit)
        .offset(offset)
        .execution_options(populate_existing=True)
    )
    items = [_to_out(row, document_id, name) for row, document_id, name in result.all()]
    return items, int(total or 0)


async def get_passport_out(
    session: AsyncSession, *, project_id: uuid.UUID, passport_id: uuid.UUID
) -> SheetPassportOut:
    result = await session.execute(
        _scoped(project_id)
        .where(SheetPassport.id == passport_id)
        .execution_options(populate_existing=True)
    )
    found = result.first()
    if found is None:
        raise not_found("Паспорт листа")
    row, document_id, name = found
    return _to_out(row, document_id, name)


def _stamp_review(row: SheetPassport, status: SheetPassportStatus, user_id: uuid.UUID) -> None:
    row.status = status.value
    if status is SheetPassportStatus.CANDIDATE:
        row.confirmed_by = None
        row.confirmed_at = None
    else:
        row.confirmed_by = user_id
        row.confirmed_at = datetime.now(UTC)


async def patch_passport(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    passport_id: uuid.UUID,
    patch: SheetPassportPatch,
    user_id: uuid.UUID,
) -> SheetPassportOut:
    """Правка полей и/или статуса; правленое поле получает доказательство `manual`."""
    row = await session.scalar(
        select(SheetPassport)
        .where(SheetPassport.id == passport_id, SheetPassport.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise not_found("Паспорт листа")
    evidence: dict[str, Any] = dict(row.evidence)
    for name in PASSPORT_FIELDS:
        if name in patch.model_fields_set:
            setattr(row, name, getattr(patch, name))
            evidence[name] = {"source": EvidenceSource.MANUAL.value, "snippet": ""}
    row.evidence = evidence
    if patch.status is not None:
        _stamp_review(row, patch.status, user_id)
    await session.flush()
    return await get_passport_out(session, project_id=project_id, passport_id=passport_id)


async def bulk_status(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    ids: list[uuid.UUID],
    status: SheetPassportStatus,
    user_id: uuid.UUID,
) -> int:
    """Единый статус пачке паспортов проекта; чужой или неизвестный id - 404, ничего не меняется."""
    unique = set(ids)
    found = await session.scalar(
        select(func.count())
        .select_from(SheetPassport)
        .where(SheetPassport.project_id == project_id, SheetPassport.id.in_(unique))
    )
    if int(found or 0) != len(unique):
        raise not_found("Паспорт листа")
    review = status is not SheetPassportStatus.CANDIDATE
    updated = await session.scalars(
        update(SheetPassport)
        .where(SheetPassport.project_id == project_id, SheetPassport.id.in_(unique))
        .values(
            status=status.value,
            confirmed_by=user_id if review else None,
            confirmed_at=datetime.now(UTC) if review else None,
        )
        .returning(SheetPassport.id)
    )
    return len(updated.all())


# --------------------------------------------------------------------------- итог разбора


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _payload_errors(payload: dict[str, Any]) -> list[SheetPassportExtractError]:
    raw = payload.get("errors")
    if not isinstance(raw, list):
        return []
    return [
        SheetPassportExtractError(
            file_name=str(item["file_name"]), error=str(item.get("reason", ""))
        )
        for item in raw
        if isinstance(item, dict) and "file_name" in item
    ]


def _payload_versions(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("versions")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


async def latest_extract_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SheetPassportExtractSummary | None:
    """Последнее задание разбора листов проекта с итогом из его payload; заданий не было - None."""
    job = await session.scalar(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.SHEET_PASSPORT_EXTRACT,
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    if job is None:
        return None
    payload: dict[str, Any] = job.payload if isinstance(job.payload, dict) else {}
    return SheetPassportExtractSummary(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
        files_total=_payload_int(payload, "files_total"),
        files_parsed=_payload_int(payload, "files_parsed"),
        pages=_payload_int(payload, "pages"),
        created=_payload_int(payload, "created"),
        updated=_payload_int(payload, "updated"),
        skipped_reviewed=_payload_int(payload, "skipped_reviewed"),
        error_count=_payload_int(payload, "error_count"),
        errors=_payload_errors(payload),
        versions=_payload_versions(payload),
    )
