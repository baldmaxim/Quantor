"""Реестр фактов: хранение утверждений, конфликты и решения человека.

Выбор значения — в `resolution.py`, без базы. Здесь — только то, что требует транзакции:
запись утверждений, замещение версий, пересчёт конфликта ключа после каждого изменения.

Запись утверждений источника сериализуется блокировкой строки источника: иначе два
одновременных запроса выдали бы одну версию дважды. Любое изменение ключа — утверждение,
проверка, отзыв, решение — идёт под транзакционной блокировкой ключа, взятой до чтения его
утверждений: иначе два одновременных расходящихся утверждения не увидели бы друг друга, и
конфликт не был бы записан. Порядок блокировок: источник → ключ → строки утверждений.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from pydantic import TypeAdapter
from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcConflictStatus,
    CalcEvidenceKind,
    CalcFactMethod,
    CalcFactStatus,
    CalcResolutionState,
    CalcReviewStatus,
    CalcSourceClass,
)
from app.contracts.calc.fact_types import (
    CalcFactTypeDef,
    FactUnitError,
    FactValueError,
    canonical_number,
    canonicalize,
    check_subject,
    fact_key,
    fact_type_def,
)
from app.contracts.calc.facts import (
    CalcAssumptionEvidence,
    CalcDecisionCreate,
    CalcDocumentFragmentEvidence,
    CalcEvidenceCreate,
    CalcFactCreate,
    CalcSourceCreate,
)
from app.contracts.calc.values import CalcFactValue
from app.errors import DomainError, ErrorCode, InvariantError
from app.models import Document, DocumentRevision, Project, Sheet
from app.models.calc import (
    CalcFact,
    CalcFactConflict,
    CalcFactEvidence,
    CalcManualOverride,
    CalcSource,
)
from app.services.calc.facts.policy import policy_for
from app.services.calc.facts.resolution import (
    ClaimView,
    DecisionView,
    FactsSnapshot,
    KeyResolution,
    Resolution,
    build_snapshot,
    resolve,
)

# Методы, которым в ручном вводе нет места: у каждого свой производитель, и он появится в
# своём промте. Ручная запись «вычислено» без запуска расчёта была бы подделкой происхождения.
_METHOD_LATER: Final[dict[CalcFactMethod, str]] = {
    CalcFactMethod.GEOMETRY_MEASURED: "адаптером обмеров (PROMPT 02)",
    CalcFactMethod.INFERRED: "правилом реестра (PROMPT 03)",
    CalcFactMethod.NORMATIVE: "правилом реестра (PROMPT 03)",
    CalcFactMethod.MANUFACTURER_RULE: "правилом реестра (PROMPT 03)",
    CalcFactMethod.CALCULATED: "расчётным ядром (PROMPT 04)",
}

_DEFAULT_CONFIDENCE: Final[dict[CalcFactMethod, CalcConfidence]] = {
    CalcFactMethod.DOCUMENT_EXPLICIT: CalcConfidence.HIGH,
    CalcFactMethod.TABLE_EXPLICIT: CalcConfidence.HIGH,
    CalcFactMethod.MANUAL: CalcConfidence.MEDIUM,
    CalcFactMethod.ASSUMPTION: CalcConfidence.LOW,
}

# Источник, от имени которого человек вводит своё значение при решении конфликта.
DECISIONS_SERIES: Final = "calc:decisions"
# Серии с этим префиксом ведёт сам реестр; пользователь их не заводит.
_SYSTEM_SERIES_PREFIX: Final = "calc:"


def _now() -> datetime:
    return datetime.now(UTC)


async def _lock(session: AsyncSession, project_id: uuid.UUID, name: str) -> None:
    """Транзакционная блокировка имени внутри проекта; снимается при фиксации или откате."""
    digest = hashlib.sha256(f"{project_id}|{name}".encode()).digest()
    await session.execute(
        select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True)))
    )


def _scoped_facts(workspace_id: uuid.UUID) -> Select[tuple[CalcFact]]:
    return (
        select(CalcFact)
        .join(Project, Project.id == CalcFact.project_id)
        .where(Project.workspace_id == workspace_id)
        .options(selectinload(CalcFact.evidence), selectinload(CalcFact.source))
    )


# ------------------------------------------------------------------------------- источники


async def _revision_in_project(
    session: AsyncSession, project_id: uuid.UUID, revision_id: uuid.UUID
) -> DocumentRevision | None:
    result = await session.execute(
        select(DocumentRevision)
        .join(Document, Document.id == DocumentRevision.document_id)
        .where(DocumentRevision.id == revision_id, Document.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def create_source(
    session: AsyncSession,
    *,
    project: Project,
    payload: CalcSourceCreate,
    created_by: uuid.UUID | None,
) -> CalcSource:
    series_key = (payload.series_key or "").strip() or None
    if series_key is not None and series_key.startswith(_SYSTEM_SERIES_PREFIX):
        raise DomainError(
            ErrorCode.CALC_SOURCE_NOT_ALLOWED, "Серии «calc:…» ведёт сам реестр фактов"
        )
    # Источник-документ — это конкретный файл: по его отпечатку одинаковые файлы под разными
    # источниками не считаются двумя подтверждениями. У ручного ввода файла нет.
    manual = payload.source_class is CalcSourceClass.MANUAL
    if manual and payload.document_revision_id is not None:
        raise DomainError(
            ErrorCode.CALC_EVIDENCE_INVALID,
            "У ручного ввода нет файла: документ указывается во фрагменте свидетельства",
        )
    if not manual and payload.document_revision_id is None:
        raise DomainError(
            ErrorCode.CALC_EVIDENCE_REQUIRED, "Источник-документ ссылается на ревизию проекта"
        )

    content_sha256: str | None = None
    if payload.document_revision_id is not None:
        revision = await _revision_in_project(session, project.id, payload.document_revision_id)
        if revision is None:
            raise DomainError(ErrorCode.CALC_EVIDENCE_INVALID, "Ревизия не относится к проекту")
        content_sha256 = revision.source_sha256

    source = CalcSource(
        project_id=project.id,
        source_class=payload.source_class,
        title=payload.title.strip(),
        document_stage=payload.document_stage,
        section_code=(payload.section_code or "").strip() or None,
        series_key=series_key,
        document_revision_id=payload.document_revision_id,
        content_sha256=content_sha256,
        # ВОР Заказчика — объект сверки: его факты не идут в расчёт никогда.
        calculation_eligible=payload.source_class is not CalcSourceClass.CUSTOMER_VOR,
        note=payload.note,
        created_by=created_by,
    )
    session.add(source)
    await session.flush()
    return source


async def list_sources(session: AsyncSession, *, project_id: uuid.UUID) -> Sequence[CalcSource]:
    rows = await session.scalars(
        select(CalcSource)
        .where(CalcSource.project_id == project_id)
        .order_by(CalcSource.created_at, CalcSource.id)
    )
    return rows.all()


async def _source_for_update(
    session: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID
) -> CalcSource | None:
    result = await session.execute(
        select(CalcSource)
        .where(CalcSource.id == source_id, CalcSource.project_id == project_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _decisions_source(
    session: AsyncSession, project: Project, created_by: uuid.UUID | None
) -> CalcSource:
    # Два первых решения проекта одновременно не заведут два источника решений.
    await _lock(session, project.id, DECISIONS_SERIES)
    existing = await session.scalar(
        select(CalcSource)
        .where(CalcSource.project_id == project.id, CalcSource.series_key == DECISIONS_SERIES)
        .order_by(CalcSource.created_at)
        .limit(1)
    )
    if existing is not None:
        return existing
    source = CalcSource(
        project_id=project.id,
        source_class=CalcSourceClass.MANUAL,
        title="Решения инженера по конфликтам",
        series_key=DECISIONS_SERIES,
        calculation_eligible=True,
        created_by=created_by,
    )
    session.add(source)
    await session.flush()
    return source


# ----------------------------------------------------------------------------- утверждения


def _check_method(
    method: CalcFactMethod, source: CalcSource, evidence: Sequence[CalcEvidenceCreate]
) -> None:
    if method in _METHOD_LATER:
        raise DomainError(
            ErrorCode.CALC_METHOD_NOT_AVAILABLE,
            f"Метод {method.value} записывается только {_METHOD_LATER[method]}, не вручную",
        )
    manual_source = source.source_class is CalcSourceClass.MANUAL
    if method in (CalcFactMethod.MANUAL, CalcFactMethod.ASSUMPTION) and not manual_source:
        raise DomainError(
            ErrorCode.CALC_SOURCE_NOT_ALLOWED,
            "Ручной ввод и допущения записываются от источника «ручной ввод»",
        )
    if method in (CalcFactMethod.DOCUMENT_EXPLICIT, CalcFactMethod.TABLE_EXPLICIT):
        if manual_source:
            raise DomainError(
                ErrorCode.CALC_SOURCE_NOT_ALLOWED,
                "Значение из документа записывается от источника-документа",
            )
        fragments = [item for item in evidence if isinstance(item, CalcDocumentFragmentEvidence)]
        if not fragments:
            raise DomainError(
                ErrorCode.CALC_EVIDENCE_REQUIRED,
                "Укажите место в документе, где прочитано значение",
            )
        # Иначе источник «файл А» подтверждался бы фрагментом файла Б.
        if any(item.document_revision_id != source.document_revision_id for item in fragments):
            raise DomainError(
                ErrorCode.CALC_EVIDENCE_INVALID, "Фрагмент должен быть из документа источника"
            )
    if method is CalcFactMethod.ASSUMPTION and not any(
        isinstance(item, CalcAssumptionEvidence) for item in evidence
    ):
        raise DomainError(ErrorCode.CALC_EVIDENCE_REQUIRED, "У допущения должно быть основание")


async def _evidence_rows(
    session: AsyncSession,
    project_id: uuid.UUID,
    evidence: Sequence[CalcEvidenceCreate],
) -> list[CalcFactEvidence]:
    rows: list[CalcFactEvidence] = []
    for item in evidence:
        match item:
            case CalcDocumentFragmentEvidence():
                revision = await _revision_in_project(
                    session, project_id, item.document_revision_id
                )
                if revision is None:
                    raise DomainError(
                        ErrorCode.CALC_EVIDENCE_INVALID, "Ревизия не относится к проекту"
                    )
                if item.sheet_id is not None:
                    sheet = await session.get(Sheet, item.sheet_id)
                    if sheet is None or sheet.revision_id != revision.id:
                        raise DomainError(
                            ErrorCode.CALC_EVIDENCE_INVALID, "Лист не относится к ревизии"
                        )
                rows.append(
                    CalcFactEvidence(
                        kind=CalcEvidenceKind.DOCUMENT_FRAGMENT,
                        document_revision_id=item.document_revision_id,
                        page_index=item.page_index,
                        sheet_id=item.sheet_id,
                        bbox=item.bbox,
                        locator=item.locator,
                        excerpt=item.excerpt,
                    )
                )
            case CalcAssumptionEvidence():
                rows.append(
                    CalcFactEvidence(
                        kind=CalcEvidenceKind.ASSUMPTION_BASIS,
                        basis=item.basis.strip(),
                        alternatives=list(item.alternatives),
                    )
                )
    return rows


async def create_fact(
    session: AsyncSession,
    *,
    project: Project,
    payload: CalcFactCreate,
    author_id: uuid.UUID | None,
) -> CalcFact:
    definition = fact_type_def(payload.fact_type)
    if definition is None:
        raise DomainError(ErrorCode.CALC_FACT_TYPE_UNKNOWN)
    source = await _source_for_update(session, project.id, payload.source_id)
    if source is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Источник не найден")
    if source.series_key == DECISIONS_SERIES:
        # Иначе в серии решений появилось бы значение, за которым нет решения по конфликту.
        raise DomainError(
            ErrorCode.CALC_SOURCE_NOT_ALLOWED,
            "Источник решений пополняется только решением по конфликту",
        )
    return await _record_fact(
        session,
        project_id=project.id,
        source=source,
        definition=definition,
        payload=payload,
        author_id=author_id,
    )


async def _record_fact(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source: CalcSource,
    definition: CalcFactTypeDef,
    payload: CalcFactCreate,
    author_id: uuid.UUID | None,
) -> CalcFact:
    _check_method(payload.method, source, payload.evidence)
    if source.source_class is CalcSourceClass.CUSTOMER_VOR and not (
        definition.customer_vor_admissible
    ):
        # ВОР Заказчика — не эталон: количества и решения из него в реестр не принимаются.
        raise DomainError(
            ErrorCode.CALC_SOURCE_NOT_ALLOWED,
            "Из ВОР Заказчика в реестр принимаются только качественные факты: "
            "количества и решения ВОР сверяются с расчётом, но не входят в него",
        )
    problem = check_subject(definition, payload.subject)
    if problem is not None:
        raise DomainError(ErrorCode.CALC_SUBJECT_INVALID, f"Место факта: {problem}")
    try:
        canonical = canonicalize(definition, payload.value)
    except FactUnitError as error:
        raise DomainError(ErrorCode.CALC_UNIT_MISMATCH, f"Единица: {error}") from error
    except FactValueError as error:
        raise DomainError(ErrorCode.CALC_VALUE_INVALID, f"Значение: {error}") from error

    evidence = await _evidence_rows(session, project_id, payload.evidence)
    if payload.method is CalcFactMethod.MANUAL:
        if author_id is None:
            raise InvariantError("ручной ввод без автора")
        evidence.insert(
            0,
            CalcFactEvidence(
                kind=CalcEvidenceKind.MANUAL_ENTRY, author_id=author_id, basis=payload.note
            ),
        )

    key = fact_key(definition.key, payload.subject)
    await _lock(session, project_id, key)
    previous = await session.scalar(
        select(CalcFact).where(
            CalcFact.project_id == project_id,
            CalcFact.fact_key == key,
            CalcFact.source_id == source.id,
            CalcFact.status == CalcFactStatus.ACTIVE,
        )
    )
    last_version = await session.scalar(
        select(func.max(CalcFact.version)).where(
            CalcFact.project_id == project_id,
            CalcFact.fact_key == key,
            CalcFact.source_id == source.id,
        )
    )
    if previous is not None:
        previous.status = CalcFactStatus.SUPERSEDED
        await session.flush()

    subject = payload.subject
    fact = CalcFact(
        project_id=project_id,
        source_id=source.id,
        source_class=source.source_class,
        fact_type=definition.key,
        building=subject.building,
        section=subject.section,
        floor=subject.floor,
        room=subject.room,
        discipline=subject.discipline,
        system_code=subject.system_code,
        subject_key=subject.key(),
        fact_key=key,
        value_kind=definition.value_kind,
        value=canonical.model_dump(mode="json"),
        stated_value=payload.value.model_dump(mode="json"),
        value_number=canonical_number(canonical),
        unit=definition.unit,
        method=payload.method,
        confidence=payload.confidence or _DEFAULT_CONFIDENCE[payload.method],
        version=(last_version or 0) + 1,
        supersedes_id=None if previous is None else previous.id,
        calculation_eligible=source.calculation_eligible,
        note=payload.note,
        created_by=author_id,
        evidence=evidence,
    )
    session.add(fact)
    await session.flush()
    await refresh_key(session, project_id=project_id, key=key)
    return await _reload(session, fact.id)


async def _reload(session: AsyncSession, fact_id: uuid.UUID) -> CalcFact:
    fact = await session.scalar(
        select(CalcFact)
        .where(CalcFact.id == fact_id)
        .options(selectinload(CalcFact.evidence), selectinload(CalcFact.source))
        .execution_options(populate_existing=True)
    )
    if fact is None:
        raise InvariantError("утверждение пропало внутри транзакции")
    return fact


async def get_fact(
    session: AsyncSession, *, workspace_id: uuid.UUID, fact_id: uuid.UUID
) -> CalcFact | None:
    result = await session.execute(_scoped_facts(workspace_id).where(CalcFact.id == fact_id))
    return result.scalar_one_or_none()


async def list_facts(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    fact_type: str | None = None,
    status: CalcFactStatus | None = None,
) -> Sequence[CalcFact]:
    query = (
        select(CalcFact)
        .where(CalcFact.project_id == project_id)
        .options(selectinload(CalcFact.evidence), selectinload(CalcFact.source))
        .order_by(CalcFact.fact_key, CalcFact.created_at, CalcFact.id)
    )
    if fact_type is not None:
        query = query.where(CalcFact.fact_type == fact_type)
    if status is not None:
        query = query.where(CalcFact.status == status)
    return (await session.scalars(query)).all()


async def _lock_active(session: AsyncSession, fact: CalcFact) -> None:
    """Блокировка ключа и статус, перечитанный под ней: объект мог устареть, пока ждали."""
    await _lock(session, fact.project_id, fact.fact_key)
    await session.refresh(fact, attribute_names=["status"])
    if fact.status is not CalcFactStatus.ACTIVE:
        raise DomainError(ErrorCode.CALC_FACT_NOT_ACTIVE)


async def review_fact(
    session: AsyncSession,
    *,
    fact: CalcFact,
    status: CalcReviewStatus,
    comment: str | None,
    reviewer_id: uuid.UUID,
) -> CalcFact:
    """Проверка человеком: подтверждение или отклонение. Отклонённое в выборе не участвует."""
    await _lock_active(session, fact)
    fact.review_status = status
    fact.review_comment = (comment or "").strip() or None
    fact.reviewed_by = reviewer_id
    fact.reviewed_at = _now()
    await session.flush()
    await refresh_key(session, project_id=fact.project_id, key=fact.fact_key)
    return await _reload(session, fact.id)


async def withdraw_fact(
    session: AsyncSession, *, fact: CalcFact, reason: str, author_id: uuid.UUID
) -> CalcFact:
    """Отзыв вместо удаления: по утверждению мог быть посчитан результат."""
    await _lock_active(session, fact)
    fact.status = CalcFactStatus.WITHDRAWN
    fact.withdrawn_reason = reason.strip()
    fact.withdrawn_at = _now()
    fact.withdrawn_by = author_id
    await session.flush()
    await refresh_key(session, project_id=fact.project_id, key=fact.fact_key)
    return await _reload(session, fact.id)


# ----------------------------------------------------------------------- выбор и конфликты

_VALUE: Final = TypeAdapter[CalcFactValue](CalcFactValue)


def parse_value(raw: dict[str, Any]) -> CalcFactValue:
    """Значение из JSONB в контракт. Хранится ровно то, что выдал `model_dump`."""
    return _VALUE.validate_python(raw)


def _claim_view(fact: CalcFact, source: CalcSource) -> ClaimView:
    return ClaimView(
        id=fact.id,
        value=parse_value(fact.value),
        method=fact.method,
        confidence=fact.confidence,
        source_class=fact.source_class,
        document_stage=source.document_stage,
        source_content_sha256=source.content_sha256,
        review_status=fact.review_status,
        status=fact.status,
        calculation_eligible=fact.calculation_eligible,
        created_at=fact.created_at,
    )


def _decision_view(decision: CalcManualOverride | None) -> DecisionView | None:
    if decision is None:
        return None
    return DecisionView(
        chosen_fact_id=decision.chosen_fact_id, claim_set_hash=decision.claim_set_hash
    )


async def _active_decision(
    session: AsyncSession, project_id: uuid.UUID, key: str
) -> CalcManualOverride | None:
    result = await session.execute(
        select(CalcManualOverride).where(
            CalcManualOverride.project_id == project_id,
            CalcManualOverride.fact_key == key,
            CalcManualOverride.revoked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _resolve_key(
    session: AsyncSession, project_id: uuid.UUID, key: str
) -> tuple[Resolution, CalcFact] | None:
    rows = (
        await session.execute(
            select(CalcFact, CalcSource)
            .join(CalcSource, CalcSource.id == CalcFact.source_id)
            .where(
                CalcFact.project_id == project_id,
                CalcFact.fact_key == key,
                CalcFact.status == CalcFactStatus.ACTIVE,
            )
        )
    ).all()
    if not rows:
        return None
    sample = rows[0][0]
    definition = fact_type_def(sample.fact_type)
    if definition is None:
        raise InvariantError(f"в реестре утверждение неизвестного типа {sample.fact_type}")
    decision = await _active_decision(session, project_id, key)
    resolution = resolve(
        definition,
        [_claim_view(fact, source) for fact, source in rows],
        _decision_view(decision),
        policy_for(definition.key),
    )
    return resolution, sample


def _conflict_status(resolution: Resolution) -> CalcConflictStatus:
    if not resolution.disagreement:
        return CalcConflictStatus.OBSOLETE
    if resolution.state is CalcResolutionState.DECIDED:
        return CalcConflictStatus.RESOLVED
    if resolution.state is CalcResolutionState.DECIDED_STALE:
        return CalcConflictStatus.REOPENED
    return CalcConflictStatus.OPEN


async def refresh_key(
    session: AsyncSession, *, project_id: uuid.UUID, key: str
) -> CalcFactConflict | None:
    """Пересчитывает конфликт ключа после любого изменения его утверждений или решения.

    Вызывающий уже держит блокировку ключа (`_lock`): утверждения читаются под ней.
    """
    resolved = await _resolve_key(session, project_id, key)
    conflict = await session.scalar(
        select(CalcFactConflict)
        .where(CalcFactConflict.project_id == project_id, CalcFactConflict.fact_key == key)
        .with_for_update()
    )
    disagreement = resolved is not None and resolved[0].disagreement
    if conflict is None and not disagreement:
        return None
    if conflict is None and resolved is not None:
        resolution, sample = resolved
        # Страховка на случай вызова без блокировки ключа: вставка не падает, а уступает.
        await session.execute(
            pg_insert(CalcFactConflict)
            .values(
                id=uuid.uuid4(),
                project_id=project_id,
                fact_key=key,
                fact_type=sample.fact_type,
                subject_key=sample.subject_key,
                status=_conflict_status(resolution),
                claim_ids=[str(item) for item in resolution.claim_ids],
                claim_set_hash=resolution.claim_set_hash,
            )
            .on_conflict_do_nothing(constraint="uq_calc_fact_conflicts_key")
        )
        conflict = await session.scalar(
            select(CalcFactConflict).where(
                CalcFactConflict.project_id == project_id, CalcFactConflict.fact_key == key
            )
        )
    if conflict is None:
        raise InvariantError("конфликт ключа не записан")
    if resolved is None:
        conflict.status = CalcConflictStatus.OBSOLETE
        conflict.claim_ids = []
    else:
        resolution = resolved[0]
        conflict.status = _conflict_status(resolution)
        conflict.claim_ids = [str(item) for item in resolution.claim_ids]
        conflict.claim_set_hash = resolution.claim_set_hash
    await session.flush()
    return conflict


async def get_conflict(
    session: AsyncSession, *, workspace_id: uuid.UUID, conflict_id: uuid.UUID
) -> CalcFactConflict | None:
    result = await session.execute(
        select(CalcFactConflict)
        .join(Project, Project.id == CalcFactConflict.project_id)
        .where(Project.workspace_id == workspace_id, CalcFactConflict.id == conflict_id)
    )
    return result.scalar_one_or_none()


async def list_conflicts(
    session: AsyncSession, *, project_id: uuid.UUID, status: CalcConflictStatus | None = None
) -> Sequence[CalcFactConflict]:
    query = (
        select(CalcFactConflict)
        .where(CalcFactConflict.project_id == project_id)
        .order_by(CalcFactConflict.fact_key)
    )
    if status is not None:
        query = query.where(CalcFactConflict.status == status)
    return (await session.scalars(query)).all()


async def conflict_claims(
    session: AsyncSession, conflict: CalcFactConflict
) -> tuple[Sequence[CalcFact], CalcManualOverride | None]:
    """Утверждения конфликта и действующее решение — для показа."""
    ids = [uuid.UUID(item) for item in conflict.claim_ids]
    facts = (
        await session.scalars(
            select(CalcFact)
            .where(CalcFact.id.in_(ids))
            .options(selectinload(CalcFact.evidence), selectinload(CalcFact.source))
            .order_by(CalcFact.created_at, CalcFact.id)
        )
    ).all()
    decision = await _active_decision(session, conflict.project_id, conflict.fact_key)
    return facts, decision


async def decide(
    session: AsyncSession,
    *,
    project: Project,
    conflict: CalcFactConflict,
    payload: CalcDecisionCreate,
    author_id: uuid.UUID,
) -> CalcManualOverride:
    """Решение человека: выбранное утверждение становится действующим значением ключа."""
    await _lock(session, project.id, conflict.fact_key)
    await session.refresh(conflict, attribute_names=["status"])
    if conflict.status is CalcConflictStatus.OBSOLETE:
        raise DomainError(ErrorCode.CALC_CONFLICT_CLOSED)

    if payload.value is not None:
        carrier = await session.scalar(
            select(CalcFact)
            .where(CalcFact.project_id == project.id, CalcFact.fact_key == conflict.fact_key)
            .limit(1)
        )
        if carrier is None:
            raise InvariantError("у конфликта нет утверждений")
        definition = fact_type_def(conflict.fact_type)
        if definition is None:
            raise InvariantError(f"конфликт неизвестного типа {conflict.fact_type}")
        source = await _decisions_source(session, project, author_id)
        own = await _record_fact(
            session,
            project_id=project.id,
            source=source,
            definition=definition,
            payload=CalcFactCreate(
                source_id=source.id,
                fact_type=conflict.fact_type,
                subject=carrier.subject,
                value=payload.value,
                method=CalcFactMethod.MANUAL,
                note=payload.reason,
            ),
            author_id=author_id,
        )
        chosen_id = own.id
    else:
        if payload.chosen_fact_id is None:
            raise InvariantError("решение без выбора прошло проверку контракта")
        chosen_id = payload.chosen_fact_id

    chosen = await session.get(CalcFact, chosen_id)
    if (
        chosen is None
        or chosen.project_id != project.id
        or chosen.fact_key != conflict.fact_key
        or chosen.status is not CalcFactStatus.ACTIVE
        or not chosen.calculation_eligible
        or chosen.review_status is CalcReviewStatus.REJECTED
    ):
        raise DomainError(ErrorCode.CALC_DECISION_INVALID)

    previous = await _active_decision(session, project.id, conflict.fact_key)
    if previous is not None:
        previous.revoked_at = _now()
        previous.revoked_by = author_id
        await session.flush()

    resolved = await _resolve_key(session, project.id, conflict.fact_key)
    if resolved is None:
        raise InvariantError("у конфликта нет действующих утверждений")
    decision = CalcManualOverride(
        project_id=project.id,
        fact_key=conflict.fact_key,
        conflict_id=conflict.id,
        chosen_fact_id=chosen.id,
        reason=payload.reason.strip(),
        claim_set_hash=resolved[0].claim_set_hash,
        decided_by=author_id,
    )
    session.add(decision)
    await session.flush()
    await refresh_key(session, project_id=project.id, key=conflict.fact_key)
    return decision


# ------------------------------------------------------------ действующие значения и снимок


async def resolve_project(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[tuple[KeyResolution, CalcFact]]:
    """Действующее значение каждого ключа проекта и пример утверждения ключа (для места)."""
    rows = (
        await session.execute(
            select(CalcFact, CalcSource)
            .join(CalcSource, CalcSource.id == CalcFact.source_id)
            .where(CalcFact.project_id == project_id, CalcFact.status == CalcFactStatus.ACTIVE)
            .order_by(CalcFact.fact_key, CalcFact.created_at, CalcFact.id)
        )
    ).all()
    decisions = {
        item.fact_key: item
        for item in await session.scalars(
            select(CalcManualOverride).where(
                CalcManualOverride.project_id == project_id,
                CalcManualOverride.revoked_at.is_(None),
            )
        )
    }
    grouped: dict[str, list[tuple[CalcFact, CalcSource]]] = defaultdict(list)
    for fact, source in rows:
        grouped[fact.fact_key].append((fact, source))

    result: list[tuple[KeyResolution, CalcFact]] = []
    for key, pairs in grouped.items():
        sample = pairs[0][0]
        definition = fact_type_def(sample.fact_type)
        if definition is None:
            raise InvariantError(f"в реестре утверждение неизвестного типа {sample.fact_type}")
        resolution = resolve(
            definition,
            [_claim_view(fact, source) for fact, source in pairs],
            _decision_view(decisions.get(key)),
            policy_for(definition.key),
        )
        result.append(
            (
                KeyResolution(
                    fact_key=key,
                    fact_type=sample.fact_type,
                    subject_key=sample.subject_key,
                    resolution=resolution,
                ),
                sample,
            )
        )
    return result


async def conflict_ids_by_key(
    session: AsyncSession, *, project_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    rows = await session.execute(
        select(CalcFactConflict.fact_key, CalcFactConflict.id).where(
            CalcFactConflict.project_id == project_id,
            CalcFactConflict.status != CalcConflictStatus.OBSOLETE,
        )
    )
    return dict(rows.tuples().all())


async def calculation_snapshot(session: AsyncSession, *, project_id: uuid.UUID) -> FactsSnapshot:
    """Снимок фактов для расчётного ядра: только утверждения, допущенные к расчёту.

    Утверждения ВОР Заказчика сюда не попадают по построению (`calculation_eligible = false`
    закреплено ограничением базы), а сборка снимка дополнительно падает, если встретит такое.
    """
    resolved = await resolve_project(session, project_id=project_id)
    return build_snapshot([entry for entry, _ in resolved])
