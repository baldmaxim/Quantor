"""Ведомости листов (ADR-0043, С2, «ведомость ↔ листы»): задание разбора, выдача, подтверждение.

Задание `sheet_register_extract` читает сохранённый текст страниц последних ревизий PDF (тот, что
сохраняет разбор паспортов листов) и разбирает таблицы ведомостей детерминированным разборщиком
`consistency.sheet_register.v1`, без модели, OCR и растра. Найденная ведомость - кандидат; человек
подтверждает или отклоняет её целиком. Повторный разбор заменяет кандидатов, а подтверждённые и
отклонённые ведомости не трогает. Доступ к проекту проверяет вызывающий.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.sheet_registers import (
    RegisterEntryOut,
    RegisterExtractSummary,
    SheetRegisterOut,
    SheetRegistersOut,
)
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import ErrorCode, not_found
from app.models import Job, Project, RevisionPageText, SheetPassport, SheetRegister
from app.services import jobs as jobs_service
from app.services.consistency.page_texts import PAGE_TEXT_FORMAT, iter_page_texts
from app.services.consistency.register_checks import (
    REGISTER_CHECKS_VERSION,
    RegisterView,
    SheetView,
)
from app.services.consistency.sheet_register import (
    REGISTER_VERSION,
    RegisterEntry,
    RegisterPage,
    RegisterStatus,
    parse_register_page,
)
from app.services.sheet_passports import latest_pdf_revisions
from app.storage.base import ObjectStorage

log = get_logger(__name__)

EXTRACT_FAILED_CODE: Final = ErrorCode.SHEET_REGISTER_EXTRACT_FAILED.value
MAX_REPORTED_FILES: Final = 50
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)


def versions() -> dict[str, str]:
    return {"parser": REGISTER_VERSION, "checks": REGISTER_CHECKS_VERSION}


def _no_nul(text: str) -> str:
    return text.replace("\x00", "")


# --------------------------------------------------------------------------- постановка


async def schedule_extract(session: AsyncSession, *, project: Project) -> Job:
    """Ставит задание разбора; уже есть активное - возвращает его (проект под блокировкой)."""
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    active = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.SHEET_REGISTER_EXTRACT,
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
        job_type=JobType.SHEET_REGISTER_EXTRACT,
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )


# --------------------------------------------------------------------------- исполнитель


@dataclass(slots=True)
class _Found:
    """Ведомость ревизии со страницами-продолжениями."""

    page_index: int
    heading: str
    pages: list[int]
    entries: list[tuple[RegisterEntry, int]]
    duplicates: list[str] = field(default_factory=list)

    def numbers(self) -> set[str]:
        return {entry.number for entry, _ in self.entries}

    def extend(self, page: RegisterPage, page_index: int) -> None:
        seen = self.numbers()
        self.pages.append(page_index)
        for entry in page.entries:
            if entry.number in seen:
                if entry.number not in self.duplicates:
                    self.duplicates.append(entry.number)
                continue
            seen.add(entry.number)
            self.entries.append((entry, page_index))
        for number in page.duplicates:
            if number not in self.duplicates:
                self.duplicates.append(number)


async def _scan_revision(
    storage: ObjectStorage, *, storage_key: str, max_bytes: int
) -> list[_Found]:
    """Ведомости одной ревизии; бросает PageTextError / ObjectNotFoundError."""
    found: list[_Found] = []
    previous_page: int | None = None
    async for page in iter_page_texts(storage, storage_key, max_bytes=max_bytes):
        parsed = await asyncio.to_thread(parse_register_page, page.text)
        if parsed is None:
            continue
        # Продолжение дописывается к ведомости предыдущей страницы, если она идёт подряд.
        if parsed.continued and found and previous_page == page.page_index - 1:
            found[-1].extend(parsed, page.page_index)
        else:
            register = _Found(page.page_index, parsed.heading, [], [])
            register.extend(parsed, page.page_index)
            found.append(register)
        previous_page = page.page_index
    return found


def _entries_json(found: _Found) -> list[dict[str, Any]]:
    return [
        {
            "number": _no_nul(entry.number),
            "title": _no_nul(entry.title),
            "snippet": _no_nul(entry.snippet),
            "page_index": page_index,
        }
        for entry, page_index in found.entries
    ]


async def _replace_candidates(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    found: dict[uuid.UUID, tuple[str, list[_Found]]],
    keep_revisions: set[uuid.UUID],
) -> int:
    """Заменяет кандидатов проекта, подтверждённые и отклонённые остаются; итог - число новых."""
    stale = delete(SheetRegister).where(
        SheetRegister.project_id == project_id, SheetRegister.status == "candidate"
    )
    if keep_revisions:
        stale = stale.where(SheetRegister.revision_id.not_in(list(keep_revisions)))
    await session.execute(stale)
    reviewed = {
        (revision_id, page_index)
        for revision_id, page_index in (
            await session.execute(
                select(SheetRegister.revision_id, SheetRegister.page_index).where(
                    SheetRegister.project_id == project_id
                )
            )
        ).tuples()
    }
    created = 0
    for revision_id, (file_name, registers) in found.items():
        for item in registers:
            if (revision_id, item.page_index) in reviewed:
                continue
            session.add(
                SheetRegister(
                    project_id=project_id,
                    revision_id=revision_id,
                    page_index=item.page_index,
                    file_name=_no_nul(file_name),
                    heading=_no_nul(item.heading),
                    pages=item.pages,
                    entries=_entries_json(item),
                    duplicates=item.duplicates,
                    entry_count=len(item.entries),
                    status="candidate",
                    versions=versions(),
                )
            )
            created += 1
    await session.flush()
    return created


async def execute_sheet_register_extract(
    session: AsyncSession, job: Job, *, storage: ObjectStorage, settings: Settings
) -> Job:
    """Тело задания `sheet_register_extract`: кандидаты-ведомости по тексту страниц PDF проекта.

    Ревизия без сохранённого текста (паспорта листов не разбирались) и нечитаемая ревизия задание
    не валят: они попадают в итог счётчиком и именами файлов (до 50). Кандидаты нечитаемой ревизии
    остаются. Содержимое документов в итог и журнал не попадает.
    """
    try:
        project_id = uuid.UUID(str(job.payload.get("project_id")))
    except ValueError:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=EXTRACT_FAILED_CODE,
            error_message="в задании нет ссылки на проект",
        )

    await jobs_service.start(session, job=job, stage="registers")
    revisions = await latest_pdf_revisions(session, project_id=project_id)
    stored = {
        row.revision_id: row
        for row in await session.scalars(
            select(RevisionPageText).where(
                RevisionPageText.project_id == project_id,
                RevisionPageText.format == PAGE_TEXT_FORMAT,
            )
        )
    }
    await session.commit()

    max_bytes = settings.sheet_passport_page_text_max_mb * 1024 * 1024
    found: dict[uuid.UUID, tuple[str, list[_Found]]] = {}
    scanned = 0
    no_text: list[str] = []
    no_text_count = 0
    unreadable: list[str] = []
    unreadable_count = 0
    keep: set[uuid.UUID] = set()
    total = len(revisions)
    for number, revision in enumerate(revisions, start=1):
        file_name = revision.source_filename
        text_row = stored.get(revision.id)
        if text_row is None:
            no_text_count += 1
            if len(no_text) < MAX_REPORTED_FILES:
                no_text.append(file_name)
        else:
            try:
                registers = await _scan_revision(
                    storage, storage_key=text_row.storage_key, max_bytes=max_bytes
                )
            except Exception as error:  # PageTextError, ObjectNotFoundError и сбои разбора
                reason = type(error).__name__
                log.warning("sheet_register_revision_failed", job_id=str(job.id), reason=reason)
                unreadable_count += 1
                keep.add(revision.id)
                if len(unreadable) < MAX_REPORTED_FILES:
                    unreadable.append(file_name)
            else:
                scanned += 1
                if registers:
                    found[revision.id] = (file_name, registers)
        await jobs_service.report_progress(session, job=job, progress=number / total)
        await session.commit()

    created = await _replace_candidates(
        session, project_id=project_id, found=found, keep_revisions=keep
    )
    registers_found = sum(len(items) for _, items in found.values())
    log.info(
        "sheet_register_extract_finished",
        job_id=str(job.id),
        revisions_scanned=scanned,
        revisions_no_text=no_text_count,
        revisions_unreadable=unreadable_count,
        registers=registers_found,
        created=created,
    )
    result = await jobs_service.succeed(
        session,
        job=job,
        payload={
            "revisions_total": total,
            "revisions_scanned": scanned,
            "revisions_no_text": no_text_count,
            "no_text_files": no_text,
            "revisions_unreadable": unreadable_count,
            "unreadable_files": unreadable,
            "registers": registers_found,
            "versions": versions(),
        },
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- выдача


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _payload_names(payload: dict[str, Any], key: str) -> list[str]:
    raw = payload.get(key)
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _payload_versions(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("versions")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


async def latest_extract_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> RegisterExtractSummary | None:
    """Последнее задание разбора ведомостей проекта с итогом; заданий не было - None."""
    job = await session.scalar(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.SHEET_REGISTER_EXTRACT,
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    if job is None:
        return None
    payload: dict[str, Any] = job.payload if isinstance(job.payload, dict) else {}
    return RegisterExtractSummary(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
        registers=_payload_int(payload, "registers"),
        revisions_total=_payload_int(payload, "revisions_total"),
        revisions_scanned=_payload_int(payload, "revisions_scanned"),
        revisions_no_text=_payload_int(payload, "revisions_no_text"),
        no_text_files=_payload_names(payload, "no_text_files"),
        revisions_unreadable=_payload_int(payload, "revisions_unreadable"),
        unreadable_files=_payload_names(payload, "unreadable_files"),
        versions=_payload_versions(payload),
    )


def _entry_of(raw: object) -> RegisterEntry | None:
    if not isinstance(raw, dict):
        return None
    number, title, snippet = raw.get("number"), raw.get("title"), raw.get("snippet")
    if not isinstance(number, str) or not isinstance(title, str) or not isinstance(snippet, str):
        return None
    return RegisterEntry(number=number, title=title, snippet=snippet)


def _entry_page(raw: object, default: int) -> int:
    if isinstance(raw, dict):
        value = raw.get("page_index")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return default


def _ints(raw: list[Any]) -> list[int]:
    return [item for item in raw if isinstance(item, int) and not isinstance(item, bool)]


def _strings(raw: list[Any]) -> list[str]:
    return [item for item in raw if isinstance(item, str)]


def _register_out(row: SheetRegister) -> SheetRegisterOut:
    entries = []
    for raw in row.entries:
        entry = _entry_of(raw)
        if entry is not None:
            entries.append(
                RegisterEntryOut(
                    number=entry.number,
                    title=entry.title,
                    snippet=entry.snippet,
                    page_index=_entry_page(raw, row.page_index),
                )
            )
    return SheetRegisterOut(
        id=row.id,
        revision_id=row.revision_id,
        file_name=row.file_name,
        page_index=row.page_index,
        pages=_ints(row.pages),
        heading=row.heading,
        entries=entries,
        duplicates=_strings(row.duplicates),
        status=RegisterStatus(row.status),
        confirmed_at=row.confirmed_at,
    )


async def _latest_registers(session: AsyncSession, project_id: uuid.UUID) -> list[SheetRegister]:
    revision_ids = [
        revision.id for revision in await latest_pdf_revisions(session, project_id=project_id)
    ]
    if not revision_ids:
        return []
    rows = await session.scalars(
        select(SheetRegister)
        .where(SheetRegister.project_id == project_id, SheetRegister.revision_id.in_(revision_ids))
        .order_by(SheetRegister.file_name, SheetRegister.page_index, SheetRegister.id)
    )
    return list(rows)


async def registers_view(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SheetRegistersOut:
    rows = await _latest_registers(session, project_id)
    return SheetRegistersOut(
        registers=[_register_out(row) for row in rows],
        last_extract=await latest_extract_summary(
            session, workspace_id=workspace_id, project_id=project_id
        ),
        versions=versions(),
    )


async def bulk_status(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    ids: list[uuid.UUID],
    status: RegisterStatus,
    user_id: uuid.UUID,
) -> int:
    """Единый статус пачке ведомостей проекта; чужой или неизвестный id - 404, без изменений."""
    unique = set(ids)
    found = await session.scalar(
        select(func.count())
        .select_from(SheetRegister)
        .where(SheetRegister.project_id == project_id, SheetRegister.id.in_(unique))
    )
    if int(found or 0) != len(unique):
        raise not_found("Ведомость листов")
    review = status is not RegisterStatus.CANDIDATE
    updated = await session.scalars(
        update(SheetRegister)
        .where(SheetRegister.project_id == project_id, SheetRegister.id.in_(unique))
        .values(
            status=status.value,
            confirmed_by=user_id if review else None,
            confirmed_at=datetime.now(UTC) if review else None,
        )
        .returning(SheetRegister.id)
    )
    return len(updated.all())


# --------------------------------------------------------------------------- входы проверок


def _register_view(row: SheetRegister) -> RegisterView:
    entries = tuple(entry for raw in row.entries if (entry := _entry_of(raw)) is not None)
    return RegisterView(
        id=str(row.id),
        revision_id=str(row.revision_id),
        file_name=row.file_name,
        page_index=row.page_index,
        entries=entries,
        duplicates=tuple(_strings(row.duplicates)),
    )


def _sheet_view(row: SheetPassport) -> SheetView:
    return SheetView(
        id=str(row.id),
        revision_id=str(row.revision_id),
        file_name=row.file_name,
        page_index=row.page_index,
        sheet_number=row.sheet_number,
        sheet_kind=row.sheet_kind,
        section_mark=row.section_mark,
        title=row.title,
        confirmed=row.status == "confirmed",
    )


async def register_check_inputs(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[list[RegisterView], int, list[SheetView]]:
    """Подтверждённые ведомости, число кандидатов и не отклонённые паспорта их ревизий."""
    rows = await _latest_registers(session, project_id)
    confirmed = [row for row in rows if row.status == RegisterStatus.CONFIRMED.value]
    candidates = sum(1 for row in rows if row.status == RegisterStatus.CANDIDATE.value)
    revision_ids = list({row.revision_id for row in confirmed})
    sheets: list[SheetView] = []
    if revision_ids:
        passports = await session.scalars(
            select(SheetPassport)
            .where(
                SheetPassport.project_id == project_id,
                SheetPassport.revision_id.in_(revision_ids),
                SheetPassport.status != "rejected",
            )
            .order_by(SheetPassport.file_name, SheetPassport.page_index, SheetPassport.id)
        )
        sheets = [_sheet_view(row) for row in passports]
    return [_register_view(row) for row in confirmed], candidates, sheets
