"""API реестра фактов расчётного контура (ADR-0030, PROMPT 01).

Весь маршрутизатор закрыт флагом `calc.portal`: он объявлен и из админки не включается до
инженерного гейта стадии П. Пути начинаются с `/calc/` и не содержат маркеров обмера
(`quantities`, `measurements`…) и `/mep/`: иначе их поймали бы охранные тесты чужих контуров.

Маршрутов для запусков, результатов, ВОР и вопросов здесь нет — они появятся в своих промтах.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.contracts.calc.enums import CalcConflictStatus, CalcFactStatus
from app.contracts.calc.fact_types import REGISTRY as FACT_TYPES
from app.contracts.calc.facts import (
    CalcConflictRead,
    CalcDecisionCreate,
    CalcDecisionRead,
    CalcEnumOptionRead,
    CalcFactCreate,
    CalcFactRead,
    CalcFactReview,
    CalcFactTypeRead,
    CalcFactValueRead,
    CalcFactWithdraw,
    CalcSourceCreate,
    CalcSourceRead,
)
from app.contracts.calc.units import UNITS
from app.domain import AuditAction
from app.errors import not_found
from app.models import CalcFact, CalcFactConflict, Project
from app.services import audit as audit_service
from app.services import projects as projects_service
from app.services.calc.facts import registry
from app.services.calc.facts.policy import POLICY_VERSION

router = APIRouter(prefix="/calc", tags=["calc"], dependencies=[require_feature("calc.portal")])


async def _project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


async def _fact(session: SessionDep, context: AuthDep, fact_id: uuid.UUID) -> CalcFact:
    fact = await registry.get_fact(session, workspace_id=context.tenant, fact_id=fact_id)
    if fact is None:
        raise not_found("Утверждение")
    return fact


async def _conflict_read(session: SessionDep, conflict: CalcFactConflict) -> CalcConflictRead:
    claims, decision = await registry.conflict_claims(session, conflict)
    return CalcConflictRead(
        id=conflict.id,
        project_id=conflict.project_id,
        fact_key=conflict.fact_key,
        fact_type=conflict.fact_type,
        subject_key=conflict.subject_key,
        status=conflict.status,
        claim_set_hash=conflict.claim_set_hash,
        claims=[CalcFactRead.model_validate(fact) for fact in claims],
        decision=None if decision is None else CalcDecisionRead.model_validate(decision),
        created_at=conflict.created_at,
        updated_at=conflict.updated_at,
    )


# ---------------------------------------------------------------------------- типы фактов


@router.get(
    "/fact-types",
    response_model=list[CalcFactTypeRead],
    summary="Типы фактов реестра",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_fact_types() -> list[CalcFactTypeRead]:
    """Что можно записать в реестр: вид значения, единица, какое место указать."""
    return [
        CalcFactTypeRead(
            key=definition.key,
            title=definition.title,
            description=definition.description,
            value_kind=definition.value_kind,
            unit=definition.unit,
            unit_title=None if definition.unit is None else UNITS[definition.unit].title,
            required_subject=sorted(definition.required_subject),
            allowed_subject=sorted(definition.allowed_subject),
            options=[
                CalcEnumOptionRead(value=option.value, title=option.title)
                for option in definition.options
            ],
            customer_vor_admissible=definition.customer_vor_admissible,
        )
        for definition in FACT_TYPES.values()
    ]


# ------------------------------------------------------------------------------- источники


@router.post(
    "/projects/{project_id}/sources",
    response_model=CalcSourceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Завести источник фактов",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_source(
    project_id: uuid.UUID, payload: CalcSourceCreate, session: SessionDep, context: AuthDep
) -> CalcSourceRead:
    project = await _project(session, context, project_id)
    source = await registry.create_source(
        session, project=project, payload=payload, created_by=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_SOURCE_CREATED,
        resource_type="calc_source",
        resource_id=str(source.id),
        after={
            "source_class": source.source_class.value,
            "document_stage": source.document_stage.value,
            "calculation_eligible": source.calculation_eligible,
        },
    )
    await session.commit()
    return CalcSourceRead.model_validate(source)


@router.get(
    "/projects/{project_id}/sources",
    response_model=list[CalcSourceRead],
    summary="Источники фактов проекта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_sources(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcSourceRead]:
    project = await _project(session, context, project_id)
    rows = await registry.list_sources(session, project_id=project.id)
    return [CalcSourceRead.model_validate(row) for row in rows]


# ----------------------------------------------------------------------------- утверждения


@router.post(
    "/projects/{project_id}/facts",
    response_model=CalcFactRead,
    status_code=status.HTTP_201_CREATED,
    summary="Записать утверждение о факте",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_fact(
    project_id: uuid.UUID, payload: CalcFactCreate, session: SessionDep, context: AuthDep
) -> CalcFactRead:
    """Новое утверждение. Прежнее утверждение того же источника по ключу заменяется версией."""
    project = await _project(session, context, project_id)
    fact = await registry.create_fact(
        session, project=project, payload=payload, author_id=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_FACT_CREATED,
        resource_type="calc_fact",
        resource_id=str(fact.id),
        after={
            "fact_key": fact.fact_key,
            "method": fact.method.value,
            "version": fact.version,
            "calculation_eligible": fact.calculation_eligible,
        },
    )
    await session.commit()
    return CalcFactRead.model_validate(fact)


@router.get(
    "/projects/{project_id}/facts",
    response_model=list[CalcFactRead],
    summary="Утверждения проекта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_facts(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    fact_type: Annotated[str | None, Query(max_length=64, description="Тип факта")] = None,
    fact_status: Annotated[
        CalcFactStatus | None, Query(alias="status", description="Статус утверждения")
    ] = None,
) -> list[CalcFactRead]:
    project = await _project(session, context, project_id)
    rows = await registry.list_facts(
        session, project_id=project.id, fact_type=fact_type, status=fact_status
    )
    return [CalcFactRead.model_validate(row) for row in rows]


@router.get(
    "/facts/{fact_id}",
    response_model=CalcFactRead,
    summary="Утверждение со свидетельствами",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_fact(fact_id: uuid.UUID, session: SessionDep, context: AuthDep) -> CalcFactRead:
    return CalcFactRead.model_validate(await _fact(session, context, fact_id))


@router.post(
    "/facts/{fact_id}/review",
    response_model=CalcFactRead,
    summary="Подтвердить или отклонить утверждение",
    dependencies=[require(Permission.CALC_VERIFY)],
)
async def review_calc_fact(
    fact_id: uuid.UUID, payload: CalcFactReview, session: SessionDep, context: AuthDep
) -> CalcFactRead:
    fact = await _fact(session, context, fact_id)
    before = fact.review_status.value
    reviewed = await registry.review_fact(
        session,
        fact=fact,
        status=payload.status,
        comment=payload.comment,
        reviewer_id=context.principal.user_id,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_FACT_REVIEWED,
        resource_type="calc_fact",
        resource_id=str(reviewed.id),
        before={"review_status": before},
        after={"review_status": reviewed.review_status.value},
    )
    await session.commit()
    return CalcFactRead.model_validate(reviewed)


@router.post(
    "/facts/{fact_id}/withdraw",
    response_model=CalcFactRead,
    summary="Отозвать утверждение",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def withdraw_calc_fact(
    fact_id: uuid.UUID, payload: CalcFactWithdraw, session: SessionDep, context: AuthDep
) -> CalcFactRead:
    fact = await _fact(session, context, fact_id)
    withdrawn = await registry.withdraw_fact(
        session, fact=fact, reason=payload.reason, author_id=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_FACT_WITHDRAWN,
        resource_type="calc_fact",
        resource_id=str(withdrawn.id),
        after={"status": withdrawn.status.value},
    )
    await session.commit()
    return CalcFactRead.model_validate(withdrawn)


# ------------------------------------------------------------------ конфликты и решения


@router.get(
    "/projects/{project_id}/conflicts",
    response_model=list[CalcConflictRead],
    summary="Конфликты источников",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_conflicts(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    conflict_status: Annotated[
        CalcConflictStatus | None, Query(alias="status", description="Состояние конфликта")
    ] = None,
) -> list[CalcConflictRead]:
    project = await _project(session, context, project_id)
    rows = await registry.list_conflicts(session, project_id=project.id, status=conflict_status)
    return [await _conflict_read(session, row) for row in rows]


@router.post(
    "/conflicts/{conflict_id}/decision",
    response_model=CalcConflictRead,
    status_code=status.HTTP_201_CREATED,
    summary="Решить конфликт источников",
    dependencies=[require(Permission.CALC_VERIFY)],
)
async def decide_calc_conflict(
    conflict_id: uuid.UUID, payload: CalcDecisionCreate, session: SessionDep, context: AuthDep
) -> CalcConflictRead:
    conflict = await registry.get_conflict(
        session, workspace_id=context.tenant, conflict_id=conflict_id
    )
    if conflict is None:
        raise not_found("Конфликт")
    project = await _project(session, context, conflict.project_id)
    decision = await registry.decide(
        session,
        project=project,
        conflict=conflict,
        payload=payload,
        author_id=context.principal.user_id,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_CONFLICT_DECIDED,
        resource_type="calc_conflict",
        resource_id=str(conflict.id),
        after={
            "fact_key": conflict.fact_key,
            "chosen_fact_id": str(decision.chosen_fact_id),
            "status": conflict.status.value,
        },
    )
    await session.commit()
    await session.refresh(conflict)
    return await _conflict_read(session, conflict)


# ------------------------------------------------------------------ действующие значения


@router.get(
    "/projects/{project_id}/fact-values",
    response_model=list[CalcFactValueRead],
    summary="Действующие значения фактов",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_fact_values(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcFactValueRead]:
    """Какое значение каждого ключа пойдёт в расчёт и почему. ВОР Заказчика — отдельно."""
    project = await _project(session, context, project_id)
    resolved = await registry.resolve_project(session, project_id=project.id)
    conflicts = await registry.conflict_ids_by_key(session, project_id=project.id)
    return [
        CalcFactValueRead(
            fact_key=entry.fact_key,
            fact_type=entry.fact_type,
            subject=sample.subject,
            state=entry.resolution.state,
            value=entry.resolution.value,
            chosen_fact_id=None if entry.resolution.chosen is None else entry.resolution.chosen.id,
            claim_ids=list(entry.resolution.claim_ids),
            excluded_claim_ids=list(entry.resolution.excluded_ids),
            conflict_id=conflicts.get(entry.fact_key),
            policy_version=POLICY_VERSION,
            warnings=list(entry.resolution.warnings),
        )
        for entry, sample in resolved
    ]
