"""Сервис версий тендера (ADR-0035, этап M2).

Версия тендера — замороженный комплект ревизий документов проекта. Черновик собирается:
состав берётся из последних ревизий документов, дальше его правит человек. Заморозка
фиксирует отпечаток комплекта `manifest_sha256`; после неё версию и её состав не меняет
никто — это держит триггер базы, а сервис отвечает понятным кодом раньше, чем дойдёт до него.

Все выборки идут от проекта: версию чужого пространства по прямому идентификатору не получить.
Изменяющие операции берут блокировку строки — проекта (номер версии, единственный черновик) или
самой версии (состав, заморозка), — поэтому два параллельных запроса не разойдутся.

Запись в HUBTender портал не умеет и не будет: клиент здесь только читает тендер, чтобы сверить
его номер с номером проекта (один номер — один проект) и записать номер версии той стороны.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.tender_versions import (
    TenderHubCandidateRead,
    TenderVersionDocumentPut,
    TenderVersionDocumentRead,
    TenderVersionRead,
    TenderVersionSummaryRead,
)
from app.domain import ProjectSource, TenderVersionStatus
from app.errors import DomainError, ErrorCode, not_found
from app.integrations.tenderhub import TenderHubClient
from app.models import (
    Document,
    DocumentRevision,
    Project,
    TenderVersion,
    TenderVersionDocument,
)

# --------------------------------------------------------------------------- отпечаток


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """Строка состава в том виде, в каком она входит в отпечаток."""

    document_id: uuid.UUID
    document_revision_id: uuid.UUID
    source_sha256: str
    section: str | None
    use_in_model: bool


def manifest_payload(
    *,
    tender_number: str | None,
    external_version: int | None,
    entries: Sequence[ManifestEntry],
) -> dict[str, Any]:
    """Содержимое отпечатка: номер тендера проекта, версия HUBTender и состав по document_id.

    Порядок состава не зависит от порядка выборки, поэтому один и тот же комплект даёт один
    и тот же отпечаток. Ревизия без хеша исходника комплект не фиксирует: отпечаток, не
    опирающийся на содержимое файла, ничего не доказывал бы.
    """
    ordered = sorted(entries, key=lambda entry: str(entry.document_id))
    for entry in ordered:
        if not entry.source_sha256.strip():
            raise DomainError(
                ErrorCode.TENDER_VERSION_REVISION_NO_HASH,
                issue={"document_id": str(entry.document_id)},
            )
    return {
        "tender_number": tender_number,
        "external_version": external_version,
        "documents": [
            {
                "document_id": str(entry.document_id),
                "document_revision_id": str(entry.document_revision_id),
                "source_sha256": entry.source_sha256,
                "section": entry.section,
                "use_in_model": entry.use_in_model,
            }
            for entry in ordered
        ],
    }


def compute_manifest_sha256(
    *,
    tender_number: str | None,
    external_version: int | None,
    entries: Sequence[ManifestEntry],
) -> str:
    """SHA-256 канонического JSON: ключи по алфавиту, без пробелов, кириллица как есть."""
    canonical = json.dumps(
        manifest_payload(
            tender_number=tender_number, external_version=external_version, entries=entries
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------ чтение


def _count_subquery() -> Any:
    return (
        select(func.count(TenderVersionDocument.id))
        .where(TenderVersionDocument.tender_version_id == TenderVersion.id)
        .correlate(TenderVersion)
        .scalar_subquery()
    )


def _summary(version: TenderVersion, document_count: int) -> TenderVersionSummaryRead:
    return TenderVersionSummaryRead(
        id=version.id,
        project_id=version.project_id,
        number=version.number,
        label=version.label,
        external_tender_id=version.external_tender_id,
        external_version=version.external_version,
        status=version.status,
        manifest_sha256=version.manifest_sha256,
        frozen_at=version.frozen_at,
        frozen_by=version.frozen_by,
        created_at=version.created_at,
        created_by=version.created_by,
        document_count=document_count,
    )


async def list_versions(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[TenderVersionSummaryRead]:
    """Версии проекта от новой к старой."""
    result = await session.execute(
        select(TenderVersion, _count_subquery())
        .where(TenderVersion.project_id == project_id)
        .order_by(TenderVersion.number.desc())
    )
    return [_summary(version, count) for version, count in result.all()]


async def get_version(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    lock: bool = False,
) -> TenderVersion | None:
    query = select(TenderVersion).where(
        TenderVersion.id == version_id, TenderVersion.project_id == project_id
    )
    if lock:
        # populate_existing: блокировка берётся ради актуального статуса, а не кэша сессии.
        query = query.with_for_update().execution_options(populate_existing=True)
    return (await session.execute(query)).scalar_one_or_none()


async def _composition(
    session: AsyncSession, version_id: uuid.UUID
) -> list[TenderVersionDocumentRead]:
    # Номер ревизии — её место среди ревизий документа от старой к новой. Окно считается
    # только по документам состава: остальные ревизии таблицы выборке не нужны.
    numbered = (
        select(
            DocumentRevision.id.label("revision_id"),
            func.row_number()
            .over(
                partition_by=DocumentRevision.document_id,
                order_by=(DocumentRevision.created_at, DocumentRevision.id),
            )
            .label("revision_number"),
        )
        .where(
            DocumentRevision.document_id.in_(
                select(TenderVersionDocument.document_id).where(
                    TenderVersionDocument.tender_version_id == version_id
                )
            )
        )
        .subquery()
    )
    result = await session.execute(
        select(
            TenderVersionDocument,
            Document.display_name,
            DocumentRevision.source_sha256,
            numbered.c.revision_number,
        )
        .join(Document, Document.id == TenderVersionDocument.document_id)
        .join(DocumentRevision, DocumentRevision.id == TenderVersionDocument.document_revision_id)
        .join(numbered, numbered.c.revision_id == DocumentRevision.id)
        .where(TenderVersionDocument.tender_version_id == version_id)
        .order_by(Document.display_name, Document.id)
    )
    return [
        TenderVersionDocumentRead(
            document_id=row.document_id,
            document_name=name,
            document_revision_id=row.document_revision_id,
            revision_number=number,
            source_sha256=sha256,
            section=row.section,
            use_in_model=row.use_in_model,
        )
        for row, name, sha256, number in result.all()
    ]


async def read_version(
    session: AsyncSession, *, project: Project, version: TenderVersion
) -> TenderVersionRead:
    documents = await _composition(session, version.id)
    return TenderVersionRead(
        **_summary(version, len(documents)).model_dump(),
        tender_number=project.external_ref,
        documents=documents,
    )


# --------------------------------------------------------------------- связь с HUBTender


@dataclass(frozen=True, slots=True)
class HubLink:
    tender_id: str
    version: int | None


async def resolve_hub_link(
    project: Project, client: TenderHubClient | None, external_tender_id: str
) -> HubLink:
    """Проверяет строку HUBTender по номеру проекта и берёт у неё номер версии.

    Ручной проект ссылки не имеет: его номер никто не подтверждал. Сервер сам читает тендер,
    а не верит присланному клиентом: номер версии записывается из ответа HUBTender.
    """
    if project.source is not ProjectSource.TENDERHUB or not project.external_ref:
        raise DomainError(ErrorCode.TENDER_VERSION_LINK_FORBIDDEN)
    if client is None:
        raise DomainError(ErrorCode.TENDERHUB_DISABLED)

    tender = await client.get_tender(external_tender_id)
    if tender.tender_number != project.external_ref:
        raise DomainError(ErrorCode.TENDER_VERSION_NUMBER_MISMATCH)
    return HubLink(tender_id=external_tender_id, version=tender.version)


async def hub_candidates(
    project: Project, client: TenderHubClient | None
) -> list[TenderHubCandidateRead]:
    """Строки HUBTender с тем же номером тендера, что и у проекта.

    Поиск HUBTender нестрогий (по подстроке и по названию), поэтому результат фильтруется по
    точному номеру. Ручной проект и выключенная интеграция — пустой список, а не ошибка:
    экран версий обязан работать и без HUBTender.
    """
    if project.source is not ProjectSource.TENDERHUB or not project.external_ref or client is None:
        return []

    rows = await client.list_tenders(search=project.external_ref)
    matching = [row for row in rows if row.tender_number == project.external_ref]
    matching.sort(key=lambda row: (row.version is None, -(row.version or 0)))
    return [
        TenderHubCandidateRead(
            id=row.id, version=row.version, submission_deadline=row.submission_deadline
        )
        for row in matching
    ]


# ---------------------------------------------------------------------------- изменение


def require_draft(version: TenderVersion) -> None:
    if version.status is not TenderVersionStatus.DRAFT:
        raise DomainError(ErrorCode.TENDER_VERSION_FROZEN)


async def _lock_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    await session.execute(select(Project.id).where(Project.id == project_id).with_for_update())


async def _latest_revisions(
    session: AsyncSession, project_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(документ, последняя ревизия) для каждого документа проекта, у которого ревизии есть."""
    result = await session.execute(
        select(DocumentRevision.document_id, DocumentRevision.id)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(Document.project_id == project_id)
        .distinct(DocumentRevision.document_id)
        .order_by(
            DocumentRevision.document_id,
            DocumentRevision.created_at.desc(),
            DocumentRevision.id.desc(),
        )
    )
    return [(document_id, revision_id) for document_id, revision_id in result.all()]


