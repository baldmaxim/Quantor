"""Входы запуска из реестров: снимок фактов и точные версии правил. Только чтение.

Снимок строже, чем «действующее значение» реестра фактов. В расчёт идёт только значение, в
котором нет открытого вопроса:

| Состояние ключа          | В снимке | Причина блокировки                                   |
| ------------------------ | -------- | ---------------------------------------------------- |
| одно, согласные, решено  | да       | —                                                    |
| решение устарело         | нет      | FACT_DECISION_STALE — после решения пришли новые     |
| по политике, конфликт    | нет      | FACT_CONFLICT — «наиболее вероятное» не выбирается   |
| расхождение без решения  | нет      | FACT_CONFLICT                                        |
| только не допущенные     | нет      | FACT_EXCLUDED — ВОР Заказчика или отклонённые        |
| утверждений нет          | нет      | FACT_MISSING — отсутствие не ноль                    |

Правило для нового запуска — только утверждённая версия, действующая на дату запуска.
Черновик, отклонённая и устаревшая версии не выбираются; правил старого портала в таблицах
реестра нет вовсе.

Члены набора (PROMPT 06) — все ключи реестра, чьё место подходит набору, с тем же строгим
допуском: конфликт одного этажа блокирует шаг набора, а не превращается в «среднее».
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.engine import CalcEvidenceRef, CalcSnapshot, CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcResolutionState,
    CalcRuleStatus,
    CalcSourceClass,
)
from app.errors import InvariantError
from app.models import CalcFact, CalcRuleDefinition
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.plan_types import (
    Absence,
    FactOutcome,
    ResolvedRule,
    RuleOutcome,
    SeriesRequirement,
    split_fact_key,
)
from app.services.calc.facts.registry import parse_value, resolve_project
from app.services.calc.facts.resolution import KeyResolution
from app.services.calc.rules import registry as rules_registry
from app.services.calc.rules import validation

RUN_SNAPSHOT_VERSION: Final = "calc.run_snapshot.v1"

_ADMITTED: Final = frozenset(
    {
        CalcResolutionState.SINGLE,
        CalcResolutionState.CORROBORATED,
        CalcResolutionState.DECIDED,
    }
)


def _absence(entry: KeyResolution) -> Absence | None:
    resolution = entry.resolution
    match resolution.state:
        case CalcResolutionState.UNRESOLVED:
            return Absence(
                CalcBlockCode.FACT_CONFLICT, "источники расходятся, решения человека нет"
            )
        case CalcResolutionState.AUTO_PREFERRED:
            return Absence(
                CalcBlockCode.FACT_CONFLICT,
                "источники расходятся: значение по политике приоритета не выбирается "
                "автоматически — нужно решение человека",
            )
        case CalcResolutionState.DECIDED_STALE:
            return Absence(
                CalcBlockCode.FACT_DECISION_STALE,
                "после решения человека появились новые утверждения — решение нужно подтвердить",
            )
        case CalcResolutionState.MISSING:
            if resolution.excluded_ids:
                return Absence(
                    CalcBlockCode.FACT_EXCLUDED,
                    "есть только утверждения, не допущенные к расчёту (ВОР Заказчика)",
                )
            return Absence(CalcBlockCode.FACT_MISSING, "все утверждения отклонены проверкой")
    return None


def _evidence(fact: CalcFact) -> list[CalcEvidenceRef]:
    return [
        CalcEvidenceRef(
            id=row.id,
            kind=row.kind,
            document_revision_id=row.document_revision_id,
            page_index=row.page_index,
            sheet_id=row.sheet_id,
            locator=row.locator,
            region_id=row.region_id,
            region_sha256=row.region_sha256,
        )
        for row in sorted(fact.evidence, key=lambda item: str(item.id))
    ]


def _item(entry: KeyResolution, fact: CalcFact) -> CalcSnapshotItem:
    resolution = entry.resolution
    if not fact.calculation_eligible or fact.source_class is CalcSourceClass.CUSTOMER_VOR:
        raise InvariantError("в снимок расчёта попало утверждение, не допущенное к расчёту")
    value = parse_value(fact.value)
    stated = parse_value(fact.stated_value)
    claim_ids = sorted(resolution.claim_ids, key=str)
    body = {
        "fact_key": entry.fact_key,
        "fact_id": str(fact.id),
        "fact_version": fact.version,
        "value": value.model_dump(mode="json"),
        "stated_value": stated.model_dump(mode="json"),
        "method": fact.method.value,
        "confidence": fact.confidence.value,
        "review_status": fact.review_status.value,
        "resolution_state": resolution.state.value,
        "claim_ids": [str(item) for item in claim_ids],
    }
    return CalcSnapshotItem(
        fact_key=entry.fact_key,
        fact_type=fact.fact_type,
        subject=fact.subject,
        fact_id=fact.id,
        fact_version=fact.version,
        value=value,
        stated_value=stated,
        method=fact.method,
        confidence=fact.confidence,
        review_status=fact.review_status,
        resolution_state=resolution.state,
        source_id=fact.source_id,
        source_class=fact.source_class,
        claim_ids=claim_ids,
        evidence=_evidence(fact),
        calculation_eligible=True,
        item_sha256=canonical_sha256(body),
    )


async def fact_outcomes(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    keys: Iterable[str],
    series: Iterable[SeriesRequirement] = (),
) -> dict[str, FactOutcome]:
    """Для каждого нужного ключа и члена набора — значение или причина его отсутствия."""
    wanted = set(keys)
    requirements = tuple(series)
    resolved: dict[str, KeyResolution] = {}
    for found, _ in await resolve_project(session, project_id=project_id):
        parsed = split_fact_key(found.fact_key) if requirements else None
        member = parsed is not None and any(item.matches(*parsed) for item in requirements)
        if found.fact_key in wanted or member:
            resolved[found.fact_key] = found
    wanted |= set(resolved)
    outcomes: dict[str, FactOutcome] = {}
    chosen: dict[uuid.UUID, KeyResolution] = {}
    for key in sorted(wanted):
        if key not in resolved:
            outcomes[key] = Absence(CalcBlockCode.FACT_MISSING, "в реестре фактов значения нет")
            continue
        entry = resolved[key]
        absence = _absence(entry)
        if absence is not None:
            outcomes[key] = absence
            continue
        claim = entry.resolution.chosen
        if entry.resolution.state not in _ADMITTED or claim is None:
            raise InvariantError(f"ключ {key}: состояние {entry.resolution.state} без значения")
        chosen[claim.id] = entry
    if chosen:
        facts = await session.scalars(
            select(CalcFact)
            .where(CalcFact.id.in_(list(chosen)))
            .options(selectinload(CalcFact.evidence))
        )
        for fact in facts:
            entry = chosen[fact.id]
            outcomes[entry.fact_key] = _item(entry, fact)
    return outcomes


def snapshot_of(items: Iterable[CalcSnapshotItem]) -> CalcSnapshot:
    ordered = sorted(items, key=lambda item: item.fact_key)
    return CalcSnapshot(
        version=RUN_SNAPSHOT_VERSION,
        items=ordered,
        sha256=canonical_sha256(
            {"version": RUN_SNAPSHOT_VERSION, "items": [item.item_sha256 for item in ordered]}
        ),
    )


async def rule_outcomes(
    session: AsyncSession, *, workspace_id: uuid.UUID, rule_keys: Iterable[str], on: date
) -> dict[str, RuleOutcome]:
    """Для каждого ключа правила — утверждённая действующая версия или причина её отсутствия."""
    keys = sorted(set(rule_keys))
    definitions: Mapping[str, CalcRuleDefinition] = {
        item.rule_key: item
        for item in await session.scalars(
            select(CalcRuleDefinition)
            .where(
                CalcRuleDefinition.workspace_id == workspace_id,
                CalcRuleDefinition.rule_key.in_(keys),
            )
            .options(selectinload(CalcRuleDefinition.versions))
        )
    }
    outcomes: dict[str, RuleOutcome] = {}
    for key in keys:
        definition = definitions.get(key)
        if definition is None:
            outcomes[key] = Absence(
                CalcBlockCode.RULE_NOT_FOUND, f"в реестре правил пространства нет {key}"
            )
            continue
        approved = next(
            (row for row in definition.versions if row.status is CalcRuleStatus.APPROVED), None
        )
        if approved is None:
            states = ", ".join(f"v{row.version} {row.status.value}" for row in definition.versions)
            outcomes[key] = Absence(
                CalcBlockCode.RULE_NOT_APPROVED,
                f"у {key} нет утверждённой версии ({states}): черновик, отклонённая и "
                "устаревшая версии в новый расчёт не идут",
            )
            continue
        content = rules_registry.content_of(approved, definition.discipline)
        if not validation.calculation_eligible(approved.status, content, on):
            outcomes[key] = Absence(
                CalcBlockCode.RULE_NOT_EFFECTIVE,
                f"{key}@{approved.version} не действует на {on.isoformat()} "
                f"(с {content.valid_from or '—'} по {content.valid_to or '—'})",
            )
            continue
        outcomes[key] = ResolvedRule(
            rule_key=key,
            rule_version_id=approved.id,
            version=approved.version,
            status=approved.status,
            rule_type=approved.rule_type,
            content=content,
            content_sha256=approved.content_sha256,
        )
    return outcomes
