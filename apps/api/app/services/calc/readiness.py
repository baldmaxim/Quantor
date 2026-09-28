"""Матрица готовности исходных данных и таблица фактов экрана «Исходные данные» (PROMPT 02).

Представление, считаемое при чтении: реестр фактов + записи о сборе + каталог требований.
Главное — различать состояния, которые в интерфейсе легко спутать:

- MISSING — все распознанные документы проверены, значения нет;
- NOT_INSPECTED — документ есть, но ещё не проверялся на этот факт;
- UNKNOWN — определить сейчас нельзя: значение не привязано к месту, таблица не разобрана;
- CONFLICTED — значения есть, но расходятся.

MISSING — не ноль: у отсутствующего значения нет числа ни в ответе, ни в снимке для ядра.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.enums import (
    CalcFactStatus,
    CalcFactUsage,
    CalcInspectionIssueCode,
    CalcReadinessStatus,
    CalcRequirementLevel,
    CalcRequirementScope,
    CalcResolutionState,
    CalcReviewStatus,
    CalcSourceClass,
)
from app.contracts.calc.fact_types import FACT_TYPES_VERSION, fact_type_def, values_agree
from app.contracts.calc.facts import CalcFactRead
from app.contracts.calc.inspections import CalcInspectionIssueRead, CalcInspectionSummary
from app.contracts.calc.readiness import (
    CalcDocumentCoverageRead,
    CalcInputFactPage,
    CalcInputFactRead,
    CalcLevelCountRead,
    CalcReadinessRead,
    CalcReadinessRowRead,
    CalcReadinessValueRead,
    CalcSystemReadinessRead,
)
from app.contracts.calc.requirements import CalcInputRequirement, CalcSystemDef
from app.contracts.calc.subjects import CalcFactSubject
from app.errors import InvariantError
from app.models import Project
from app.models.calc import CalcFact, CalcSource
from app.services.calc import inspections
from app.services.calc.adapters.pipeline import DOCUMENT_FACT_TYPES
from app.services.calc.facts import registry
from app.services.calc.facts.resolution import Resolution

_VALUED: Final = frozenset(
    {CalcResolutionState.SINGLE, CalcResolutionState.CORROBORATED, CalcResolutionState.DECIDED}
)
_OPEN: Final = frozenset(
    {
        CalcResolutionState.UNRESOLVED,
        CalcResolutionState.AUTO_PREFERRED,
        CalcResolutionState.DECIDED_STALE,
    }
)
_UNDETERMINED: Final = frozenset(
    {
        CalcInspectionIssueCode.UNSCOPED,
        CalcInspectionIssueCode.TABLE_NOT_EXTRACTED,
        CalcInspectionIssueCode.SELF_CONTRADICTION,
        CalcInspectionIssueCode.UNIT_MISSING,
        CalcInspectionIssueCode.UNIT_MISMATCH,
        CalcInspectionIssueCode.APPROXIMATE,
        CalcInspectionIssueCode.DISCIPLINE_MISSING,
        CalcInspectionIssueCode.SCOPE_MISMATCH,
        CalcInspectionIssueCode.UNMAPPED_LABEL,
        CalcInspectionIssueCode.VALUE_INVALID,
    }
)
_SATISFIED: Final = frozenset({CalcReadinessStatus.FOUND, CalcReadinessStatus.DERIVABLE})


@dataclass(frozen=True, slots=True)
class KeyState:
    """Ключ реестра глазами матрицы: действующее значение и откуда оно."""

    fact_key: str
    fact_type: str
    subject: CalcFactSubject
    resolution: Resolution
    conflict_id: uuid.UUID | None
    source_title: str | None
    source_class: CalcSourceClass | None


@dataclass(frozen=True, slots=True)
class DocumentState:
    """Последняя ревизия документа глазами матрицы."""

    recognized: bool
    latest: bool
    inspected_fact_types: frozenset[str] | None
    """Пусто — сбора не было."""
    declared_class: CalcSourceClass | None
    issues: tuple[CalcInspectionIssueRead, ...]


def _matches(requirement: CalcInputRequirement, system_code: str, key: KeyState) -> bool:
    if key.fact_type != requirement.fact_type:
        return False
    if requirement.scope is CalcRequirementScope.SYSTEM:
        return key.subject.system_code == system_code
    return True


def _value_read(key: KeyState) -> CalcReadinessValueRead:
    chosen = key.resolution.chosen
    return CalcReadinessValueRead(
        fact_key=key.fact_key,
        subject=key.subject,
        state=key.resolution.state,
        value=key.resolution.value,
        chosen_fact_id=None if chosen is None else chosen.id,
        source_title=key.source_title,
        source_class=key.source_class,
        method=None if chosen is None else chosen.method,
        confidence=None if chosen is None else chosen.confidence,
        conflict_id=key.conflict_id,
    )


def _titles(fact_types: Sequence[str]) -> str:
    names: list[str] = []
    for fact_type in fact_types:
        definition = fact_type_def(fact_type)
        names.append(definition.title.lower() if definition else fact_type)
    return ", ".join(names)


def derivable_types(
    keys: Sequence[KeyState], requirements: Sequence[CalcInputRequirement]
) -> frozenset[str]:
    """Типы фактов, значение которых есть или выводимо — с учётом цепочек вывода.

    Высоты этажей выводятся из отметок, высота здания — из отметок и высот этажей: если есть
    отметки, выводимы обе. Вывод выполнит расчёт; здесь только ответ «из чего».
    """
    available = {key.fact_type for key in keys if key.resolution.state in _VALUED}
    changed = True
    while changed:
        changed = False
        for requirement in requirements:
            if (
                requirement.derivable_from
                and requirement.fact_type not in available
                and set(requirement.derivable_from) <= available
            ):
                available.add(requirement.fact_type)
                changed = True
    return frozenset(available)


def evaluate(
    requirement: CalcInputRequirement,
    system_code: str,
    keys: Sequence[KeyState],
    documents: Sequence[DocumentState],
    present_classes: frozenset[CalcSourceClass],
    class_titles: Callable[[CalcSourceClass], str],
    available: frozenset[str] | None = None,
) -> CalcReadinessRowRead:
    matching = [key for key in keys if _matches(requirement, system_code, key)]
    shown = [key for key in matching if key.resolution.state in _VALUED | _OPEN]
    open_keys = [key for key in shown if key.resolution.state in _OPEN]
    reason: str | None = None

    if open_keys:
        status = CalcReadinessStatus.CONFLICTED
        reason = f"Источники расходятся: {len(open_keys)} из {len(shown)}"
    elif shown:
        status = CalcReadinessStatus.FOUND
    elif requirement.derivable_from and set(requirement.derivable_from) <= (
        available if available is not None else derivable_types(keys, [requirement])
    ):
        status = CalcReadinessStatus.DERIVABLE
        reason = f"Выводится расчётом из: {_titles(requirement.derivable_from)}"
    elif requirement.manual_when_sources_absent and not (
        set(requirement.expected_sources) & present_classes
    ):
        status = CalcReadinessStatus.MANUAL_REQUIRED
        missing = " или ".join(class_titles(item) for item in requirement.expected_sources)
        reason = f"{missing} в проекте не найдены — нужен ручной ввод"
    elif requirement.fact_type not in DOCUMENT_FACT_TYPES:
        status = CalcReadinessStatus.MANUAL_REQUIRED
        where = ", ".join(class_titles(item) for item in requirement.expected_sources)
        reason = "Автоматически не извлекается — нужен ручной ввод" + (
            f" (обычно: {where})" if where else ""
        )
    else:
        latest = [document for document in documents if document.recognized and document.latest]
        pending = [
            document
            for document in latest
            if document.inspected_fact_types is None
            or requirement.fact_type not in document.inspected_fact_types
        ]
        undetermined = [
            issue
            for document in latest
            for issue in document.issues
            if issue.fact_type == requirement.fact_type and issue.code in _UNDETERMINED
        ]
        if not latest:
            status = CalcReadinessStatus.UNKNOWN
            reason = "В проекте нет распознанных документов"
        elif pending:
            status = CalcReadinessStatus.NOT_INSPECTED
            reason = f"Не проверено документов: {len(pending)} из {len(latest)}"
        elif undetermined:
            status = CalcReadinessStatus.UNKNOWN
            more = len(undetermined) - 1
            reason = undetermined[0].message + (f" (и ещё {more})" if more else "")
        else:
            status = CalcReadinessStatus.MISSING
            reason = f"Проверено документов: {len(latest)} — не найдено"

    return CalcReadinessRowRead(
        requirement_id=requirement.id,
        title=requirement.title,
        group=requirement.group,
        fact_type=requirement.fact_type,
        level=requirement.level,
        assumption=requirement.assumption,
        status=status,
        reason=reason,
        values=[_value_read(key) for key in shown],
        excluded_count=sum(len(key.resolution.excluded_ids) for key in matching),
        derivable_from=list(requirement.derivable_from),
    )


def compute_readiness(
    *,
    version: str,
    systems: Sequence[CalcSystemDef],
    requirements_for: Callable[[str], Sequence[CalcInputRequirement]],
    keys: Sequence[KeyState],
    documents: Sequence[DocumentState],
    present_classes: frozenset[CalcSourceClass],
    class_titles: Callable[[CalcSourceClass], str],
) -> CalcReadinessRead:
    result: list[CalcSystemReadinessRead] = []
    catalog = [item for system in systems for item in requirements_for(system.code)]
    available = derivable_types(keys, catalog)
    for system in systems:
        rows = [
            evaluate(
                requirement,
                system.code,
                keys,
                documents,
                present_classes,
                class_titles,
                available,
            )
            for requirement in requirements_for(system.code)
        ]
        counts = [
            CalcLevelCountRead(
                level=level,
                satisfied=sum(1 for row in rows if row.level is level and row.status in _SATISFIED),
                total=sum(1 for row in rows if row.level is level),
            )
            for level in CalcRequirementLevel
        ]
        result.append(
            CalcSystemReadinessRead(
                discipline=system.discipline,
                system_code=system.code,
                title=system.title,
                counts=[count for count in counts if count.total],
                rows=rows,
            )
        )
    latest = [document for document in documents if document.latest]
    recognized = [document for document in latest if document.recognized]
    inspected = [document for document in recognized if document.inspected_fact_types is not None]
    return CalcReadinessRead(
        requirements_version=version,
        fact_types_version=FACT_TYPES_VERSION,
        systems=result,
        documents=CalcDocumentCoverageRead(
            recognized=len(recognized),
            inspected=len(inspected),
            not_inspected=len(recognized) - len(inspected),
            without_recognition=len(latest) - len(recognized),
        ),
    )


# ------------------------------------------------------------------------------ из базы


async def _key_states(session: AsyncSession, project_id: uuid.UUID) -> list[KeyState]:
    resolved = await registry.resolve_project(session, project_id=project_id)
    conflicts = await registry.conflict_ids_by_key(session, project_id=project_id)
    source_ids = {
        entry.resolution.chosen.source_id
        for entry, _ in resolved
        if entry.resolution.chosen is not None and entry.resolution.chosen.source_id is not None
    }
    sources: dict[uuid.UUID, CalcSource] = {}
    if source_ids:
        sources = {
            source.id: source
            for source in await session.scalars(
                select(CalcSource).where(CalcSource.id.in_(source_ids))
            )
        }
    states: list[KeyState] = []
    for entry, sample in resolved:
        chosen = entry.resolution.chosen
        source = sources.get(chosen.source_id) if chosen and chosen.source_id else None
        states.append(
            KeyState(
                fact_key=entry.fact_key,
                fact_type=entry.fact_type,
                subject=sample.subject,
                resolution=entry.resolution,
                conflict_id=conflicts.get(entry.fact_key),
                source_title=None if source is None else source.title,
                source_class=None if source is None else source.source_class,
            )
        )
    return states


async def _document_states(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[list[DocumentState], frozenset[CalcSourceClass]]:
    infos = await inspections.project_revisions(session, project_id)
    latest = inspections.latest_revision_ids(infos)
    last = await inspections.latest_inspections(
        session, project_id, [info.revision.id for info in infos if info.revision.id in latest]
    )
    documents: list[DocumentState] = []
    for info in infos:
        if info.revision.id not in latest:
            continue
        inspection = last.get(info.revision.id)
        documents.append(
            DocumentState(
                recognized=info.text_regions > 0,
                latest=True,
                inspected_fact_types=(
                    None if inspection is None else frozenset(inspection.inspected_fact_types)
                ),
                declared_class=None if inspection is None else inspection.source_class,
                issues=(
                    ()
                    if inspection is None
                    else tuple(CalcInspectionSummary.model_validate(inspection.summary).issues)
                ),
            )
        )
    declared = {document.declared_class for document in documents if document.declared_class}
    manual = set(
        await session.scalars(
            select(CalcSource.source_class)
            .where(
                CalcSource.project_id == project_id,
                or_(
                    CalcSource.series_key.is_(None),
                    CalcSource.series_key.not_like(registry.ADAPTER_SERIES_PREFIX + "%"),
                ),
            )
            .distinct()
        )
    )
    return documents, frozenset(declared | manual)


async def load_readiness(
    session: AsyncSession,
    *,
    project: Project,
    version: str,
    systems: Sequence[CalcSystemDef],
    requirements_for: Callable[[str], Sequence[CalcInputRequirement]],
) -> CalcReadinessRead:
    keys = await _key_states(session, project.id)
    documents, present = await _document_states(session, project.id)
    return compute_readiness(
        version=version,
        systems=systems,
        requirements_for=requirements_for,
        keys=keys,
        documents=documents,
        present_classes=present,
        class_titles=lambda item: inspections.SOURCE_CLASS_TITLES[item],
    )


# ------------------------------------------------------------------------ таблица фактов


def usage_of(fact: CalcFact, resolution: Resolution | None) -> CalcFactUsage:
    """Идёт ли утверждение в расчёт — ответ сервера, а не вывод интерфейса."""
    if fact.review_status is CalcReviewStatus.REJECTED:
        return CalcFactUsage.REJECTED
    if not fact.calculation_eligible:
        return CalcFactUsage.EXCLUDED_VOR
    if resolution is None:
        raise InvariantError("у действующего утверждения нет выбора по ключу")
    if resolution.chosen is not None and resolution.chosen.id == fact.id:
        return CalcFactUsage.USED
    if resolution.state is CalcResolutionState.UNRESOLVED:
        return CalcFactUsage.CONFLICT
    definition = fact_type_def(fact.fact_type)
    if (
        resolution.value is not None
        and definition is not None
        and values_agree(definition, registry.parse_value(fact.value), resolution.value)
    ):
        return CalcFactUsage.AGREES
    return CalcFactUsage.NOT_CHOSEN


async def list_input_facts(
    session: AsyncSession,
    *,
    project: Project,
    fact_type: str | None,
    limit: int,
    offset: int,
) -> CalcInputFactPage:
    conditions = [CalcFact.project_id == project.id, CalcFact.status == CalcFactStatus.ACTIVE]
    if fact_type is not None:
        conditions.append(CalcFact.fact_type == fact_type)
    total = await session.scalar(select(func.count(CalcFact.id)).where(*conditions))
    facts = (
        await session.scalars(
            select(CalcFact)
            .where(*conditions)
            .options(selectinload(CalcFact.evidence), selectinload(CalcFact.source))
            .order_by(CalcFact.fact_type, CalcFact.subject_key, CalcFact.created_at, CalcFact.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    resolutions = {
        entry.fact_key: entry.resolution
        for entry, _ in await registry.resolve_project(session, project_id=project.id)
    }
    items: list[CalcInputFactRead] = []
    for fact in facts:
        definition = fact_type_def(fact.fact_type)
        items.append(
            CalcInputFactRead(
                fact=CalcFactRead.model_validate(fact),
                fact_type_title=fact.fact_type if definition is None else definition.title,
                source_title=fact.source.title,
                usage=usage_of(fact, resolutions.get(fact.fact_key)),
            )
        )
    return CalcInputFactPage(items=items, total=total or 0)
