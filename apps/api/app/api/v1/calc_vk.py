"""API рабочего калькулятора ВК стадии П (ADR-0030, PROMPT 06).

Калькуляторы В1, Т3, Т4, К1 с заявками на инженерные решения; готовность проекта (назначение
систем, исходные данные, правила); расчёт комплекта — паспорта трёх сценариев; история;
паспорт; структура; ожидаемые количества («объёмы»); неопределённости; допущения; объяснение
позиции до свидетельства. Сверки с ВОР Заказчика здесь нет — это PROMPT 09. Закрыто флагом
`calc.portal`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.v1.calc import project_in_scope
from app.api.v1.calc_rules import audit_rule_version
from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.contracts.calc.engine import CalcAssumptionRecord
from app.contracts.calc.enums import CalcScenario
from app.contracts.calc.passport import (
    CalcExpectedQuantityRead,
    CalcPassportIssue,
    CalcPassportRead,
    CalcPassportSummaryRead,
    CalcQuantityTraceRead,
    CalcRuleTermRead,
    CalcVkBatchRead,
    CalcVkCalculatorRead,
    CalcVkReadinessRead,
    CalcVkRuleNeedRead,
    CalcVkRuleVersionCreate,
    CalcVkRunCreate,
    CalcVkSystemReadinessRead,
)
from app.contracts.calc.rules import CalcRuleVersionRead
from app.contracts.calc.synthesis import CalcSystemGraph
from app.domain import AuditAction
from app.errors import not_found
from app.models import CalcPassport
from app.services import audit as audit_service
from app.services.calc import readiness as input_readiness
from app.services.calc.engine.catalog import CALCULATORS
from app.services.calc.engine.reads import calculator_read
from app.services.calc.rules import registry as rules_registry
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.synthesis.reads import synthesizer_read
from app.services.calc.systems.vk import orchestrator, reads, rule_versions
from app.services.calc.systems.vk.passport_sections import missing as missing_rows
from app.services.calc.systems.vk.readiness import (
    function_title,
    input_counts,
    rule_matrix,
    semantics_of,
)
from app.services.calc.systems.vk.requirements import (
    VK_REQUIREMENTS_VERSION,
    VK_SYSTEMS,
    requirements_for,
)
from app.services.calc.systems.vk.rule_needs import RuleTerm, needs_for
from app.services.calc.systems.vk.spec import VK_SPECS

router = APIRouter(prefix="/calc", tags=["calc"], dependencies=[require_feature("calc.portal")])

_PASSPORT = "Паспорт"


def _terms(terms: tuple[RuleTerm, ...]) -> list[CalcRuleTermRead]:
    return [
        CalcRuleTermRead(
            name=item.name, unit=item.unit, meaning=item.meaning, quantity=item.quantity
        )
        for item in terms
    ]


async def _passport(session: SessionDep, context: AuthDep, passport_id: uuid.UUID) -> CalcPassport:
    passport = await orchestrator.get(session, workspace_id=context.tenant, passport_id=passport_id)
    if passport is None:
        raise not_found(_PASSPORT)
    return passport


@router.get(
    "/vk/calculators",
    response_model=list[CalcVkCalculatorRead],
    summary="Рабочие калькуляторы ВК стадии П",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_vk_calculators() -> list[CalcVkCalculatorRead]:
    return [
        CalcVkCalculatorRead(
            system_code=spec.code,
            title=spec.title,
            function=function_title(spec.function),
            calculator=calculator_read(CALCULATORS[(spec.calculator_id, spec.version)]),
            synthesizer=synthesizer_read(SYNTHESIZERS[(spec.synthesizer_id, spec.version)]),
            rules=[
                CalcVkRuleNeedRead(
                    rule_key=need.rule_key,
                    title=need.title,
                    systems=list(need.systems),
                    layer=need.layer,
                    rule_types=list(need.rule_types),
                    implementation_key=need.implementation_key,
                    formula=need.formula,
                    inputs=_terms(need.inputs),
                    parameters=_terms(need.parameters),
                    outputs=_terms(need.outputs),
                    used_in=need.used_in,
                    blocks=need.blocks,
                    affects=list(need.affects),
                    gate=need.gate,
                    example=need.example,
                )
                for need in needs_for(spec.code)
            ],
        )
        for spec in VK_SPECS
    ]


@router.post(
    "/vk/rules/{rule_key}/versions",
    response_model=CalcRuleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Версия правила по заявке калькулятора ВК",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def save_calc_vk_rule_version(
    rule_key: str, payload: CalcVkRuleVersionCreate, session: SessionDep, context: AuthDep
) -> CalcRuleVersionRead:
    """Черновик по заявке: значения параметров и основание — инженера, контракт — из заявки.

    Нет правила — создаётся; есть черновик — он правится; иначе — новая версия с причиной.
    Утверждает другой человек: `POST /calc/rules/{rule_key}/versions/{version}/approve`.
    """
    try:
        definition, row, action = await rule_versions.save(
            session,
            workspace_id=context.tenant,
            rule_key=rule_key,
            payload=payload,
            author=context.principal.user_id,
        )
    except LookupError:
        raise not_found("Заявка правила") from None
    await audit_rule_version(session, context, action, definition, row)
    await session.commit()
    return rules_registry.version_read(definition, row, rules_registry.today())


@router.get(
    "/projects/{project_id}/vk/readiness",
    response_model=CalcVkReadinessRead,
    summary="Готовность ВК: назначение систем, исходные данные, правила",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_vk_readiness(
    project_id: uuid.UUID,
    building: Annotated[str, Query(min_length=1, max_length=64)],
    session: SessionDep,
    context: AuthDep,
    section: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> CalcVkReadinessRead:
    project = await project_in_scope(session, context, project_id)
    matrix = await input_readiness.load_readiness(
        session,
        project=project,
        version=VK_REQUIREMENTS_VERSION,
        systems=VK_SYSTEMS,
        requirements_for=requirements_for,
    )
    by_code = {item.system_code: item for item in matrix.systems}
    today = datetime.now(UTC).date()
    systems: list[CalcVkSystemReadinessRead] = []
    for spec in VK_SPECS:
        semantics, note, _ = await semantics_of(
            session, project_id=project.id, spec=spec, building=building
        )
        system = by_code.get(spec.code)
        systems.append(
            CalcVkSystemReadinessRead(
                system_code=spec.code,
                title=spec.title,
                calculator_id=spec.calculator_id,
                calculator_version=spec.version,
                synthesizer_id=spec.synthesizer_id,
                function=function_title(spec.function),
                semantics=semantics,
                semantics_note=note,
                inputs=input_counts(system),
                missing=missing_rows(system, []),
                rules=await rule_matrix(
                    session, workspace_id=context.tenant, system_code=spec.code, on=today
                ),
            )
        )
    return CalcVkReadinessRead(building=building, section=section, systems=systems)


@router.post(
    "/projects/{project_id}/vk/passports",
    response_model=CalcVkBatchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Рассчитать комплект ВК: паспорта систем",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_vk_passports(
    project_id: uuid.UUID,
    payload: CalcVkRunCreate,
    session: SessionDep,
    context: AuthDep,
    response: Response,
) -> CalcVkBatchRead:
    """BLOCKED и PARTIAL — не ошибки, а записанные паспорта. Повтор по ключу — тот же комплект."""
    project = await project_in_scope(session, context, project_id)
    batch_id, passports, created = await orchestrator.start(
        session,
        workspace_id=context.tenant,
        project=project,
        payload=payload,
        author=context.principal.user_id,
    )
    if created:
        for passport in passports:
            await audit_service.record(
                session,
                context,
                action=AuditAction.CALC_PASSPORT_CREATED,
                resource_type="calc_passport",
                resource_id=str(passport.id),
                after={
                    "batch_id": str(batch_id),
                    "system": passport.system_code,
                    "status": passport.status.value,
                    "passport_sha256": passport.passport_sha256,
                },
            )
        await session.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return CalcVkBatchRead(
        batch_id=batch_id,
        created=created,
        passports=[reads.summary_read(item) for item in passports],
    )


@router.get(
    "/projects/{project_id}/vk/passports",
    response_model=list[CalcPassportSummaryRead],
    summary="История паспортов ВК проекта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_vk_passports(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcPassportSummaryRead]:
    project = await project_in_scope(session, context, project_id)
    return [
        reads.summary_read(item)
        for item in await orchestrator.list_for_project(session, project_id=project.id)
    ]


@router.get(
    "/vk/passports/{passport_id}",
    response_model=CalcPassportRead,
    summary="Расчётный паспорт системы",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_vk_passport(
    passport_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CalcPassportRead:
    return reads.passport_read(await _passport(session, context, passport_id))


@router.get(
    "/vk/passports/{passport_id}/structure",
    response_model=CalcSystemGraph,
    summary="Структура системы паспорта",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_vk_structure(
    passport_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    scenario: Annotated[CalcScenario, Query()] = CalcScenario.EXPECTED,
) -> CalcSystemGraph:
    graph = await reads.graph_of(session, await _passport(session, context, passport_id), scenario)
    if graph is None:
        raise not_found("Граф")
    return graph


@router.get(
    "/vk/passports/{passport_id}/volumes",
    response_model=list[CalcExpectedQuantityRead],
    summary="Ожидаемые количества паспорта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_vk_volumes(
    passport_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    scenario: Annotated[CalcScenario | None, Query()] = None,
) -> list[CalcExpectedQuantityRead]:
    passport = await _passport(session, context, passport_id)
    return [
        reads.quantity_read(row)
        for row in passport.quantities
        if scenario is None or row.scenario is scenario
    ]


@router.get(
    "/vk/passports/{passport_id}/unresolved",
    response_model=list[CalcPassportIssue],
    summary="Что Quantor пока не может определить",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_vk_unresolved(
    passport_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcPassportIssue]:
    return reads.passport_read(await _passport(session, context, passport_id)).body.unresolved


@router.get(
    "/vk/passports/{passport_id}/assumptions",
    response_model=list[CalcAssumptionRecord],
    summary="Допущения паспорта: применённые и нет, с причиной",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_vk_assumptions(
    passport_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcAssumptionRecord]:
    return await reads.assumptions_of(session, await _passport(session, context, passport_id))


@router.get(
    "/vk/volumes/{quantity_id}/trace",
    response_model=CalcQuantityTraceRead,
    summary="Почему количество такое",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_vk_volume_trace(
    quantity_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CalcQuantityTraceRead:
    found = await orchestrator.quantity(
        session, workspace_id=context.tenant, quantity_id=quantity_id
    )
    if found is None:
        raise not_found("Позиция")
    row, passport = found
    return await reads.quantity_trace(session, row, passport)
