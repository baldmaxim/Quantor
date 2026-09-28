"""Сбор фактов из распознанного пакета: заявление документа → адаптеры → реестр фактов.

Сбор идёт синхронно в запросе: разбор чистый и быстрый, а нового типа задания контур не
заводит (ADR-0030). Распознавание не меняется и не повторяется — читается готовый текст блоков.

Правила:

- собирать можно только последнюю ревизию документа; при сборе утверждения прежних ревизий
  той же линии отзываются — «заменено новой ревизией»;
- повторный сбор той же ревизии идемпотентен, а исчезнувшие значения отзываются;
- ручные утверждения и решения человека сбор не трогает: у адаптеров свои источники.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.calc.enums import (
    CalcDocumentStage,
    CalcEvidenceKind,
    CalcSourceClass,
    CalcStageBasis,
)
from app.contracts.calc.facts import CalcRegionTableLocator
from app.contracts.calc.inspections import (
    CalcCollectableDocumentRead,
    CalcFactTypeCountRead,
    CalcInspectionCreate,
    CalcInspectionRead,
    CalcInspectionSummary,
)
from app.domain import DocumentKind
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, Project, Region, Sheet
from app.models.calc import CalcFactEvidence, CalcSource, CalcSourceInspection
from app.services.calc.adapters.candidates import CollectionDeclaration, clip
from app.services.calc.adapters.pipeline import (
    EXTRACTOR_VERSION,
    AcceptedCandidate,
    CollectionResult,
    collect,
)
from app.services.calc.adapters.recognized import (
    TEXT_BLOCK,
    RecognizedDocument,
    RecognizedRegion,
    StampSummary,
    class_for_section,
    parse_stamp,
    summarize_stamps,
)
from app.services.calc.facts import registry

SOURCE_CLASS_TITLES: Final[MappingProxyType[CalcSourceClass, str]] = MappingProxyType(
    {
        CalcSourceClass.ARCHITECTURE: "АР",
        CalcSourceClass.APARTMENT_SCHEDULE: "Квартирография",
        CalcSourceClass.ROOM_SCHEDULE: "Экспликация помещений",
        CalcSourceClass.MEP_DESIGN: "Инженерный раздел",
        CalcSourceClass.CONSUMER_TABLE: "Таблица потребителей",
        CalcSourceClass.AIR_EXCHANGE_TABLE: "Таблица воздухообменов",
        CalcSourceClass.FIXTURE_TABLE: "Таблица санприборов",
        CalcSourceClass.EXPLANATORY_NOTE: "Пояснительная записка",
        CalcSourceClass.TECHNICAL_CONDITIONS: "ТУ",
        CalcSourceClass.ADJACENT_TASK: "Задание смежного раздела",
        CalcSourceClass.BRAND_LIST: "Бренд-лист",
        CalcSourceClass.TECHNICAL_REQUIREMENTS: "Технические требования",
        CalcSourceClass.CUSTOMER_VOR: "ВОР Заказчика",
        CalcSourceClass.MANUAL: "Ручной ввод",
    }
)

# Предел длины раздела при импорте legacy-v1 (`services/legacy/markdown.py`): длиннее —
# обрезается без пометки, и таблица в конце блока может оказаться неполной.
_IMPORT_SECTION_LIMIT: Final = 64 * 1024
_STAMP_PATTERN: Final = r"> \*\*Stamp:\*\*[^\n]*"


@dataclass(frozen=True, slots=True)
class RevisionInfo:
    revision: DocumentRevision
    document: Document
    lineage: uuid.UUID
    """Документ, чьи ревизии заменяют друг друга: для распознанного пакета — сам пакет."""
    text_regions: int


async def project_revisions(session: AsyncSession, project_id: uuid.UUID) -> list[RevisionInfo]:
    """Ревизии документов проекта с содержанием — архив пакета сам по себе не документ."""
    rows = (
        await session.execute(
            select(DocumentRevision, Document)
            .join(Document, Document.id == DocumentRevision.document_id)
            .where(Document.project_id == project_id)
        )
    ).all()
    by_id = {revision.id: (revision, document) for revision, document in rows}
    counts: dict[uuid.UUID, int] = {}
    if by_id:
        counted = await session.execute(
            select(Sheet.revision_id, func.count(Region.id))
            .join(Region, Region.sheet_id == Sheet.id)
            .where(Sheet.revision_id.in_(list(by_id)), Region.block_type == TEXT_BLOCK)
            .group_by(Sheet.revision_id)
        )
        counts = dict(counted.tuples().all())
    infos: list[RevisionInfo] = []
    for revision, document in by_id.values():
        if document.document_kind is DocumentKind.RECOGNIZED_PACKAGE:
            continue
        lineage = document.id
        origin = (revision.source_metadata or {}).get("imported_from_revision_id")
        if isinstance(origin, str):
            try:
                package = by_id.get(uuid.UUID(origin))
            except ValueError:
                package = None
            if package is not None:
                lineage = package[1].id
        infos.append(RevisionInfo(revision, document, lineage, counts.get(revision.id, 0)))
    return infos


def latest_revision_ids(infos: Sequence[RevisionInfo]) -> set[uuid.UUID]:
    newest: dict[uuid.UUID, RevisionInfo] = {}
    for info in infos:
        current = newest.get(info.lineage)
        if current is None or (info.revision.created_at, str(info.revision.id)) > (
            current.revision.created_at,
            str(current.revision.id),
        ):
            newest[info.lineage] = info
    return {info.revision.id for info in newest.values()}


async def latest_inspections(
    session: AsyncSession, project_id: uuid.UUID, revision_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, CalcSourceInspection]:
    if not revision_ids:
        return {}
    rows = await session.scalars(
        select(CalcSourceInspection)
        .where(
            CalcSourceInspection.project_id == project_id,
            CalcSourceInspection.document_revision_id.in_(list(revision_ids)),
        )
        .order_by(CalcSourceInspection.document_revision_id, CalcSourceInspection.created_at.desc())
        .distinct(CalcSourceInspection.document_revision_id)
    )
    return {row.document_revision_id: row for row in rows}


async def _stamp_summaries(
    session: AsyncSession, revision_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, StampSummary]:
    """Штамп листа — по одной строке на лист; остальной текст блоков не читается."""
    if not revision_ids:
        return {}
    rows = await session.execute(
        select(Sheet.revision_id, func.substring(Region.raw_content_md, _STAMP_PATTERN))
        .join(Region, Region.sheet_id == Sheet.id)
        .where(
            Sheet.revision_id.in_(list(revision_ids)),
            Region.block_type == TEXT_BLOCK,
            Region.raw_content_md.contains("**Stamp:**"),
        )
        .order_by(Sheet.id)
        .distinct(Sheet.id)
    )
    stamps: dict[uuid.UUID, list[str]] = {}
    for revision_id, line in rows.tuples():
        if line:
            stamps.setdefault(revision_id, []).append(line)
    return {
        revision_id: summarize_stamps(
            [stamp for line in lines if (stamp := parse_stamp(line)) is not None]
        )
        for revision_id, lines in stamps.items()
    }


async def list_collectable_documents(
    session: AsyncSession, *, project: Project
) -> list[CalcCollectableDocumentRead]:
    infos = await project_revisions(session, project.id)
    latest = latest_revision_ids(infos)
    recognized = [info.revision.id for info in infos if info.text_regions > 0]
    stamps = await _stamp_summaries(session, recognized)
    inspections = await latest_inspections(session, project.id, [i.revision.id for i in infos])
    documents: list[CalcCollectableDocumentRead] = []
    for info in infos:
        summary = stamps.get(info.revision.id)
        suggestion = class_for_section(summary.section) if summary and summary.section else None
        inspection = inspections.get(info.revision.id)
        documents.append(
            CalcCollectableDocumentRead(
                document_id=info.document.id,
                document_revision_id=info.revision.id,
                title=info.document.display_name,
                recognized=info.text_regions > 0,
                latest=info.revision.id in latest,
                regions_count=info.text_regions,
                stamp_stage=summary.stage if summary else None,
                stamp_section=summary.section if summary else None,
                suggested_class=suggestion[0] if suggestion else None,
                suggested_discipline=suggestion[1] if suggestion else None,
                last_inspection=(
                    None if inspection is None else CalcInspectionRead.model_validate(inspection)
                ),
                inspection_current=(
                    inspection is not None and inspection.extractor_version == EXTRACTOR_VERSION
                ),
            )
        )
    documents.sort(key=lambda item: (not item.latest, not item.recognized, item.title.casefold()))
    return documents


async def _load_regions(
    session: AsyncSession, revision_id: uuid.UUID
) -> tuple[RecognizedRegion, ...]:
    rows = await session.execute(
        select(
            Region.id,
            Region.sheet_id,
            Sheet.page_index,
            Region.block_type,
            Region.raw_content_md,
            Region.coords_norm,
        )
        .join(Sheet, Sheet.id == Region.sheet_id)
        .where(Sheet.revision_id == revision_id)
        .order_by(Sheet.page_index, Region.ordinal.asc().nullslast(), Region.external_block_id)
    )
    regions: list[RecognizedRegion] = []
    for region_id, sheet_id, page_index, block_type, text, coords in rows.tuples():
        bbox = (
            (float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))
            if isinstance(coords, list) and len(coords) == 4
            else None
        )
        regions.append(
            RecognizedRegion(region_id, sheet_id, page_index, block_type, text or "", bbox)
        )
    return tuple(regions)


def _evidence_rows(
    accepted: AcceptedCandidate, revision_id: uuid.UUID
) -> tuple[CalcFactEvidence, ...]:
    return tuple(
        CalcFactEvidence(
            kind=(
                CalcEvidenceKind.REGION_TABLE
                if isinstance(item.locator, CalcRegionTableLocator)
                else CalcEvidenceKind.REGION_TEXT
            ),
            document_revision_id=revision_id,
            page_index=item.region.page_index,
            sheet_id=item.region.sheet_id,
            bbox=None if item.region.bbox is None else list(item.region.bbox),
            locator=clip(item.label, 200),
            excerpt=clip(item.excerpt, 500),
            region_id=item.region.id,
            region_sha256=item.region.sha256(),
            region_locator=item.locator.model_dump(mode="json"),
        )
        for item in accepted.evidence
    )


async def _adapter_source(
    session: AsyncSession,
    *,
    info: RevisionInfo,
    source_class: CalcSourceClass,
    stage: CalcDocumentStage,
    extractor: str,
    section: str | None,
    user_id: uuid.UUID | None,
) -> CalcSource:
    series = registry.ADAPTER_SERIES_PREFIX + extractor
    existing = await session.scalar(
        select(CalcSource).where(
            CalcSource.project_id == info.document.project_id,
            CalcSource.document_revision_id == info.revision.id,
            CalcSource.source_class == source_class,
            CalcSource.document_stage == stage,
            CalcSource.series_key == series,
        )
    )
    if existing is not None:
        return existing
    source = CalcSource(
        project_id=info.document.project_id,
        source_class=source_class,
        title=clip(f"{SOURCE_CLASS_TITLES[source_class]} · {info.document.display_name}", 200),
        document_stage=stage,
        section_code=section,
        series_key=series,
        document_revision_id=info.revision.id,
        content_sha256=info.revision.source_sha256,
        # ВОР Заказчика — объект сверки: его факты не идут в расчёт никогда.
        calculation_eligible=source_class is not CalcSourceClass.CUSTOMER_VOR,
        note="Сбор фактов из распознанного пакета",
        created_by=user_id,
    )
    session.add(source)
    await session.flush()
    return source


def _limitations(document: RecognizedDocument, result: CollectionResult, vor: bool) -> list[str]:
    notes: list[str] = []
    if result.image_regions:
        notes.append(
            f"Блоков-изображений: {result.image_regions}. Их описание написала модель "
            "распознавалки — наблюдением оно не считается и не используется."
        )
    cut = sum(1 for region in document.regions if len(region.text) >= _IMPORT_SECTION_LIMIT)
    if cut:
        notes.append(
            f"Блоков на пределе импорта 64 КБ: {cut}. Таблицы в конце таких блоков могут быть "
            "неполными."
        )
    if vor:
        notes.append(
            "ВОР Заказчика: приняты только упоминания систем, для сверки. Количества, диаметры и "
            "решения ВОР в реестр не попадают и в расчёт не идут."
        )
    return notes


async def run_inspection(
    session: AsyncSession,
    *,
    project: Project,
    payload: CalcInspectionCreate,
    user_id: uuid.UUID | None,
) -> CalcSourceInspection:
    infos = await project_revisions(session, project.id)
    info = next((i for i in infos if i.revision.id == payload.document_revision_id), None)
    if info is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Ревизия документа не найдена")
    # Одна линия документа собирается одним запросом: иначе два сбора отзывали бы друг друга.
    await registry.lock_name(session, project.id, f"calc:inspect:{info.lineage}")
    if info.text_regions == 0:
        raise DomainError(ErrorCode.CALC_DOCUMENT_NOT_RECOGNIZED)
    if info.revision.id not in latest_revision_ids(infos):
        raise DomainError(ErrorCode.CALC_REVISION_NOT_LATEST)

    document = RecognizedDocument(info.revision.id, await _load_regions(session, info.revision.id))
    declaration = CollectionDeclaration(
        source_class=payload.source_class,
        building=payload.building,
        discipline=payload.discipline,
    )
    # Разбор — чистый код без базы; в потоке, чтобы не держать цикл событий.
    result = await asyncio.to_thread(collect, document, declaration)

    inspection = CalcSourceInspection(
        project_id=project.id,
        document_revision_id=info.revision.id,
        source_class=payload.source_class,
        document_stage=payload.document_stage,
        building=payload.building,
        discipline=payload.discipline,
        extractor_version=EXTRACTOR_VERSION,
        inspected_fact_types=sorted(result.inspected_fact_types),
        summary={},
        created_by=user_id,
    )
    session.add(inspection)
    await session.flush()

    sources: dict[tuple[str, CalcSourceClass], CalcSource] = {}
    claims: list[registry.AdapterClaim] = []
    for accepted in result.accepted:
        candidate = accepted.candidate
        slot = (candidate.extractor, candidate.source_class)
        if slot not in sources:
            sources[slot] = await _adapter_source(
                session,
                info=info,
                source_class=candidate.source_class,
                stage=payload.document_stage,
                extractor=candidate.extractor,
                section=result.stamp.section,
                user_id=user_id,
            )
        claims.append(
            registry.AdapterClaim(
                source=sources[slot],
                fact_type=candidate.fact_type,
                subject=candidate.subject,
                fact_key=accepted.fact_key,
                stated=candidate.value,
                canonical=accepted.canonical,
                method=candidate.method,
                confidence=candidate.confidence,
                note=candidate.note,
                evidence=_evidence_rows(accepted, info.revision.id),
            )
        )

    lineage = [item.revision.id for item in infos if item.lineage == info.lineage]
    retire: dict[uuid.UUID, str] = {}
    for source in await session.scalars(
        select(CalcSource).where(
            CalcSource.project_id == project.id,
            CalcSource.document_revision_id.in_(lineage),
            CalcSource.series_key.like(registry.ADAPTER_SERIES_PREFIX + "%"),
        )
    ):
        retire[source.id] = (
            "Не найдено при повторном сборе документа"
            if source.document_revision_id == info.revision.id
            else "Заменено новой ревизией документа"
        )

    stats = await registry.record_adapter_claims(
        session,
        project_id=project.id,
        inspection_id=inspection.id,
        claims=claims,
        retire=retire,
        author_id=user_id,
    )

    stamp_stage = result.stamp.stage
    summary = CalcInspectionSummary(
        regions_total=result.regions_total,
        text_regions=result.text_regions,
        image_regions=result.image_regions,
        tables_total=result.tables_total,
        tables=list(result.tables),
        candidates=result.candidates_total,
        accepted=len(result.accepted),
        rejected=result.rejected,
        created=stats.created,
        unchanged=stats.unchanged,
        superseded=stats.superseded,
        withdrawn=stats.withdrawn,
        by_fact_type=[
            CalcFactTypeCountRead(fact_type=fact_type, accepted=count)
            for fact_type, count in sorted(
                Counter(item.candidate.fact_type for item in result.accepted).items()
            )
        ],
        issues=list(result.issues),
        stamp_stage=stamp_stage,
        stamp_section=result.stamp.section,
        stage_basis=(
            CalcStageBasis.DECLARED_OVER_STAMP
            if stamp_stage is not None and stamp_stage is not payload.document_stage
            else CalcStageBasis.DECLARED
        ),
        limitations=_limitations(
            document, result, payload.source_class is CalcSourceClass.CUSTOMER_VOR
        ),
    )
    inspection.summary = summary.model_dump(mode="json")
    await session.flush()
    return inspection


async def list_inspections(
    session: AsyncSession, *, project_id: uuid.UUID
) -> Sequence[CalcSourceInspection]:
    rows = await session.scalars(
        select(CalcSourceInspection)
        .where(CalcSourceInspection.project_id == project_id)
        .order_by(CalcSourceInspection.created_at.desc(), CalcSourceInspection.id)
        .limit(200)
    )
    return rows.all()
