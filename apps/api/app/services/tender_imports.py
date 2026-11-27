"""Пакетный импорт тендерной документации: перечень комплекта, поиск объекта, состояние позиций.

Клиент присылает перечень ZIP-пакетов распознавалки с хешами; портал находит или (если токену
это разрешено) создаёт объект, заводит запись комплекта и отвечает, какие позиции надо догрузить.
Файлы принимает обычная загрузка в проект (`POST /projects/{id}/uploads`) с привязкой к позиции.

Два правила модуля:

1. Отпечаток комплекта (`content_key`) считается по ключам позиций и хешам PDF и blocks.json.
   Хеш и размер самого ZIP в него не входят: архив пересобирается с новыми временными метками,
   а комплект остаётся тем же.
2. Состояние позиции в базе не хранится. Оно выводится при чтении из задания импорта и ревизий
   проекта пакетными запросами, поэтому исполнитель заданий о пакетном импорте ничего не знает.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, get_args

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.permissions import Permission, permissions_for
from app.contracts.tender_imports import (
    ItemState,
    MatchedBy,
    TenderImportItemIn,
    TenderImportItemRead,
    TenderImportRead,
    TenderImportStart,
    TenderImportSummary,
    TenderImportUpload,
)
from app.core.config import Settings
from app.domain import ArtifactKind, JobStatus, ProjectSource
from app.errors import MESSAGES, DomainError, ErrorCode
from app.integrations.tenderhub import TenderHubClient
from app.models import (
    Document,
    DocumentRevision,
    Job,
    Project,
    RecognitionArtifact,
    TenderImport,
    TenderImportItem,
)
from app.services import jobs as jobs_service
from app.services import projects as projects_service

_MATCHED_BY: Final[TypeAdapter[MatchedBy]] = TypeAdapter(MatchedBy)
ITEM_STATES: Final[tuple[str, ...]] = get_args(ItemState)
UPLOAD_FILE_FIELD: Final = "file"
UPLOAD_IMPORT_FIELD: Final = "tender_import_id"
UPLOAD_ITEM_FIELD: Final = "tender_import_item"


# --------------------------------------------------------------------------- отпечаток


def compute_content_key(items: Sequence[TenderImportItemIn]) -> str:
    """Отпечаток комплекта: sha256 канонического JSON отсортированного списка позиций."""
    rows = sorted([item.key, item.pdf_sha256, item.blocks_sha256] for item in items)
    canonical = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_sizes(items: Sequence[TenderImportItemIn], *, max_size: int) -> None:
    """Размер ZIP не больше предела загрузки: иначе позицию всё равно нельзя принять."""
    for item in items:
        if item.size > max_size:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                f"Размер позиции «{item.key}» больше допустимых {max_size // (1024 * 1024)} МБ",
            )


# --------------------------------------------------------------------------- объект


@dataclass(frozen=True, slots=True)
class ResolvedProject:
    project: Project
    matched_by: MatchedBy
    tenderhub_id: str | None


def _lock_id(workspace_id: uuid.UUID, key: str) -> int:
    digest = hashlib.sha256(f"tender_import:{workspace_id}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def lock_tender(session: AsyncSession, *, workspace_id: uuid.UUID, key: str) -> None:
    """Блокировка до конца транзакции на номер тендера (или его id без номера) в пространстве.

    Её берут оба пути создания объекта по тендеру - импорт и «Создать проект по тендеру»:
    иначе параллельно они завели бы два объекта на один номер.
    """
    await session.execute(select(func.pg_advisory_xact_lock(_lock_id(workspace_id, key))))


async def _find_by_tender(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    tenderhub_id: str,
    tender_number: str | None,
) -> tuple[Project, MatchedBy] | None:
    by_id = await projects_service.find_by_external_id(
        session,
        workspace_id=workspace_id,
        source=ProjectSource.TENDERHUB,
        external_id=tenderhub_id,
    )
    if by_id is not None:
        return by_id, "tenderhub_id"
    if tender_number:
        by_number = await projects_service.find_by_external_ref(
            session,
            workspace_id=workspace_id,
            source=ProjectSource.TENDERHUB,
            external_ref=tender_number,
        )
        if by_number is not None:
            return by_number, "tender_number"
    return None


async def resolve_project(
    session: AsyncSession,
    context: AuthContext,
    *,
    tenderhub_id: str | None,
    project_id: uuid.UUID | None,
    client: TenderHubClient | None,
) -> ResolvedProject:
    """Объект импорта: существующий по id, по тендеру TenderHUB или созданный по тендеру."""
    workspace_id = context.tenant
    if project_id is not None:
        project = await projects_service.get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if project is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Проект не найден")
        return ResolvedProject(project, "project_id", None)

    if tenderhub_id is None:  # pragma: no cover - исключено контрактом запроса
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Укажите tenderhub_id или project_id")

    by_id = await projects_service.find_by_external_id(
        session,
        workspace_id=workspace_id,
        source=ProjectSource.TENDERHUB,
        external_id=tenderhub_id,
    )
    if by_id is not None:
        return ResolvedProject(by_id, "tenderhub_id", tenderhub_id)

    may_create = Permission.TENDER_IMPORT_CREATE_PROJECT in context.permissions
    if client is None:
        raise DomainError(
            ErrorCode.TENDERHUB_DISABLED if may_create else ErrorCode.TENDER_IMPORT_CREATE_FORBIDDEN
        )
    # Объект мог быть заведён по другой версии того же тендера: номер берётся из TenderHUB и для
    # токена без области tender_import - он только ищет, создать объект ему нельзя.
    # Номер и название берутся только из ответа TenderHUB, а не от клиента. Сеть - до блокировки.
    tender = await client.get_tender(tenderhub_id)

    found = await _find_by_tender(
        session,
        workspace_id=workspace_id,
        tenderhub_id=tenderhub_id,
        tender_number=tender.tender_number,
    )
    if found is not None:
        return ResolvedProject(found[0], found[1], tenderhub_id)

    if not may_create or Permission.PROJECT_CREATE not in permissions_for(context.role):
        raise DomainError(ErrorCode.TENDER_IMPORT_CREATE_FORBIDDEN)

    # Два параллельных импорта одного тендера не должны завести два объекта.
    await lock_tender(session, workspace_id=workspace_id, key=tender.tender_number or tenderhub_id)
    found = await _find_by_tender(
        session,
        workspace_id=workspace_id,
        tenderhub_id=tenderhub_id,
        tender_number=tender.tender_number,
    )
    if found is not None:
        return ResolvedProject(found[0], found[1], tenderhub_id)

    project = await projects_service.create_project(
        session,
        workspace_id=workspace_id,
        name=projects_service.project_name(tender),
        source=ProjectSource.TENDERHUB,
        external_id=tenderhub_id,
        external_ref=tender.tender_number,
    )
    return ResolvedProject(project, "created", tenderhub_id)


# --------------------------------------------------------------------------- состояние


@dataclass(slots=True)
class ItemView:
    """Вычисленное состояние позиции и то, на что оно опирается."""

    state: ItemState
    job: Job | None = None
    document_id: uuid.UUID | None = None
    pdf_revision_id: uuid.UUID | None = None
    error_code: str | None = None
    error_message: str | None = None


def _revision_id_of(job: Job) -> uuid.UUID | None:
    value = job.payload.get("imported_revision_id")
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def compute_states(
    session: AsyncSession, *, project_id: uuid.UUID, items: Sequence[TenderImportItem]
) -> dict[uuid.UUID, ItemView]:
    """Состояния позиций пакетными запросами: задания, ревизии PDF и артефакты blocks.json."""
    job_ids = {item.job_id for item in items if item.job_id is not None}
    jobs: dict[uuid.UUID, Job] = {}
    if job_ids:
        job_rows = await session.execute(select(Job).where(Job.id.in_(job_ids)))
        jobs = {job.id: job for job in job_rows.scalars()}

    # Ревизия PDF для позиций с выполненным заданием - из payload задания.
    revision_ids: set[uuid.UUID] = set()
    for item in items:
        job = jobs.get(item.job_id) if item.job_id is not None else None
        if job is not None and job.status is JobStatus.SUCCEEDED:
            revision_id = _revision_id_of(job)
            if revision_id is not None:
                revision_ids.add(revision_id)

    # Позиции без задания: предварительная сверка с PDF проекта. Берётся самая ранняя ревизия
    # с таким хешем - ровно та, которую выберет импортёр при прикреплении.
    unsent = [item for item in items if item.job_id is None or item.job_id not in jobs]
    by_pdf: dict[str, DocumentRevision] = {}
    if unsent:
        rows = await session.execute(
            select(DocumentRevision)
            .join(Document, DocumentRevision.document_id == Document.id)
            .where(
                Document.project_id == project_id,
                DocumentRevision.source_sha256.in_({item.pdf_sha256 for item in unsent}),
            )
            .order_by(DocumentRevision.created_at.asc(), DocumentRevision.id.asc())
        )
        for revision in rows.scalars():
            by_pdf.setdefault(revision.source_sha256, revision)
        revision_ids |= {revision.id for revision in by_pdf.values()}

    revisions: dict[uuid.UUID, DocumentRevision] = {}
    blocks_sha: dict[uuid.UUID, str] = {}
    if revision_ids:
        rows = await session.execute(
            select(DocumentRevision).where(DocumentRevision.id.in_(revision_ids))
        )
        revisions = {revision.id: revision for revision in rows.scalars()}
        artifacts = await session.execute(
            select(RecognitionArtifact.revision_id, RecognitionArtifact.sha256).where(
                RecognitionArtifact.revision_id.in_(revision_ids),
                RecognitionArtifact.artifact_kind == ArtifactKind.BLOCKS_JSON,
            )
        )
        for revision_id, sha256 in artifacts.all():
            blocks_sha.setdefault(revision_id, sha256)

    views: dict[uuid.UUID, ItemView] = {}
    for item in items:
        job = jobs.get(item.job_id) if item.job_id is not None else None
        if job is None:
            views[item.id] = _view_without_job(item, by_pdf, blocks_sha)
        else:
            views[item.id] = _view_with_job(item, job, revisions, blocks_sha)
    return views


def _conflict(revision: DocumentRevision, job: Job | None) -> ItemView:
    return ItemView(
        state="conflict",
        job=job,
        document_id=revision.document_id,
        pdf_revision_id=revision.id,
        error_code=ErrorCode.TENDER_IMPORT_OCR_CONFLICT.value,
        error_message=MESSAGES[ErrorCode.TENDER_IMPORT_OCR_CONFLICT],
    )


def _view_without_job(
    item: TenderImportItem,
    by_pdf: dict[str, DocumentRevision],
    blocks_sha: dict[uuid.UUID, str],
) -> ItemView:
    revision = by_pdf.get(item.pdf_sha256)
    existing = blocks_sha.get(revision.id) if revision is not None else None
    if revision is None or existing is None:
        return ItemView(state="pending")
    if existing == item.blocks_sha256:
        return ItemView(
            state="imported", document_id=revision.document_id, pdf_revision_id=revision.id
        )
    return _conflict(revision, None)


def _view_with_job(
    item: TenderImportItem,
    job: Job,
    revisions: dict[uuid.UUID, DocumentRevision],
    blocks_sha: dict[uuid.UUID, str],
) -> ItemView:
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return ItemView(state="received", job=job)
    if job.status is not JobStatus.SUCCEEDED:
        return ItemView(
            state="failed",
            job=job,
            error_code=job.error_code,
            error_message=job.error_message,
        )

    revision_id = _revision_id_of(job)
    revision = revisions.get(revision_id) if revision_id is not None else None
    if revision is None or revision.source_sha256 != item.pdf_sha256:
        return ItemView(
            state="failed",
            job=job,
            error_code=ErrorCode.TENDER_IMPORT_PDF_MISMATCH.value,
            error_message=MESSAGES[ErrorCode.TENDER_IMPORT_PDF_MISMATCH],
        )
    # В payload задания нет признака «уже распознан», поэтому blocks.json сверяется всегда: у
    # только что принятого пакета артефакт совпадает с заявленным, у прикреплённого к прежнему
    # распознаванию - нет, и тогда прежние данные остаются как есть.
    existing = blocks_sha.get(revision.id)
    if existing is not None and existing != item.blocks_sha256:
        return _conflict(revision, job)
    return ItemView(
        state="imported", job=job, document_id=revision.document_id, pdf_revision_id=revision.id
    )


# --------------------------------------------------------------------------- ответ


def _portal_url(settings: Settings, project_id: uuid.UUID) -> str:
    return f"{settings.portal_base_url.rstrip('/')}/projects/{project_id}"


def render(
    *,
    settings: Settings,
    import_row: TenderImport,
    project: Project,
    items: Sequence[TenderImportItem],
    views: dict[uuid.UUID, ItemView],
    created: bool,
) -> TenderImportRead:
    ordered = sorted(items, key=lambda item: item.item_key)
    counts = dict.fromkeys(ITEM_STATES, 0)
    to_upload: list[str] = []
    reads: list[TenderImportItemRead] = []
    for item in ordered:
        view = views[item.id]
        counts[view.state] += 1
        # Упавшую позицию досылать имеет смысл только при повторяемом отказе: те же байты
        # вернут то же задание в очередь. Отказ по содержимому (битый blocks.json) повторится,
        # а отменённое задание из очереди не возвращается - дослать тот же ZIP значило бы
        # получать «принято» по кругу. Их решает человек.
        if view.state == "pending" or (
            view.state == "failed" and view.job is not None and jobs_service.is_retryable(view.job)
        ):
            to_upload.append(item.item_key)
        reads.append(
            TenderImportItemRead(
                key=item.item_key,
                filename=item.filename,
                size=item.size,
                sha256=item.sha256,
                pdf_sha256=item.pdf_sha256,
                blocks_sha256=item.blocks_sha256,
                state=view.state,
                job_id=item.job_id,
                job_status=view.job.status.value if view.job is not None else None,
                package_revision_id=item.package_revision_id,
                document_id=view.document_id,
                pdf_revision_id=view.pdf_revision_id,
                error_code=view.error_code,
                error_message=view.error_message,
                received_at=item.received_at,
            )
        )
    matched_by = _MATCHED_BY.validate_python(import_row.matched_by)
    return TenderImportRead(
        import_id=import_row.id,
        project_id=project.id,
        project_name=project.name,
        project_url=_portal_url(settings, project.id),
        tenderhub_id=import_row.tenderhub_id,
        matched_by=matched_by,
        created=created,
        complete=(
            counts["pending"] == 0
            and counts["uploading"] == 0
            and counts["received"] == 0
            and not to_upload
        ),
        summary=TenderImportSummary(
            total=len(ordered),
            pending=counts["pending"],
            uploading=counts["uploading"],
            received=counts["received"],
            imported=counts["imported"],
            failed=counts["failed"],
            conflict=counts["conflict"],
        ),
        to_upload=to_upload,
        upload=TenderImportUpload(
            method="POST",
            path=f"/api/v1/projects/{project.id}/uploads",
            file_field=UPLOAD_FILE_FIELD,
            fields={UPLOAD_IMPORT_FIELD: str(import_row.id)},
            item_field=UPLOAD_ITEM_FIELD,
        ),
        items=reads,
    )


async def _load_items(session: AsyncSession, import_id: uuid.UUID) -> list[TenderImportItem]:
    rows = await session.execute(
        select(TenderImportItem)
        .where(TenderImportItem.import_id == import_id)
        .order_by(TenderImportItem.item_key)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _free_item_ids(session: AsyncSession, import_id: uuid.UUID) -> set[uuid.UUID]:
    """Позиции, файл которых сейчас не принимается (`lock_item` загрузки строку не держит).

    FOR KEY SHARE конфликтует только с FOR UPDATE загрузки: параллельные статус и запуск друг
    друга занятыми не видят. SKIP LOCKED не ждёт - занятая строка просто не попадает в ответ.
    Свободная строка остаётся под блокировкой до конца транзакции: загрузка её не возьмёт, пока
    запуск переписывает имя и хеш (UPDATE двух запусков ждёт лишь коротко, без взаимоблокировки).
    """
    rows = await session.execute(
        select(TenderImportItem.id)
        .where(TenderImportItem.import_id == import_id)
        .with_for_update(skip_locked=True, read=True, key_share=True)
    )
    return set(rows.scalars())


def _mark_uploading(
    views: dict[uuid.UUID, ItemView], items: Sequence[TenderImportItem], free: set[uuid.UUID]
) -> None:
    """Позиция, ждущая файла, чей ZIP сейчас принимается, - `uploading`: досылать её не надо."""
    for item in items:
        view = views[item.id]
        if item.id not in free and view.state in ("pending", "failed"):
            views[item.id] = ItemView(state="uploading", job=view.job)


# --------------------------------------------------------------------------- запуск и статус


async def start(
    session: AsyncSession,
    context: AuthContext,
    *,
    settings: Settings,
    payload: TenderImportStart,
    client: TenderHubClient | None,
) -> tuple[TenderImportRead, bool]:
    """Находит или создаёт объект и запись комплекта. Возвращает ответ и признак «создан»."""
    # Перечень проверяется до любых поисков: плохой запрос не должен создавать объект.
    validate_sizes(payload.items, max_size=settings.max_upload_size_bytes)
    key = compute_content_key(payload.items)

    resolved = await resolve_project(
        session,
        context,
        tenderhub_id=payload.tenderhub_id,
        project_id=payload.project_id,
        client=client,
    )
    project = resolved.project

    inserted = await session.execute(
        pg_insert(TenderImport)
        .values(
            id=uuid.uuid4(),
            workspace_id=project.workspace_id,
            project_id=project.id,
            tenderhub_id=resolved.tenderhub_id,
            matched_by=resolved.matched_by,
            content_key=key,
            created_by_user_id=context.principal.user_id,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "content_key"])
        .returning(TenderImport.id)
    )
    new_id = inserted.scalar_one_or_none()
    created = new_id is not None

    import_row = (
        await session.execute(
            select(TenderImport)
            .where(TenderImport.project_id == project.id, TenderImport.content_key == key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    if created:
        session.add_all(
            TenderImportItem(
                import_id=import_row.id,
                item_key=item.key,
                filename=item.filename,
                size=item.size,
                sha256=item.sha256,
                pdf_sha256=item.pdf_sha256,
                blocks_sha256=item.blocks_sha256,
            )
            for item in payload.items
        )
        await session.flush()
        free = None
    else:
        # Свободные позиции блокируются до конца запуска, занятые загрузкой не ждём.
        free = await _free_item_ids(session, import_row.id)

    # Позиции читаются после блокировки: загрузка, закончившаяся раньше, уже видна.
    items = await _load_items(session, import_row.id)
    views = await compute_states(session, project_id=project.id, items=items)

    if free is not None:
        # ZIP мог быть пересобран: у ожидающих и упавших позиций обновляются имя, размер и хеш.
        # Принятые позиции и позиции, чей файл сейчас принимается, не трогаются.
        incoming = {item.key: item for item in payload.items}
        for row in items:
            new = incoming.get(row.item_key)
            if (
                new is None
                or row.id not in free
                or views[row.id].state not in ("pending", "failed")
            ):
                continue
            row.filename, row.size, row.sha256 = new.filename, new.size, new.sha256
        await session.flush()
        _mark_uploading(views, items, free)

    read = render(
        settings=settings,
        import_row=import_row,
        project=project,
        items=items,
        views=views,
        created=created,
    )
    return read, created


async def get_status(
    session: AsyncSession, context: AuthContext, *, settings: Settings, import_id: uuid.UUID
) -> TenderImportRead:
    import_row = await get_import(session, workspace_id=context.tenant, import_id=import_id)
    project = await projects_service.get_project(
        session, workspace_id=import_row.workspace_id, project_id=import_row.project_id
    )
    if project is None:
        raise DomainError(ErrorCode.TENDER_IMPORT_NOT_FOUND)
    free = await _free_item_ids(session, import_row.id)
    items = await _load_items(session, import_row.id)
    views = await compute_states(session, project_id=project.id, items=items)
    _mark_uploading(views, items, free)
    return render(
        settings=settings,
        import_row=import_row,
        project=project,
        items=items,
        views=views,
        created=False,
    )


async def get_import(
    session: AsyncSession, *, workspace_id: uuid.UUID, import_id: uuid.UUID
) -> TenderImport:
    """Импорт своего пространства; чужой и несуществующий неотличимы (404)."""
    row = (
        await session.execute(
            select(TenderImport).where(
                TenderImport.id == import_id, TenderImport.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise DomainError(ErrorCode.TENDER_IMPORT_NOT_FOUND)
    return row


# --------------------------------------------------------------------------- привязка загрузки


async def lock_item(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    import_id: uuid.UUID,
    item_key: str,
) -> tuple[TenderImport, TenderImportItem]:
    """Импорт и строка позиции под блокировкой: параллельные загрузки одной позиции встают в ряд.

    Строка читается заново (`populate_existing`): второй запрос после ожидания обязан увидеть
    ссылку на ревизию, записанную первым, а не устаревшую копию из сессии.
    """
    import_row = await get_import(session, workspace_id=workspace_id, import_id=import_id)
    if import_row.project_id != project_id:
        raise DomainError(ErrorCode.TENDER_IMPORT_NOT_FOUND)
    item = (
        await session.execute(
            select(TenderImportItem)
            .where(TenderImportItem.import_id == import_id, TenderImportItem.item_key == item_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if item is None:
        raise DomainError(ErrorCode.TENDER_IMPORT_ITEM_NOT_FOUND)
    return import_row, item


async def item_view(
    session: AsyncSession, *, project_id: uuid.UUID, item: TenderImportItem
) -> ItemView:
    return (await compute_states(session, project_id=project_id, items=[item]))[item.id]


def attach_outcome(item: TenderImportItem, *, revision_id: uuid.UUID, job: Job | None) -> None:
    """Записывает приём ZIP в позицию; повтор того же пакета прежнюю запись не портит."""
    if item.package_revision_id != revision_id or item.received_at is None:
        item.received_at = datetime.now(UTC)
    item.package_revision_id = revision_id
    if job is not None:
        item.job_id = job.id
