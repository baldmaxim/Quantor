"""API синтеза структуры системы (ADR-0030, PROMPT 05).

Синтезаторы, проверка без записи, запуск синтеза по запуску расчёта, запуски проекта, запуск,
граф, варианты, нерешённое, «почему этот элемент нужен», повтор, сравнение и решение инженера по
варианту. Нехватка данных — запуск BLOCKED с причинами; открытое структурное решение — PARTIAL.
Изменить или удалить запуск нельзя. Сверки с ВОР здесь нет. Закрыто флагом `calc.portal`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.v1.calc import project_in_scope
from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.contracts.calc.synthesis import (
    CalcSynthesisCompareRead,
    CalcSynthesisDecisionCreate,
    CalcSynthesisDecisionRead,
    CalcSynthesisReplayRead,
    CalcSynthesisRunCreate,
    CalcSynthesisRunRead,
    CalcSynthesisRunSummaryRead,
    CalcSynthesisTraceRead,
    CalcSynthesisValidateRead,
    CalcSynthesisVariant,
    CalcSynthesizerRead,
    CalcSystemGraph,
    CalcUnresolvedItem,
)
from app.domain import AuditAction
from app.errors import DomainError, ErrorCode, not_found
from app.models import CalcSynthesisRun
from app.services import audit as audit_service
from app.services.calc.engine.reads import run_read as calculation_read
from app.services.calc.synthesis import reads, runs, trace

router = APIRouter(prefix="/calc", tags=["calc"], dependencies=[require_feature("calc.portal")])

_RUN = "Запуск синтеза"


async def _run(session: SessionDep, context: AuthDep, run_id: uuid.UUID) -> CalcSynthesisRun:
    run = await runs.get(session, workspace_id=context.tenant, run_id=run_id)
    if run is None:
        raise not_found(_RUN)
    return run


async def _read(session: SessionDep, run: CalcSynthesisRun) -> CalcSynthesisRunRead:
    return reads.run_read(run, await runs.decisions_made(session, run))


@router.get(
    "/synthesizers",
    response_model=list[CalcSynthesizerRead],
    summary="Синтезаторы структуры системы",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_synthesizers(
    include_demo: Annotated[bool, Query()] = False,
) -> list[CalcSynthesizerRead]:
    """Демонстрационные синтезаторы скрыты; `include_demo=true` — отладочный режим."""
    return reads.list_synthesizers(include_demo=include_demo)


@router.post(
    "/projects/{project_id}/synthesis-runs/validate",
    response_model=CalcSynthesisValidateRead,
    summary="Проверить запрос синтеза без запуска",
    dependencies=[require(Permission.CALC_READ)],
)
async def validate_calc_synthesis(
    project_id: uuid.UUID, payload: CalcSynthesisRunCreate, session: SessionDep, context: AuthDep
) -> CalcSynthesisValidateRead:
    project = await project_in_scope(session, context, project_id)
    try:
        return await runs.validate(
            session, workspace_id=context.tenant, project_id=project.id, payload=payload
        )
    except LookupError as error:
        raise not_found(str(error).capitalize()) from None


@router.post(
    "/projects/{project_id}/synthesis-runs",
    response_model=CalcSynthesisRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить синтез структуры",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_synthesis_run(
    project_id: uuid.UUID,
    payload: CalcSynthesisRunCreate,
    session: SessionDep,
    context: AuthDep,
    response: Response,
) -> CalcSynthesisRunRead:
    """BLOCKED и PARTIAL — не ошибки, а записанные итоги. Повтор по ключу возвращает тот же."""
    project = await project_in_scope(session, context, project_id)
    try:
        run, created = await runs.start(
            session,
            workspace_id=context.tenant,
            project_id=project.id,
            payload=payload,
            author=context.principal.user_id,
        )
    except LookupError as error:
        raise not_found(str(error).capitalize()) from None
    if created:
        await audit_service.record(
            session,
            context,
            action=AuditAction.CALC_SYNTHESIS_RUN_CREATED,
            resource_type="calc_synthesis_run",
            resource_id=str(run.id),
            after={
                "synthesizer": f"{run.synthesizer_id}@{run.synthesizer_version}",
                "calculation_run_id": str(run.calculation_run_id),
                "status": run.status.value,
                "graph_sha256": run.graph_sha256,
            },
        )
        await session.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return await _read(session, run)


@router.get(
    "/projects/{project_id}/synthesis-runs",
    response_model=list[CalcSynthesisRunSummaryRead],
    summary="Запуски синтеза проекта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_synthesis_runs(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcSynthesisRunSummaryRead]:
    project = await project_in_scope(session, context, project_id)
    return [
        reads.summary_read(run)
        for run in await runs.list_for_project(session, project_id=project.id)
    ]


@router.get(
    "/synthesis-runs/compare",
    response_model=CalcSynthesisCompareRead,
    summary="Сравнить два запуска синтеза",
    dependencies=[require(Permission.CALC_READ)],
)
async def compare_calc_synthesis_runs(
    base: Annotated[uuid.UUID, Query()],
    other: Annotated[uuid.UUID, Query()],
    session: SessionDep,
    context: AuthDep,
) -> CalcSynthesisCompareRead:
    first = await _run(session, context, base)
    second = await _run(session, context, other)
    if first.project_id != second.project_id:
        raise DomainError(ErrorCode.CALC_RUN_COMPARE_INVALID)
    return trace.compare(
        await _read(session, first),
        reads.graph_read(first),
        await _read(session, second),
        reads.graph_read(second),
    )


@router.get(
    "/synthesis-runs/{run_id}",
    response_model=CalcSynthesisRunRead,
    summary="Запуск синтеза",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_synthesis_run(
    run_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CalcSynthesisRunRead:
    return await _read(session, await _run(session, context, run_id))


@router.get(
    "/synthesis-runs/{run_id}/graph",
    response_model=CalcSystemGraph,
    summary="Граф системы запуска",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_synthesis_graph(
    run_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CalcSystemGraph:
    graph = reads.graph_read(await _run(session, context, run_id))
    if graph is None:
        raise not_found("Граф")
    return graph


@router.get(
    "/synthesis-runs/{run_id}/variants",
    response_model=list[CalcSynthesisVariant],
    summary="Допустимые варианты схемы",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_synthesis_variants(
    run_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcSynthesisVariant]:
    return (await _read(session, await _run(session, context, run_id))).variants


@router.get(
    "/synthesis-runs/{run_id}/unresolved",
    response_model=list[CalcUnresolvedItem],
    summary="Что Quantor пока не знает",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_synthesis_unresolved(
    run_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcUnresolvedItem]:
    return (await _read(session, await _run(session, context, run_id))).unresolved


@router.get(
    "/synthesis-runs/{run_id}/trace",
    response_model=CalcSynthesisTraceRead,
    summary="Почему этот элемент нужен",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_synthesis_trace(
    run_id: uuid.UUID,
    element_id: Annotated[str, Query(max_length=64)],
    session: SessionDep,
    context: AuthDep,
) -> CalcSynthesisTraceRead:
    run = await _run(session, context, run_id)
    graph = reads.graph_read(run)
    if graph is None:
        raise not_found("Граф")
    calculation = calculation_read(await runs.calculation_of(session, run))
    try:
        return trace.element_trace(await _read(session, run), graph, calculation, element_id)
    except KeyError:
        raise not_found("Элемент") from None


@router.post(
    "/synthesis-runs/{run_id}/replay",
    response_model=CalcSynthesisReplayRead,
    summary="Повторить исторический запуск синтеза",
    dependencies=[require(Permission.CALC_READ)],
)
async def replay_calc_synthesis_run(
    run_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CalcSynthesisReplayRead:
    return await runs.replay(session, await _run(session, context, run_id))


@router.post(
    "/synthesis-runs/{run_id}/decisions",
    response_model=CalcSynthesisDecisionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Решение инженера по варианту",
    dependencies=[require(Permission.CALC_VERIFY)],
)
async def create_calc_synthesis_decision(
    run_id: uuid.UUID,
    payload: CalcSynthesisDecisionCreate,
    session: SessionDep,
    context: AuthDep,
) -> CalcSynthesisDecisionRead:
    """Запуск не меняется: решение — вход следующего запуска, а не факт объекта."""
    run = await _run(session, context, run_id)
    decision = await runs.decide(
        session, run=run, payload=payload, author=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_SYNTHESIS_DECIDED,
        resource_type="calc_synthesis_decision",
        resource_id=str(decision.id),
        after={"run": str(run.id), "node": decision.node_id, "count": decision.selected_count},
    )
    await session.commit()
    return runs.decision_read(decision)
