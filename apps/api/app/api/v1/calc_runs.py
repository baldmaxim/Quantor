"""API расчётного ядра (ADR-0030, PROMPT 04).

Каталог калькуляторов, проверка запроса без запуска, запуск, запуски проекта, запуск целиком,
результат, цепочка объяснения, сравнение двух запусков и повтор исторического запуска.

Нехватка данных — не ошибка сервера: запуск записывается со статусом BLOCKED и причинами.
Изменить или удалить запуск нельзя — таких маршрутов нет, а база не даёт это сделать и в обход.
Сверки с ВОР здесь нет — это PROMPT 09. Закрыто флагом `calc.portal`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.v1.calc import project_in_scope
from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.contracts.calc.engine import (
    CalcCalculatorRead,
    CalcResultRead,
    CalcResultTraceRead,
    CalcRunCompareRead,
    CalcRunCreate,
    CalcRunRead,
    CalcRunReplayRead,
    CalcRunSummaryRead,
    CalcRunValidateRead,
)
from app.domain import AuditAction
from app.errors import DomainError, ErrorCode, not_found
from app.models import CalcRun
from app.services import audit as audit_service
from app.services.calc.engine import reads, runs, trace

router = APIRouter(prefix="/calc", tags=["calc"], dependencies=[require_feature("calc.portal")])

_CALCULATOR = "Калькулятор"
_RUN = "Запуск расчёта"


async def _run(session: SessionDep, context: AuthDep, run_id: uuid.UUID) -> CalcRun:
    run = await runs.get_run(session, workspace_id=context.tenant, run_id=run_id)
    if run is None:
        raise not_found(_RUN)
    return run


@router.get(
    "/calculators",
    response_model=list[CalcCalculatorRead],
    summary="Калькуляторы расчётного ядра",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_calculators(
    include_demo: Annotated[bool, Query()] = False,
) -> list[CalcCalculatorRead]:
    """Что можно запустить: версии, система, стадия, сценарии, нужные факты и правила.

    Демонстрационные калькуляторы скрыты; `include_demo=true` — отладочный режим.
    """
    return reads.list_calculators(include_demo=include_demo)


@router.post(
    "/projects/{project_id}/runs/validate",
    response_model=CalcRunValidateRead,
    summary="Проверить запрос расчёта без запуска",
    dependencies=[require(Permission.CALC_READ)],
)
async def validate_calc_run(
    project_id: uuid.UUID, payload: CalcRunCreate, session: SessionDep, context: AuthDep
) -> CalcRunValidateRead:
    """Какие факты и версии правил будут использованы и что блокирует расчёт. Ничего не пишет."""
    project = await project_in_scope(session, context, project_id)
    try:
        return await runs.validate(
            session, workspace_id=context.tenant, project_id=project.id, payload=payload
        )
    except LookupError:
        raise not_found(_CALCULATOR) from None


@router.post(
    "/projects/{project_id}/runs",
    response_model=CalcRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить расчёт",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_run(
    project_id: uuid.UUID,
    payload: CalcRunCreate,
    session: SessionDep,
    context: AuthDep,
    response: Response,
) -> CalcRunRead:
    """Нехватка данных — запуск BLOCKED с причинами, а не ошибка. Повтор с тем же ключом
    идемпотентности возвращает уже созданный запуск (200)."""
    project = await project_in_scope(session, context, project_id)
    try:
        run, created = await runs.start_run(
            session,
            workspace_id=context.tenant,
            project_id=project.id,
            payload=payload,
            author=context.principal.user_id,
        )
    except LookupError:
        raise not_found(_CALCULATOR) from None
    if created:
        await audit_service.record(
            session,
            context,
            action=AuditAction.CALC_RUN_CREATED,
            resource_type="calc_run",
            resource_id=str(run.id),
            after={
                "calculator": f"{run.calculator_id}@{run.calculator_version}",
                "scenario": run.scenario.value,
                "status": run.status.value,
                "result_sha256": run.result_sha256,
            },
        )
        await session.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return reads.run_read(run)


@router.get(
    "/projects/{project_id}/runs",
    response_model=list[CalcRunSummaryRead],
    summary="Запуски расчёта проекта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_runs(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcRunSummaryRead]:
    project = await project_in_scope(session, context, project_id)
    return [reads.summary_read(run) for run in await runs.list_runs(session, project_id=project.id)]


@router.get(
    "/runs/compare",
    response_model=CalcRunCompareRead,
    summary="Сравнить два запуска",
    dependencies=[require(Permission.CALC_READ)],
)
async def compare_calc_runs(
    base: Annotated[uuid.UUID, Query()],
    other: Annotated[uuid.UUID, Query()],
    session: SessionDep,
    context: AuthDep,
) -> CalcRunCompareRead:
    """Что изменилось: факты, версии правил, шаги с новым отпечатком и почему, результаты."""
    first = await _run(session, context, base)
    second = await _run(session, context, other)
    if first.project_id != second.project_id:
        raise DomainError(ErrorCode.CALC_RUN_COMPARE_INVALID)
    return trace.compare(reads.run_read(first), reads.run_read(second))


@router.get(
    "/runs/{run_id}",
    response_model=CalcRunRead,
    summary="Запуск расчёта",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_run(run_id: uuid.UUID, session: SessionDep, context: AuthDep) -> CalcRunRead:
    """Запуск целиком: снимок, версии правил, шаги, результаты, причины блокировки."""
    return reads.run_read(await _run(session, context, run_id))


@router.get(
    "/runs/{run_id}/results/{result_key}",
    response_model=CalcResultRead,
    summary="Результат запуска",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_run_result(
    run_id: uuid.UUID, result_key: str, session: SessionDep, context: AuthDep
) -> CalcResultRead:
    run = await _run(session, context, run_id)
    row = next((item for item in run.results if item.result_key == result_key), None)
    if row is None:
        raise not_found("Результат")
    return reads.result_read(row)


@router.get(
    "/runs/{run_id}/results/{result_key}/trace",
    response_model=CalcResultTraceRead,
    summary="Почему такое значение",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_run_trace(
    run_id: uuid.UUID, result_key: str, session: SessionDep, context: AuthDep
) -> CalcResultTraceRead:
    """Цепочка: результат → шаг → версия правила, входы → факт → свидетельство."""
    run = reads.run_read(await _run(session, context, run_id))
    if all(item.result_key != result_key for item in run.results):
        raise not_found("Результат")
    return trace.explain(run, result_key)


@router.post(
    "/runs/{run_id}/replay",
    response_model=CalcRunReplayRead,
    summary="Повторить исторический запуск",
    dependencies=[require(Permission.CALC_READ)],
)
async def replay_calc_run(
    run_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> CalcRunReplayRead:
    """Пересчёт из снимка и версий правил самого запуска; ничего не пишет."""
    return await runs.replay(session, await _run(session, context, run_id))
