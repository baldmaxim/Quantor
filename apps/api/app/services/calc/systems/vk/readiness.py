"""Готовность ВК к расчёту: назначение систем, исходные данные, правила (PROMPT 06). Чтение.

- Назначение: калькулятор Т3 запускается, только если документация называет Т3 подающим
  трубопроводом горячей воды (`system.function`). Нет факта — BLOCKED с вопросом, другое
  назначение — BLOCKED с расхождением, конфликт источников — BLOCKED до решения человека.
- Исходные данные: матрица PROMPT 02 сворачивается в «найдено автоматически / выводится /
  нужен человек»; человек работает только с недостающим.
- Правила: каждое решение калькулятора — утверждённая версия (READY), черновик (DRAFT — блокер
  гейта), источника нет (SOURCE_REQUIRED) или методики нет в коде (IMPLEMENTATION_REQUIRED).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.engine import CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcDiscipline,
    CalcFactMethod,
    CalcReadinessStatus,
    CalcRequirementLevel,
    CalcRuleReadiness,
    CalcRuleStatus,
    CalcSemanticsStatus,
)
from app.contracts.calc.fact_types import SYSTEM_FUNCTIONS, fact_key
from app.contracts.calc.passport import CalcInputCounts, CalcPassportRule
from app.contracts.calc.readiness import CalcReadinessRowRead, CalcSystemReadinessRead
from app.contracts.calc.subjects import CalcFactSubject
from app.models import CalcRuleDefinition
from app.services.calc.engine.inputs import fact_outcomes
from app.services.calc.rules import registry as rules_registry
from app.services.calc.rules import validation
from app.services.calc.systems.vk.graph_parts import code_of
from app.services.calc.systems.vk.rule_needs import needs_for
from app.services.calc.systems.vk.spec import VkSystemSpec

_FUNCTION_TITLES: Final = {item.value: item.title for item in SYSTEM_FUNCTIONS}
_SATISFIED: Final = frozenset({CalcReadinessStatus.FOUND, CalcReadinessStatus.DERIVABLE})
_HUMAN: Final = frozenset(
    {
        CalcReadinessStatus.MANUAL_REQUIRED,
        CalcReadinessStatus.MISSING,
        CalcReadinessStatus.UNKNOWN,
        CalcReadinessStatus.CONFLICTED,
    }
)


def function_title(code: str) -> str:
    return _FUNCTION_TITLES.get(code, code)


def semantics_key(spec: VkSystemSpec, building: str) -> str:
    """Назначение системы — свойство корпуса, а не секции: ключ без секции."""
    subject = CalcFactSubject(
        building=building, discipline=CalcDiscipline.VK, system_code=spec.code
    )
    return fact_key("system.function", subject)


async def semantics_of(
    session: AsyncSession, *, project_id: uuid.UUID, spec: VkSystemSpec, building: str
) -> tuple[CalcSemanticsStatus, str, CalcSnapshotItem | None]:
    key = semantics_key(spec, building)
    outcome = (await fact_outcomes(session, project_id=project_id, keys=[key]))[key]
    expected = function_title(spec.function)
    if not isinstance(outcome, CalcSnapshotItem):
        if outcome.code in (CalcBlockCode.FACT_CONFLICT, CalcBlockCode.FACT_DECISION_STALE):
            return (
                CalcSemanticsStatus.CONFLICT,
                f"Назначение {spec.code} в документах расходится: {outcome.message}",
                None,
            )
        return (
            CalcSemanticsStatus.MISSING,
            f"Назначение {spec.code} не подтверждено легендой или запиской: калькулятор считает "
            f"«{expected}» и по одному обозначению этого не предполагает",
            None,
        )
    code = code_of(outcome)
    if code != spec.function:
        return (
            CalcSemanticsStatus.MISMATCH,
            f"По документации {spec.code} — {function_title(code or '—')}, а калькулятор "
            f"считает «{expected}»: нужна проверка обозначений",
            outcome,
        )
    return CalcSemanticsStatus.CONFIRMED, f"{spec.code} — {expected} (по документации)", outcome


def input_counts(system: CalcSystemReadinessRead | None) -> CalcInputCounts:
    rows = [] if system is None else system.rows
    manual = [
        row
        for row in rows
        if row.status is CalcReadinessStatus.FOUND
        and all(value.method is CalcFactMethod.MANUAL for value in row.values)
    ]
    required = [row for row in rows if row.level is CalcRequirementLevel.REQUIRED]
    return CalcInputCounts(
        total=len(rows),
        found_auto=sum(1 for row in rows if row.status is CalcReadinessStatus.FOUND) - len(manual),
        found_manual=len(manual),
        derivable=sum(1 for row in rows if row.status is CalcReadinessStatus.DERIVABLE),
        needs_human=sum(1 for row in rows if row.status in _HUMAN),
        not_inspected=sum(1 for row in rows if row.status is CalcReadinessStatus.NOT_INSPECTED),
        required_total=len(required),
        required_satisfied=sum(1 for row in required if row.status in _SATISFIED),
    )


def unsatisfied(system: CalcSystemReadinessRead | None) -> list[CalcReadinessRowRead]:
    return [] if system is None else [row for row in system.rows if row.status not in _SATISFIED]


async def rule_matrix(
    session: AsyncSession, *, workspace_id: uuid.UUID, system_code: str, on: date
) -> list[CalcPassportRule]:
    needs = needs_for(system_code)
    definitions = {
        item.rule_key: item
        for item in await session.scalars(
            select(CalcRuleDefinition)
            .where(
                CalcRuleDefinition.workspace_id == workspace_id,
                CalcRuleDefinition.rule_key.in_([need.rule_key for need in needs]),
            )
            .options(selectinload(CalcRuleDefinition.versions))
        )
    }
    rows: list[CalcPassportRule] = []
    for need in needs:
        status = CalcRuleReadiness.SOURCE_REQUIRED
        version: int | None = None
        rule_type = None
        definition = definitions.get(need.rule_key)
        if need.implementation_key is None:
            status = CalcRuleReadiness.IMPLEMENTATION_REQUIRED
        elif definition is not None:
            approved = next(
                (row for row in definition.versions if row.status is CalcRuleStatus.APPROVED),
                None,
            )
            draft = next(
                (row for row in definition.versions if row.status is CalcRuleStatus.DRAFT), None
            )
            if approved is not None and validation.calculation_eligible(
                approved.status, rules_registry.content_of(approved, definition.discipline), on
            ):
                status, version, rule_type = (
                    CalcRuleReadiness.READY,
                    approved.version,
                    approved.rule_type,
                )
            elif draft is not None:
                status, version, rule_type = CalcRuleReadiness.DRAFT, draft.version, draft.rule_type
        rows.append(
            CalcPassportRule(
                rule_key=need.rule_key,
                title=need.title,
                layer=need.layer,
                status=status,
                version=version,
                rule_type=rule_type,
                blocks=need.blocks,
                gate=need.gate,
            )
        )
    return rows
