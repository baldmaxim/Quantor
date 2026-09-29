"""Таблица фактов экрана «Исходные данные» (PROMPT 02): идёт ли утверждение в расчёт.

Ответ сервера, а не вывод интерфейса: интерфейс только называет его.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.enums import (
    CalcFactStatus,
    CalcFactUsage,
    CalcResolutionState,
    CalcReviewStatus,
)
from app.contracts.calc.fact_types import fact_type_def, values_agree
from app.contracts.calc.facts import CalcFactRead
from app.contracts.calc.readiness import CalcInputFactPage, CalcInputFactRead
from app.errors import InvariantError
from app.models import Project
from app.models.calc import CalcFact
from app.services.calc.facts import registry
from app.services.calc.facts.resolution import Resolution


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