async def create_draft(
    session: AsyncSession,
    *,
    project: Project,
    author_id: uuid.UUID | None,
    label: str | None,
    external_tender_id: str | None,
    client: TenderHubClient | None,
) -> TenderVersion:
    """Черновик с составом из последних ревизий документов проекта."""
    # Сеть — до блокировки: пока HUBTender отвечает, проект никому не мешает.
    link = (
        await resolve_hub_link(project, client, external_tender_id) if external_tender_id else None
    )

    await _lock_project(session, project.id)
    existing = await session.execute(
        select(TenderVersion.id).where(
            TenderVersion.project_id == project.id,
            TenderVersion.status == TenderVersionStatus.DRAFT,
        )
    )
    if existing.first() is not None:
        raise DomainError(ErrorCode.TENDER_VERSION_DRAFT_EXISTS)

    top = await session.execute(
        select(func.coalesce(func.max(TenderVersion.number), 0)).where(
            TenderVersion.project_id == project.id
        )
    )
    version = TenderVersion(
        workspace_id=project.workspace_id,
        project_id=project.id,
        number=int(top.scalar_one()) + 1,
        label=label,
        external_tender_id=link.tender_id if link else None,
        external_version=link.version if link else None,
        status=TenderVersionStatus.DRAFT,
        created_by=author_id,
    )
    session.add(version)
    await session.flush()

    session.add_all(
        TenderVersionDocument(
            tender_version_id=version.id,
            document_id=document_id,
            document_revision_id=revision_id,
            section=None,
            use_in_model=True,
        )
        for document_id, revision_id in await _latest_revisions(session, project.id)
    )
    await session.flush()
    await session.refresh(version)
    return version


