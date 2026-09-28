"""Реестр правил: черновики, версии, утверждение, отклонение, вывод из действия.

Правило принадлежит рабочему пространству: утверждённая версия меняет расчёты всех проектов
пространства, и чужое пространство её не видит и не меняет.

Жизненный цикл версии:

```text
DRAFT ──approve──► APPROVED ──deprecate──► DEPRECATED
  └───reject────► REJECTED
```

Утверждённая версия не меняется: правка — только новой версией. Утверждение новой версии
выводит прежнюю утверждённую из действия той же транзакцией, поэтому для нового расчёта у
правила одна действующая версия, а старая остаётся доступной по номеру для воспроизведения.
Версию утверждает не её автор и не последний, кто её правил.

Правила старого портала в таблицы не попадают: из карантина можно только завести новый
черновик, который ссылается на старое правило как на происхождение. Сам карантин не меняется.

Реестр фактов этот модуль не читает и не пишет: правило объявляет, какие факты ему нужны, а
снимок фактов готовит расчётное ядро (PROMPT 04).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcLegacyAction,
    CalcRuleStatus,
    CalcRuleType,
)
from app.contracts.calc.rules import (
    CalcLegacyProvenanceRead,
    CalcLegacyRuleRead,
    CalcLegacySource,
    CalcRuleApprove,
    CalcRuleContent,
    CalcRuleCreate,
    CalcRuleDecision,
    CalcRuleDraftUpdate,
    CalcRuleFromLegacy,
    CalcRuleRead,
    CalcRuleReviewRead,
    CalcRuleSummaryRead,
    CalcRuleVersionCreate,
    CalcRuleVersionRead,
)
from app.errors import DomainError, ErrorCode
from app.models import CalcRuleDefinition, CalcRuleReview, CalcRuleVersion
from app.services.calc.rules import validation
from app.services.calc.rules.legacy import LegacyCatalog, load_catalog

_TITLE: Final = 200
_TEXT: Final = 2000


def today() -> date:
    return datetime.now(UTC).date()


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_id(workspace_id: uuid.UUID, rule_key: str) -> int:
    digest = hashlib.sha256(f"calc-rule|{workspace_id}|{rule_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _lock(session: AsyncSession, workspace_id: uuid.UUID, rule_key: str) -> None:
    """Транзакционная блокировка правила: номера версий и переходы идут по одному."""
    await session.execute(select(func.pg_advisory_xact_lock(_lock_id(workspace_id, rule_key))))


# --------------------------------------------------------------- содержание ↔ колонки версии


def content_of(row: CalcRuleVersion, discipline: CalcDiscipline) -> CalcRuleContent:
    """Содержание версии из колонок. Раздел — у определения: он часть ключа правила."""
    return CalcRuleContent.model_validate(
        {
            "title": row.title,
            "description": row.description,
            "rule_type": row.rule_type,
            "discipline": discipline,
            "applicability": row.applicability,
            "inputs": row.inputs,
            "parameters": row.parameters,
            "outputs": row.outputs,
            "dimension_checks": row.dimension_checks,
            "formula": row.formula_text,
            "explanation": row.explanation,
            "implementation_key": row.implementation_key,
            "sources": row.sources,
            "impact": row.impact,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
        }
    )


def _provenance(content: CalcRuleContent, legacy: LegacyCatalog) -> list[CalcLegacyProvenanceRead]:
    found: list[CalcLegacyProvenanceRead] = []
    for legacy_id in validation.legacy_ids(content):
        entry = legacy.get(legacy_id)
        if entry is None:
            continue
        found.append(
            CalcLegacyProvenanceRead(
                legacy_id=entry.legacy_id,
                catalog_version=legacy.catalog_version,
                class_primary=entry.class_primary,
                actions=list(entry.actions),
                hazards=list(entry.hazards),
                group_ids=list(entry.group_ids),
            )
        )
    return found


def _apply(row: CalcRuleVersion, content: CalcRuleContent, legacy: LegacyCatalog) -> None:
    data = content.model_dump(mode="json")
    row.rule_type = content.rule_type
    row.title = content.title
    row.description = content.description
    row.formula_text = content.formula
    row.explanation = content.explanation
    row.implementation_key = content.implementation_key
    row.inputs = data["inputs"]
    row.parameters = data["parameters"]
    row.outputs = data["outputs"]
    row.dimension_checks = data["dimension_checks"]
    row.applicability = data["applicability"]
    row.sources = data["sources"]
    row.impact = content.impact
    row.valid_from = content.valid_from
    row.valid_to = content.valid_to
    row.content_sha256 = validation.content_sha256(content)
    row.legacy_provenance = [item.model_dump(mode="json") for item in _provenance(content, legacy)]


def _check(content: CalcRuleContent, discipline: CalcDiscipline, legacy: LegacyCatalog) -> None:
    problems = validation.content_problems(content, legacy)
    if content.discipline is not discipline:
        problems.append("раздел версии не совпадает с разделом правила: раздел — часть ключа")
    if problems:
        raise DomainError(ErrorCode.CALC_RULE_CONTENT_INVALID, "; ".join(problems))


# ---------------------------------------------------------------------------------- чтение


async def _definition(
    session: AsyncSession, workspace_id: uuid.UUID, rule_key: str
) -> CalcRuleDefinition | None:
    query = (
        select(CalcRuleDefinition)
        .where(
            CalcRuleDefinition.workspace_id == workspace_id,
            CalcRuleDefinition.rule_key == rule_key,
        )
        .options(selectinload(CalcRuleDefinition.versions).selectinload(CalcRuleVersion.reviews))
    )
    # populate_existing: под блокировкой читаем состояние базы, а не копию из сессии.
    result = await session.scalars(query, execution_options={"populate_existing": True})
    return result.one_or_none()


async def _locked(
    session: AsyncSession, workspace_id: uuid.UUID, rule_key: str
) -> CalcRuleDefinition:
    await _lock(session, workspace_id, rule_key)
    definition = await _definition(session, workspace_id, rule_key)
    if definition is None:
        raise LookupError(rule_key)
    return definition


def _version(definition: CalcRuleDefinition, version: int) -> CalcRuleVersion:
    for row in definition.versions:
        if row.version == version:
            return row
    raise LookupError(f"{definition.rule_key}@{version}")


def version_read(
    definition: CalcRuleDefinition, row: CalcRuleVersion, on: date
) -> CalcRuleVersionRead:
    content = content_of(row, definition.discipline)
    return CalcRuleVersionRead(
        rule_key=definition.rule_key,
        version=row.version,
        status=row.status,
        rule_type=row.rule_type,
        content=content,
        content_sha256=row.content_sha256,
        calculation_eligible=validation.calculation_eligible(row.status, content, on),
        notice=validation.notice(row.rule_type),
        change_reason=row.change_reason,
        created_by=row.created_by,
        edited_by=row.edited_by,
        created_at=row.created_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        deprecated_by=row.deprecated_by,
        deprecated_at=row.deprecated_at,
        deprecation_reason=row.deprecation_reason,
        rejected_by=row.rejected_by,
        rejected_at=row.rejected_at,
        rejection_reason=row.rejection_reason,
        legacy_provenance=[
            CalcLegacyProvenanceRead.model_validate(item) for item in row.legacy_provenance
        ],
        reviews=[CalcRuleReviewRead.model_validate(review) for review in row.reviews],
    )


def rule_read(definition: CalcRuleDefinition, on: date) -> CalcRuleRead:
    return CalcRuleRead(
        rule_key=definition.rule_key,
        discipline=definition.discipline,
        created_by=definition.created_by,
        created_at=definition.created_at,
        versions=[version_read(definition, row, on) for row in definition.versions],
    )


async def get_rule(
    session: AsyncSession, *, workspace_id: uuid.UUID, rule_key: str
) -> CalcRuleDefinition | None:
    return await _definition(session, workspace_id, rule_key)


def _summary(definition: CalcRuleDefinition, on: date) -> CalcRuleSummaryRead:
    latest = definition.versions[-1]
    approved = next(
        (row for row in definition.versions if row.status is CalcRuleStatus.APPROVED), None
    )
    shown = approved or latest
    content = content_of(shown, definition.discipline)
    return CalcRuleSummaryRead(
        rule_key=definition.rule_key,
        discipline=definition.discipline,
        title=content.title,
        rule_type=content.rule_type,
        systems=list(content.applicability.systems),
        latest_version=latest.version,
        latest_status=latest.status,
        approved_version=None if approved is None else approved.version,
        calculation_eligible=approved is not None
        and validation.calculation_eligible(approved.status, content, on),
        sources=[validation.source_label(source) for source in content.sources],
        notice=validation.notice(content.rule_type),
    )


async def list_rules(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    discipline: CalcDiscipline | None = None,
    system: str | None = None,
    rule_type: CalcRuleType | None = None,
    status: CalcRuleStatus | None = None,
    on: date,
) -> list[CalcRuleSummaryRead]:
    """Правила пространства: по одной строке, с действующей утверждённой версией, если есть.

    Фильтр по статусу — «есть версия в этом статусе»; по системе и типу — по показанной версии.
    """
    query = (
        select(CalcRuleDefinition)
        .where(CalcRuleDefinition.workspace_id == workspace_id)
        .options(selectinload(CalcRuleDefinition.versions))
        .order_by(CalcRuleDefinition.rule_key)
    )
    if discipline is not None:
        query = query.where(CalcRuleDefinition.discipline == discipline)
    rows: list[CalcRuleSummaryRead] = []
    for definition in (await session.scalars(query)).all():
        if not definition.versions:
            continue
        if status is not None and all(row.status is not status for row in definition.versions):
            continue
        summary = _summary(definition, on)
        if rule_type is not None and summary.rule_type is not rule_type:
            continue
        if system is not None and system not in summary.systems:
            continue
        rows.append(summary)
    return rows


# ---------------------------------------------------------------------------------- запись


async def create_rule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    payload: CalcRuleCreate,
    author: uuid.UUID | None,
) -> tuple[CalcRuleDefinition, CalcRuleVersion]:
    """Новое правило: определение и версия 1 в статусе DRAFT. В расчёт черновик не идёт."""
    legacy = load_catalog()
    await _lock(session, workspace_id, payload.rule_key)
    if await _definition(session, workspace_id, payload.rule_key) is not None:
        raise DomainError(ErrorCode.CALC_RULE_KEY_TAKEN)
    _check(payload.content, payload.content.discipline, legacy)

    definition = CalcRuleDefinition(
        workspace_id=workspace_id,
        rule_key=payload.rule_key,
        discipline=payload.content.discipline,
        created_by=author,
        versions=[],
    )
    row = CalcRuleVersion(
        rule=definition,
        version=1,
        status=CalcRuleStatus.DRAFT,
        created_by=author,
        edited_by=author,
        reviews=[],
    )
    _apply(row, payload.content, legacy)
    session.add(definition)
    await session.flush()
    return definition, row


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def draft_from_legacy(entry: CalcLegacyRuleRead, payload: CalcRuleFromLegacy) -> CalcRuleContent:
    """Содержание черновика по мотивам старого правила.

    Переносится только текст как исходный материал для проверки: формула — для человека,
    замечания разбора — в пояснение, место в старом коде — в происхождение. Реализации нет,
    входы и параметры пусты: их задаёт инженер, иначе черновик не утвердить.
    """
    title = payload.title or f"Черновик по {entry.legacy_id}: {entry.rule_text}"
    return CalcRuleContent(
        title=_clip(title, _TITLE),
        description=_clip(
            f"Исходный материал старого портала {entry.legacy_id} ({entry.section}). "
            f"НЕ ПРОВЕРЕНО: текст перенесён для инженерной проверки, а не как правило. "
            f"Старое правило: {entry.rule_text}",
            _TEXT,
        ),
        rule_type=payload.rule_type,
        discipline=payload.discipline,
        applicability=payload.applicability,
        outputs=payload.outputs,
        formula=_clip(f"Старый портал, {entry.legacy_id}: {entry.rule_text}", _TEXT),
        explanation=_clip(
            f"Допущения и замечания разбора PROMPT 00: {entry.assumptions or '—'}", _TEXT
        ),
        sources=[CalcLegacySource(legacy_ids=[entry.legacy_id], note=_clip(_origin(entry), _TEXT))],
    )


def _origin(entry: CalcLegacyRuleRead) -> str:
    """Место в старом коде: файлы, строки и функции разбора плюс дословная запись разбора."""
    refs = "; ".join(
        ref.file
        + (f":{ref.lines}" if ref.lines else "")
        + (f" ({ref.symbol})" if ref.symbol else "")
        for ref in entry.code_refs
    )
    return f"Место в старом коде: {refs}. Запись разбора: {entry.location}"


async def create_from_legacy(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    entry: CalcLegacyRuleRead,
    payload: CalcRuleFromLegacy,
    author: uuid.UUID | None,
) -> tuple[CalcRuleDefinition, CalcRuleVersion]:
    """Новое правило Quantor из старого: свой ключ, версия 1, DRAFT. Карантин не меняется."""
    if CalcLegacyAction.OUT_OF_SCOPE in entry.actions:
        raise DomainError(ErrorCode.CALC_LEGACY_OUT_OF_SCOPE)
    content = draft_from_legacy(entry, payload)
    return await create_rule(
        session,
        workspace_id=workspace_id,
        payload=CalcRuleCreate(rule_key=payload.rule_key, content=content),
        author=author,
    )


async def update_draft(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    rule_key: str,
    version: int,
    payload: CalcRuleDraftUpdate,
    editor: uuid.UUID | None,
) -> tuple[CalcRuleDefinition, CalcRuleVersion]:
    """Новое содержание черновика. Версия не в статусе DRAFT не меняется — 409."""
    legacy = load_catalog()
    definition = await _locked(session, workspace_id, rule_key)
    row = _version(definition, version)
    if row.status is not CalcRuleStatus.DRAFT:
        raise DomainError(ErrorCode.CALC_RULE_NOT_DRAFT)
    _check(payload.content, definition.discipline, legacy)
    _apply(row, payload.content, legacy)
    row.edited_by = editor
    await session.flush()
    return definition, row


async def create_version(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    rule_key: str,
    payload: CalcRuleVersionCreate,
    author: uuid.UUID | None,
) -> tuple[CalcRuleDefinition, CalcRuleVersion]:
    """Следующая версия-черновик. Без содержания — копия последней версии для правки."""
    legacy = load_catalog()
    definition = await _locked(session, workspace_id, rule_key)
    if any(row.status is CalcRuleStatus.DRAFT for row in definition.versions):
        raise DomainError(ErrorCode.CALC_RULE_DRAFT_EXISTS)
    latest = definition.versions[-1]
    content = payload.content or content_of(latest, definition.discipline)
    _check(content, definition.discipline, legacy)
    row = CalcRuleVersion(
        rule=definition,
        version=latest.version + 1,
        status=CalcRuleStatus.DRAFT,
        change_reason=payload.change_reason,
        created_by=author,
        edited_by=author,
        reviews=[],
    )
    _apply(row, content, legacy)
    # Обратная ссылка в SQLAlchemy 2 объект в сессию не добавляет — добавляем явно.
    session.add(row)
    await session.flush()
    return definition, row


def _review(
    row: CalcRuleVersion,
    to_status: CalcRuleStatus,
    reviewer: uuid.UUID,
    comment: str,
    legacy_review: list[dict[str, object]] | None = None,
) -> CalcRuleReview:
    return CalcRuleReview(
        rule_version_id=row.id,
        from_status=row.status,
        to_status=to_status,
        reviewer_id=reviewer,
        comment=comment,
        legacy_review=legacy_review or [],
    )


async def approve(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    rule_key: str,
    version: int,
    payload: CalcRuleApprove,
    reviewer: uuid.UUID,
) -> tuple[CalcRuleDefinition, CalcRuleVersion, CalcRuleVersion | None]:
    """DRAFT → APPROVED. Прежняя утверждённая версия выводится из действия той же транзакцией.

    Возвращает определение, утверждённую версию и выведенную из действия, если была.
    """
    legacy = load_catalog()
    definition = await _locked(session, workspace_id, rule_key)
    row = _version(definition, version)
    if row.status is not CalcRuleStatus.DRAFT:
        raise DomainError(ErrorCode.CALC_RULE_TRANSITION_INVALID)
    if reviewer in (row.created_by, row.edited_by):
        raise DomainError(ErrorCode.CALC_RULE_SELF_APPROVAL)
    content = content_of(row, definition.discipline)
    problems = validation.approval_problems(content, payload, legacy)
    if problems:
        raise DomainError(ErrorCode.CALC_RULE_APPROVAL_BLOCKED, "; ".join(problems))

    now = _now()
    previous = next(
        (item for item in definition.versions if item.status is CalcRuleStatus.APPROVED), None
    )
    if previous is not None:
        reason = f"Заменена утверждённой версией {row.version}"
        session.add(_review(previous, CalcRuleStatus.DEPRECATED, reviewer, reason))
        previous.status = CalcRuleStatus.DEPRECATED
        previous.deprecated_at = now
        previous.deprecated_by = reviewer
        previous.deprecation_reason = reason
        # Сначала вывод прежней: одна утверждённая версия на правило — уникальный индекс.
        await session.flush()

    session.add(
        _review(
            row,
            CalcRuleStatus.APPROVED,
            reviewer,
            payload.comment,
            [item.model_dump(mode="json") for item in payload.legacy_review],
        )
    )
    row.status = CalcRuleStatus.APPROVED
    row.approved_at = now
    row.approved_by = reviewer
    # Снимок опасностей — на момент утверждения: по нему и шёл разбор.
    row.legacy_provenance = [item.model_dump(mode="json") for item in _provenance(content, legacy)]
    await session.flush()
    await session.refresh(row, attribute_names=["reviews"])
    if previous is not None:
        await session.refresh(previous, attribute_names=["reviews"])
    return definition, row, previous


async def reject(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    rule_key: str,
    version: int,
    payload: CalcRuleDecision,
    reviewer: uuid.UUID,
) -> tuple[CalcRuleDefinition, CalcRuleVersion]:
    """DRAFT → REJECTED с причиной. Отклонённая версия остаётся в истории."""
    definition = await _locked(session, workspace_id, rule_key)
    row = _version(definition, version)
    if row.status is not CalcRuleStatus.DRAFT:
        raise DomainError(ErrorCode.CALC_RULE_TRANSITION_INVALID)
    session.add(_review(row, CalcRuleStatus.REJECTED, reviewer, payload.comment))
    row.status = CalcRuleStatus.REJECTED
    row.rejected_at = _now()
    row.rejected_by = reviewer
    row.rejection_reason = payload.comment
    await session.flush()
    await session.refresh(row, attribute_names=["reviews"])
    return definition, row


async def deprecate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    rule_key: str,
    version: int,
    payload: CalcRuleDecision,
    reviewer: uuid.UUID,
) -> tuple[CalcRuleDefinition, CalcRuleVersion]:
    """APPROVED → DEPRECATED с причиной. Версия остаётся доступной по номеру."""
    definition = await _locked(session, workspace_id, rule_key)
    row = _version(definition, version)
    if row.status is not CalcRuleStatus.APPROVED:
        raise DomainError(ErrorCode.CALC_RULE_TRANSITION_INVALID)
    session.add(_review(row, CalcRuleStatus.DEPRECATED, reviewer, payload.comment))
    row.status = CalcRuleStatus.DEPRECATED
    row.deprecated_at = _now()
    row.deprecated_by = reviewer
    row.deprecation_reason = payload.comment
    await session.flush()
    await session.refresh(row, attribute_names=["reviews"])
    return definition, row
