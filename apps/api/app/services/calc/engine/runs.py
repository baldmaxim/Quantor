"""Запуски расчётного ядра: подготовка, исполнение, хранение, чтение, повтор.

Запуск синхронный и укладывается в одну транзакцию запроса: снимок фактов и выбор правил,
план, исполнение, запись. Поэтому запуск записывается сразу в итоговом состоянии —
BLOCKED, SUCCEEDED или FAILED — и больше не меняется (триггер базы).

Реестр фактов и реестр правил здесь только читаются. Два запуска одного проекта не мешают
друг другу: у каждого свой снимок, общих изменяемых данных у них нет.

Идемпотентность — как у заданий: ключ в запросе, повтор с тем же ключом возвращает уже
созданный запуск; тот же ключ с другим запросом — отказ. Гонку двух одинаковых запросов
разводят транзакционная блокировка ключа и уникальный индекс.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.calc.engine import (
    CalcResultRead,
    CalcRoundingRecord,
    CalcRuleBinding,
    CalcRunCreate,
    CalcRunFailure,
    CalcRunReplayRead,
    CalcRunValidateRead,
    CalcRunVersions,
    CalcStepOutput,
    CalcStepRead,
)
from app.contracts.calc.enums import CalcRuleStatus, CalcRunStatus, CalcStepStatus
from app.contracts.calc.fact_types import FACT_TYPES_VERSION
from app.errors import DomainError, ErrorCode
from app.models import CalcRuleVersion, CalcRun, CalcRunResult, CalcRunStep
from app.services.calc.engine import planner
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.catalog import CALCULATORS, HANDLERS
from app.services.calc.engine.executor import Execution, PriorStep, StepExecutionError, execute
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.inputs import (
    RUN_SNAPSHOT_VERSION,
    fact_outcomes,
    rule_outcomes,
    snapshot_of,
)
from app.services.calc.engine.plan_types import (
    FactOutcome,
    Plan,
    ResolvedRule,
    RuleOutcome,
    fact_requirements,
)
from app.services.calc.engine.policy import SCENARIO_POLICY_VERSION
from app.services.calc.engine.reads import run_read
from app.services.calc.facts.policy import POLICY_VERSION

ENGINE_VERSION: Final = "calc.engine.v1"


def today() -> date:
    return datetime.now(UTC).date()


def versions() -> CalcRunVersions:
    return CalcRunVersions(
        engine=ENGINE_VERSION,
        scenario_policy=SCENARIO_POLICY_VERSION,
        facts_policy=POLICY_VERSION,
        fact_types=FACT_TYPES_VERSION,
        snapshot=RUN_SNAPSHOT_VERSION,
    )


# ----------------------------------------------------------------------------- калькуляторы


def calculator(calculator_id: str, version: int) -> CalculatorDef | None:
    return CALCULATORS.get((calculator_id, version))


# ------------------------------------------------------------------------------- подготовка


async def prepare(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CalcRunCreate,
    on: date,
) -> tuple[CalculatorDef, Plan]:
    """План запуска по текущим реестрам. LookupError — такого калькулятора нет."""
    definition = calculator(payload.calculator_id, payload.calculator_version)
    if definition is None:
        raise LookupError(f"{payload.calculator_id}@{payload.calculator_version}")
    requirements, _ = fact_requirements(definition, payload.scope)
    facts = await fact_outcomes(
        session, project_id=project_id, keys=[item.fact_key for item in requirements]
    )
    rules = await rule_outcomes(
        session, workspace_id=workspace_id, rule_keys=definition.rule_keys, on=on
    )
    plan = planner.plan(definition, payload.scenario, payload.scope, facts, rules, HANDLERS)
    return definition, plan


async def validate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CalcRunCreate,
) -> CalcRunValidateRead:
    """Проверка запроса без записи: что будет использовано и что мешает."""
    definition, plan = await prepare(
        session, workspace_id=workspace_id, project_id=project_id, payload=payload, on=today()
    )
    return CalcRunValidateRead(
        calculator_id=definition.calculator_id,
        calculator_version=definition.version,
        scenario=payload.scenario,
        valid=plan.valid,
        blocking_reasons=list(plan.reasons),
        warnings=list(plan.warnings),
        snapshot=snapshot_of(plan.snapshot_items),
        rule_bindings=list(plan.bindings),
    )


def _request_sha256(payload: CalcRunCreate) -> str:
    return canonical_sha256(
        {
            "calculator_id": payload.calculator_id,
            "calculator_version": payload.calculator_version,
            "scenario": payload.scenario.value,
            "scope": payload.scope.model_dump(mode="json"),
        }
    )


def _bindings_sha256(bindings: Sequence[CalcRuleBinding]) -> str:
    return canonical_sha256(
        [
            {
                "step_key": item.step_key,
                "rule_key": item.rule_key,
                "version": item.version,
                "content_sha256": item.content_sha256,
                "implementation_key": item.implementation_key,
                "handler_semantics_sha256": item.handler_semantics_sha256,
            }
            for item in bindings
        ]
    )


async def _lock(session: AsyncSession, name: str) -> None:
    digest = hashlib.sha256(name.encode()).digest()
    await session.execute(
        select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True)))
    )


async def _by_idempotency(session: AsyncSession, project_id: uuid.UUID, key: str) -> CalcRun | None:
    result = await session.scalars(
        select(CalcRun)
        .where(CalcRun.project_id == project_id, CalcRun.idempotency_key == key)
        .options(selectinload(CalcRun.steps), selectinload(CalcRun.results))
    )
    return result.one_or_none()


async def _prior_steps(
    session: AsyncSession, project_id: uuid.UUID, definition: CalculatorDef
) -> dict[str, PriorStep]:
    """Шаги последнего успешного запуска того же калькулятора в том же проекте.

    Только тот же проект — значит, то же пространство: результаты не переходят между
    арендаторами. Совпадение отпечатка шага гарантирует, что пересчёт дал бы то же самое.
    """
    prior = await session.scalar(
        select(CalcRun)
        .where(
            CalcRun.project_id == project_id,
            CalcRun.calculator_id == definition.calculator_id,
            CalcRun.calculator_version == definition.version,
            CalcRun.status == CalcRunStatus.SUCCEEDED,
        )
        .order_by(CalcRun.created_at.desc(), CalcRun.id)
        .limit(1)
        .options(selectinload(CalcRun.steps))
    )
    if prior is None:
        return {}
    return {
        row.fingerprint: PriorStep(
            run_id=row.reused_from_run_id or prior.id,
            fingerprint=row.fingerprint,
            outputs=tuple(CalcStepOutput.model_validate(item) for item in row.outputs),
            explanation=row.explanation,
            roundings=tuple(CalcRoundingRecord.model_validate(item) for item in row.roundings),
        )
        for row in prior.steps
        if row.status is not CalcStepStatus.NOT_APPLIED
    }


# ---------------------------------------------------------------------------------- запуск


async def start_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CalcRunCreate,
    author: uuid.UUID | None,
) -> tuple[CalcRun, bool]:
    """Новый запуск или уже созданный по тому же ключу идемпотентности (второе — False)."""
    request_sha256 = _request_sha256(payload)
    if payload.idempotency_key is not None:
        await _lock(session, f"calc-run|{project_id}|{payload.idempotency_key}")
        existing = await _by_idempotency(session, project_id, payload.idempotency_key)
        if existing is not None:
            if existing.request_sha256 != request_sha256:
                raise DomainError(ErrorCode.CALC_RUN_IDEMPOTENCY_CONFLICT)
            return existing, False

    on = today()
    definition, plan = await prepare(
        session, workspace_id=workspace_id, project_id=project_id, payload=payload, on=on
    )
    run_id = uuid.uuid4()
    snapshot = snapshot_of(plan.snapshot_items)
    execution: Execution | None = None
    failure: CalcRunFailure | None = None
    if plan.valid:
        reuse = await _prior_steps(session, project_id, definition)
        try:
            execution = execute(plan, run_id, reuse)
        except StepExecutionError as error:
            failure = CalcRunFailure(
                step_key=error.step_key, error=error.error, message=error.message
            )

    status = (
        CalcRunStatus.BLOCKED
        if not plan.valid
        else CalcRunStatus.FAILED
        if failure is not None
        else CalcRunStatus.SUCCEEDED
    )
    run = CalcRun(
        id=run_id,
        workspace_id=workspace_id,
        project_id=project_id,
        calculator_id=definition.calculator_id,
        calculator_version=definition.version,
        calculator_title=definition.title,
        calculator_sha256=definition.sha256,
        scenario=payload.scenario,
        scope=payload.scope.model_dump(mode="json"),
        status=status,
        effective_on=on,
        versions=versions().model_dump(mode="json"),
        snapshot=snapshot.model_dump(mode="json"),
        snapshot_sha256=snapshot.sha256,
        rule_bindings=[item.model_dump(mode="json") for item in plan.bindings],
        rule_bindings_sha256=_bindings_sha256(plan.bindings),
        blocking_reasons=[item.model_dump(mode="json") for item in plan.reasons],
        failure=None if failure is None else failure.model_dump(mode="json"),
        assumptions=[]
        if execution is None
        else [item.model_dump(mode="json") for item in execution.assumptions],
        warnings=list(plan.warnings),
        result_sha256=None if execution is None or failure else execution.result_sha256,
        results_count=0 if execution is None or failure else len(execution.results),
        idempotency_key=payload.idempotency_key,
        request_sha256=request_sha256,
        created_by=author,
        steps=[],
        results=[],
    )
    if execution is not None and failure is None:
        run.steps = [_step_row(run_id, item) for item in execution.steps]
        run.results = [
            _result_row(run_id, position, item) for position, item in enumerate(execution.results)
        ]
    session.add(run)
    await session.flush()
    return run, True


def _step_row(run_id: uuid.UUID, step: CalcStepRead) -> CalcRunStep:
    return CalcRunStep(
        run_id=run_id,
        step_key=step.step_key,
        position=step.position,
        title=step.title,
        status=step.status,
        rule_key=None if step.rule is None else step.rule.rule_key,
        rule_version=None if step.rule is None else step.rule.version,
        rule_type=None if step.rule is None else step.rule.rule_type,
        rule_content_sha256=None if step.rule is None else step.rule.content_sha256,
        implementation_key=None if step.rule is None else step.rule.implementation_key,
        inputs=[item.model_dump(mode="json") for item in step.inputs],
        parameters=[item.model_dump(mode="json") for item in step.parameters],
        outputs=[item.model_dump(mode="json") for item in step.outputs],
        roundings=[item.model_dump(mode="json") for item in step.roundings],
        assumption=None if step.assumption is None else step.assumption.model_dump(mode="json"),
        explanation=step.explanation,
        fingerprint=step.fingerprint,
        reused_from_run_id=step.reused_from_run_id,
    )


def _result_row(run_id: uuid.UUID, position: int, result: CalcResultRead) -> CalcRunResult:
    return CalcRunResult(
        run_id=run_id,
        result_key=result.result_key,
        position=position,
        title=result.title,
        value=result.value,
        unit=result.unit,
        category=result.category,
        discipline=result.discipline,
        system_code=result.system_code,
        scenario=result.scenario,
        step_key=result.step_key,
        output=result.output,
        rounding=None if result.rounding is None else result.rounding.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------------- чтение


async def get_run(
    session: AsyncSession, *, workspace_id: uuid.UUID, run_id: uuid.UUID
) -> CalcRun | None:
    result = await session.scalars(
        select(CalcRun)
        .where(CalcRun.id == run_id, CalcRun.workspace_id == workspace_id)
        .options(selectinload(CalcRun.steps), selectinload(CalcRun.results))
    )
    return result.one_or_none()


async def list_runs(session: AsyncSession, *, project_id: uuid.UUID) -> Sequence[CalcRun]:
    result = await session.scalars(
        select(CalcRun)
        .where(CalcRun.project_id == project_id)
        .order_by(CalcRun.created_at.desc(), CalcRun.id)
    )
    return result.all()


# ----------------------------------------------------------------------------------- повтор


async def replay(session: AsyncSession, run: CalcRun) -> CalcRunReplayRead:
    """Повтор из снимка и версий правил самого запуска — без чтения текущих реестров.

    Если калькулятора или реализации этой версии в коде больше нет или их семантика
    изменилась, повтор честно отказывает, а не считает новым алгоритмом.
    """
    stored = run_read(run)

    def refused(*problems: str) -> CalcRunReplayRead:
        return CalcRunReplayRead(
            run_id=run.id,
            reproducible=False,
            original_result_sha256=run.result_sha256,
            replay_result_sha256=None,
            problems=list(problems),
        )

    if run.status is not CalcRunStatus.SUCCEEDED:
        return refused("повторяется только успешный запуск")
    definition = calculator(run.calculator_id, run.calculator_version)
    if definition is None:
        return refused(
            f"калькулятора {run.calculator_id}@{run.calculator_version} больше нет в коде"
        )
    problems: list[str] = []
    if definition.sha256 != run.calculator_sha256:
        problems.append(
            f"определение {run.calculator_id}@{run.calculator_version} изменилось после запуска"
        )
    rules: dict[str, RuleOutcome] = {}
    for binding in stored.rule_bindings:
        handler = HANDLERS.get(binding.implementation_key)
        if handler is None:
            problems.append(f"реализации {binding.implementation_key} больше нет в коде")
        elif handler.semantics_sha256 != binding.handler_semantics_sha256:
            problems.append(
                f"семантика реализации {binding.implementation_key} изменилась — повтор "
                "новым алгоритмом был бы подменой"
            )
        version = await session.get(CalcRuleVersion, binding.rule_version_id)
        if version is None or version.content_sha256 != binding.content_sha256:
            problems.append(f"версия {binding.rule_key}@{binding.version} в реестре не та же")
        rules[binding.rule_key] = ResolvedRule(
            rule_key=binding.rule_key,
            rule_version_id=binding.rule_version_id,
            version=binding.version,
            status=CalcRuleStatus.APPROVED,
            rule_type=binding.rule_type,
            content=binding.content,
            content_sha256=binding.content_sha256,
        )
    if problems:
        return refused(*problems)

    facts: dict[str, FactOutcome] = {item.fact_key: item for item in stored.snapshot.items}
    plan = planner.plan(definition, run.scenario, stored.scope, facts, rules, HANDLERS)
    if not plan.valid:
        return refused(*(reason.message for reason in plan.reasons))
    try:
        execution = execute(plan, run.id, {})
    except StepExecutionError as error:
        return refused(f"шаг {error.step_key}: {error.message}")
    return CalcRunReplayRead(
        run_id=run.id,
        reproducible=execution.result_sha256 == run.result_sha256,
        original_result_sha256=run.result_sha256,
        replay_result_sha256=execution.result_sha256,
        problems=[]
        if execution.result_sha256 == run.result_sha256
        else ["повтор дал другой результат"],
    )
