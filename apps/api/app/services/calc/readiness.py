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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.calc.enums import (
    CalcAssumptionPolicy,
    CalcFactMethod,
    CalcInspectionIssueCode,
    CalcReadinessStatus,
    CalcRequirementLevel,
    CalcRequirementScope,
    CalcResolutionState,
    CalcSourceClass,
)
from app.contracts.calc.fact_types import FACT_TYPES_VERSION, fact_type_def
from app.contracts.calc.inspections import CalcInspectionIssueRead, CalcInspectionSummary
from app.contracts.calc.readiness import (
    CalcDocumentCoverageRead,
    CalcLevelCountRead,
    CalcReadinessRead,
    CalcReadinessRowRead,
    CalcReadinessValueRead,
    CalcSystemReadinessRead,
)
from app.contracts.calc.requirements import CalcInputRequirement, CalcSystemDef
from app.contracts.calc.subjects import CalcFactSubject
from app.domain import DocumentKind
from app.models import Project
from app.models.calc import CalcSource
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
_NOT_SOURCES: Final = frozenset({CalcSourceClass.CUSTOMER_VOR, CalcSourceClass.PROJECT_COMPOSITION})


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
    raw_pdf: bool = False
    """PDF без распознанного текста: сбор его не видит, «не найдено» по нему не доказано."""


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


def _by_assumption(key: KeyState) -> bool:
    chosen = key.resolution.chosen
    return chosen is not None and chosen.method is CalcFactMethod.ASSUMPTION


def _collectable(documents: Sequence[DocumentState]) -> list[DocumentState]:
    """Документы, по которым сбор отвечает «найдено / не найдено».

    ВОР Заказчика — только объект сверки, состав проекта — только перечень документов: их проверка
    не делает исходное данное «не найденным».
    """
    return [
        document
        for document in documents
        if document.recognized and document.latest and document.declared_class not in _NOT_SOURCES
    ]


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

    assumed = [key for key in shown if _by_assumption(key)]
    untaken = [
        issue
        for document in _collectable(documents)
        for issue in document.issues
        if issue.fact_type == requirement.fact_type
        and issue.code is CalcInspectionIssueCode.TABLE_NOT_EXTRACTED
    ]

    if open_keys:
        status = CalcReadinessStatus.CONFLICTED
        reason = f"Источники расходятся: {len(open_keys)} из {len(shown)}"
    elif assumed and requirement.assumption is CalcAssumptionPolicy.NOT_ALLOWED:
        # Допущение записано, но для этого параметра оно не закрывает требование.
        status = CalcReadinessStatus.MANUAL_REQUIRED
        reason = (
            f"Допущение не принимается для этого параметра ({len(assumed)} из {len(shown)}): "
            "нужен факт документа или ручной ввод по документу"
        )
    elif shown:
        status = CalcReadinessStatus.FOUND
    elif requirement.derivable_from and set(requirement.derivable_from) <= (
        available if available is not None else derivable_types(keys, [requirement])
    ):
        status = CalcReadinessStatus.DERIVABLE
        reason = f"Выводится расчётом из: {_titles(requirement.derivable_from)}"
    elif untaken and requirement.fact_type not in DOCUMENT_FACT_TYPES:
        # Таблица в документации есть, извлечение не сделано: значение не отсутствует,
        # а не определено — инженер вводит его по этой таблице.
        status = CalcReadinessStatus.UNKNOWN
        reason = f"{untaken[0].message} — введите значение по этой таблице"
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
        latest = _collectable(documents)
        raw = sum(1 for document in documents if document.latest and document.raw_pdf)
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
            reason = (
                "В проекте нет распознанных документов"
                if not any(document.recognized and document.latest for document in documents)
                else "Распознаны только ВОР Заказчика или состав проекта — "
                "они не источник исходных данных"
            )
        elif pending:
            status = CalcReadinessStatus.NOT_INSPECTED
            reason = f"Не проверено документов: {len(pending)} из {len(latest)}"
        elif undetermined:
            status = CalcReadinessStatus.UNKNOWN
            more = len(undetermined) - 1
            reason = undetermined[0].message + (f" (и ещё {more})" if more else "")
        else:
            status = CalcReadinessStatus.MISSING
            reason = f"Проверено документов: {len(latest)} — не найдено" + (
                f"; PDF без распознавания не проверялись: {raw}" if raw else ""
            )

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
                raw_pdf=info.document.document_kind is DocumentKind.PDF and not info.text_regions,
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