async def update_draft(
    session: AsyncSession,
    *,
    project: Project,
    version: TenderVersion,
    fields: set[str],
    label: str | None,
    external_tender_id: str | None,
    client: TenderHubClient | None,
) -> TenderVersion:
    """Меняет подпись и связь с HUBTender: не присланное поле не трогается, null очищает."""
    require_draft(version)

    if "label" in fields:
        version.label = label
    if "external_tender_id" in fields:
        if external_tender_id is None:
            version.external_tender_id = None
            version.external_version = None
        else:
            link = await resolve_hub_link(project, client, external_tender_id)
            version.external_tender_id = link.tender_id
            version.external_version = link.version
    await session.flush()
    return version


async def delete_draft(session: AsyncSession, *, version: TenderVersion) -> None:
    require_draft(version)
    # Состав уходит каскадом внешнего ключа: ORM связи состава не знает.
    await session.delete(version)
    await session.flush()


async def set_document(
    session: AsyncSession,
    *,
    project: Project,
    version: TenderVersion,
    document_id: uuid.UUID,
    payload: TenderVersionDocumentPut,
) -> None:
    """Кладёт в состав ревизию документа или заменяет уже выбранную."""
    require_draft(version)

    document = (
        await session.execute(
            select(Document.id).where(Document.id == document_id, Document.project_id == project.id)
        )
    ).first()
    if document is None:
        # Документ чужого проекта неотличим от несуществующего: существование не раскрываем.
        raise not_found("Документ")

    revision = (
        await session.execute(
            select(DocumentRevision.id).where(
                DocumentRevision.id == payload.document_revision_id,
                DocumentRevision.document_id == document_id,
            )
        )
    ).first()
    if revision is None:
        raise DomainError(ErrorCode.TENDER_VERSION_REVISION_MISMATCH)

    row = (
        await session.execute(
            select(TenderVersionDocument).where(
                TenderVersionDocument.tender_version_id == version.id,
                TenderVersionDocument.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        session.add(
            TenderVersionDocument(
                tender_version_id=version.id,
                document_id=document_id,
                document_revision_id=payload.document_revision_id,
                section=payload.section,
                use_in_model=payload.use_in_model,
            )
        )
    else:
        row.document_revision_id = payload.document_revision_id
        row.section = payload.section
        row.use_in_model = payload.use_in_model
    await session.flush()


async def remove_document(
    session: AsyncSession, *, version: TenderVersion, document_id: uuid.UUID
) -> None:
    require_draft(version)
    row = (
        await session.execute(
            select(TenderVersionDocument).where(
                TenderVersionDocument.tender_version_id == version.id,
                TenderVersionDocument.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise not_found("Документ в составе версии")
    await session.delete(row)
    await session.flush()


async def freeze(
    session: AsyncSession,
    *,
    project: Project,
    version: TenderVersion,
    actor_id: uuid.UUID | None,
) -> TenderVersion:
    """Замораживает черновик: считает отпечаток комплекта и запрещает дальнейшие изменения."""
    require_draft(version)

    result = await session.execute(
        select(TenderVersionDocument, DocumentRevision.source_sha256)
        .join(DocumentRevision, DocumentRevision.id == TenderVersionDocument.document_revision_id)
        .where(TenderVersionDocument.tender_version_id == version.id)
    )
    entries = [
        ManifestEntry(
            document_id=row.document_id,
            document_revision_id=row.document_revision_id,
            source_sha256=sha256 or "",
            section=row.section,
            use_in_model=row.use_in_model,
        )
        for row, sha256 in result.all()
    ]
    if not entries:
        raise DomainError(ErrorCode.TENDER_VERSION_EMPTY)

    version.manifest_sha256 = compute_manifest_sha256(
        tender_number=project.external_ref,
        external_version=version.external_version,
        entries=entries,
    )
    version.frozen_at = datetime.now(UTC)
    version.frozen_by = actor_id
    version.status = TenderVersionStatus.FROZEN
    await session.flush()
    return version
