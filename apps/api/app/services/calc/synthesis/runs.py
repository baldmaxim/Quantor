"""Запуски синтеза: подготовка, запуск, хранение, решения инженера, повтор.

Порядок данных только один: факты → расчёт → синтез. Синтез читает исходный запуск расчёта
(неизменяемый), дополнительные факты для структуры — тем же строгим допуском, что ядро, — и
утверждённые правила; ничего из этого не меняет. Гипотеза синтеза не пишется в реестр фактов.

Запуск синхронный, одной транзакцией, записывается сразу итогом — BLOCKED, PARTIAL, SUCCEEDED
или FAILED — и больше не меняется (триггер базы). Повтор читает только сам запуск и исходный
запуск расчёта.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.calc.engine import (
    CalcBlockingReason,
    CalcResultRead,
    CalcRuleBinding,
    CalcSnapshot,
)
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcRuleStatus,
    CalcRunStatus,
    CalcSynthesisStatus,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import (
    CalcSynthesisDecisionCreate,
    CalcSynthesisDecisionRead,
    CalcSynthesisReplayRead,
    CalcSynthesisRunCreate,
    CalcSynthesisValidateRead,
    CalcSystemGraph,
)
from app.errors import DomainError, ErrorCode
from app.models import CalcRuleVersion, CalcRun, CalcSynthesisDecision, CalcSynthesisRun
from app.services.calc.engine import runs as engine_runs
from app.services.calc.engine.catalog import HANDLERS
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.inputs import fact_outcomes, rule_outcomes, snapshot_of
from app.services.calc.engine.plan_types import Absence, FactOutcome, ResolvedRule, RuleOutcome
from app.services.calc.engine.reads import result_read, run_read
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.synthesis.definitions import (
    DecisionInput,
    SynthesisOutcome,
    SynthesizerDef,
    fact_keys,
    synthesize,
)


def synthesizer(synthesizer_id: str, version: int) -> SynthesizerDef | None:
    return SYNTHESIZERS.get((synthesizer_id, version))


async def _lock(session: AsyncSession, name: str) -> None:
    digest = hashlib.sha256(name.encode()).digest()
    await session.execute(
        select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True)))
    )


def decision_read(row: CalcSynthesisDecision) -> CalcSynthesisDecisionRead:
    return CalcSynthesisDecisionRead.model_validate(row)


async def _decisions(
    session: AsyncSession, project_id: uuid.UUID, ids: Sequence[uuid.UUID]
) -> list[CalcSynthesisDecisionRead]:
    """Решения по идентификаторам в проекте. LookupError — чужое или несуществующее."""
    if not ids:
        return []
    rows = {
        row.id: row
        for row in await session.scalars(
            select(CalcSynthesisDecision).where(
                CalcSynthesisDecision.id.in_(list(ids)),
                CalcSynthesisDecision.project_id == project_id,
            )
        )
    }
    missing = [str(item) for item in ids if item not in rows]
    if missing:
        raise LookupError("решение " + ", ".join(missing))
    return [decision_read(rows[item]) for item in ids]


def _inputs(decisions: Sequence[CalcSynthesisDecisionRead]) -> tuple[DecisionInput, ...]:
    return tuple(
        DecisionInput(
            id=item.id,
            node_id=item.node_id,
            selected_count=item.selected_count,
            comment=item.comment,
        )
        for item in decisions
    )


def _calculation_problem(
    definition: SynthesizerDef, calculation: CalcRun, project_id: uuid.UUID
) -> CalcBlockingReason | None:
    if calculation.project_id != project_id:
        message = "запуск расчёта другого проекта"
    elif calculation.status not in (CalcRunStatus.SUCCEEDED, CalcRunStatus.PARTIAL):
        message = f"запуск расчёта без результатов ({calculation.status.value})"
    elif (calculation.calculator_id, calculation.calculator_version) != (
        definition.calculator_id,
        definition.calculator_version,
    ):
        message = (
            f"синтезатор строит структуру по {definition.calculator_id}@"
            f"{definition.calculator_version}, а запуск — {calculation.calculator_id}@"
            f"{calculation.calculator_version}"
        )
    else:
        return None
    return CalcBlockingReason(code=CalcBlockCode.CALCULATION_NOT_USABLE, message=message)


def _results(calculation: CalcRun) -> dict[str, CalcResultRead]:
    return {row.result_key: result_read(row) for row in calculation.results}


def _blocked(reason: CalcBlockingReason) -> SynthesisOutcome:
    return SynthesisOutcome(
        status=CalcSynthesisStatus.BLOCKED,
        graph=None,
        graph_sha256=None,
        variants=(),
        bindings=(),
        snapshot_items=(),
        reasons=(reason,),
        warnings=(),
        applied_decisions=(),
    )


async def _prepare(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CalcSynthesisRunCreate,
) -> tuple[
    SynthesizerDef,
    CalcRun,
    list[CalcSynthesisDecisionRead],
    dict[str, RuleOutcome],
    SynthesisOutcome,
]:
    """Синтез по текущим реестрам. LookupError — нет синтезатора, запуска или решения."""
    definition = synthesizer(payload.synthesizer_id, payload.synthesizer_version)
    if definition is None:
        raise LookupError(f"{payload.synthesizer_id}@{payload.synthesizer_version}")
    calculation = await engine_runs.get_run(
        session, workspace_id=workspace_id, run_id=payload.calculation_run_id
    )
    if calculation is None:
        raise LookupError("запуск расчёта")
    decisions = await _decisions(session, project_id, payload.decision_ids)
    problem = _calculation_problem(definition, calculation, project_id)
    if problem is not None:
        return definition, calculation, decisions, {}, _blocked(problem)
    scope = CalcFactSubject.model_validate(calculation.scope)
    keys, _ = fact_keys(definition, scope)
    facts = await fact_outcomes(
        session, project_id=project_id, keys=[item.fact_key for item in keys]
    )
    rules = await rule_outcomes(
        session,
        workspace_id=workspace_id,
        rule_keys=[spec.rule_key for spec in definition.rules.values()],
        on=datetime.now(UTC).date(),
    )
    outcome = synthesize(
        definition,
        scenario=calculation.scenario,
        scope=scope,
        calculation_run_id=calculation.id,
        results=_results(calculation),
        facts=facts,
        rules=rules,
        handlers=HANDLERS,
        decisions=_inputs(decisions),
    )
    return definition, calculation, decisions, rules, outcome


async def validate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CalcSynthesisRunCreate,
) -> CalcSynthesisValidateRead:
    definition, calculation, _, _, outcome = await _prepare(
        session, workspace_id=workspace_id, project_id=project_id, payload=payload
    )
    return CalcSynthesisValidateRead(
        synthesizer_id=definition.synthesizer_id,
        synthesizer_version=definition.version,
        scenario=calculation.scenario,
        valid=outcome.status is not CalcSynthesisStatus.BLOCKED,
        blocking_reasons=list(outcome.reasons),
        warnings=list(outcome.warnings),
    )


def _request_sha256(payload: CalcSynthesisRunCreate) -> str:
    return canonical_sha256(
        {
            "calculation_run_id": str(payload.calculation_run_id),
            "synthesizer": [payload.synthesizer_id, payload.synthesizer_version],
            "decision_ids": [str(item) for item in payload.decision_ids],
        }
    )


def _absences(rules: dict[str, RuleOutcome]) -> list[dict[str, str]]:
    return [
        {"rule_key": key, "code": outcome.code.value, "message": outcome.message}
        for key, outcome in sorted(rules.items())
        if isinstance(outcome, Absence)
    ]


async def start(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: CalcSynthesisRunCreate,
    author: uuid.UUID | None,
) -> tuple[CalcSynthesisRun, bool]:
    """Новый запуск синтеза или уже созданный по тому же ключу идемпотентности."""
    request_sha256 = _request_sha256(payload)
    if payload.idempotency_key is not None:
        await _lock(session, f"calc-synthesis|{project_id}|{payload.idempotency_key}")
        existing = await session.scalar(
            select(CalcSynthesisRun).where(
                CalcSynthesisRun.project_id == project_id,
                CalcSynthesisRun.idempotency_key == payload.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_sha256 != request_sha256:
                raise DomainError(ErrorCode.CALC_RUN_IDEMPOTENCY_CONFLICT)
            return existing, False

    definition, calculation, decisions, rules, outcome = await _prepare(
        session, workspace_id=workspace_id, project_id=project_id, payload=payload
    )
    snapshot = snapshot_of(outcome.snapshot_items)
    graph = outcome.graph
    run = CalcSynthesisRun(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        project_id=project_id,
        calculation_run_id=calculation.id,
        calculation_result_sha256=calculation.result_sha256 or "",
        synthesizer_id=definition.synthesizer_id,
        synthesizer_version=definition.version,
        synthesizer_title=definition.title,
        synthesizer_sha256=definition.sha256,
        implementation_sha256=definition.implementation_sha256,
        scenario=calculation.scenario,
        scope=calculation.scope,
        status=outcome.status,
        versions=engine_runs.versions().model_dump(mode="json"),
        snapshot=snapshot.model_dump(mode="json"),
        snapshot_sha256=snapshot.sha256,
        rule_bindings=[item.model_dump(mode="json") for item in outcome.bindings],
        rule_bindings_sha256=canonical_sha256(
            [
                [item.step_key, item.rule_key, item.version, item.content_sha256]
                for item in outcome.bindings
            ]
        ),
        rule_absences=_absences(rules),
        decision_inputs=[item.model_dump(mode="json") for item in decisions],
        applied_decision_ids=[str(item) for item in outcome.applied_decisions],
        graph=None if graph is None else graph.model_dump(mode="json"),
        graph_sha256=outcome.graph_sha256,
        variants=[item.model_dump(mode="json") for item in outcome.variants],
        unresolved=[]
        if graph is None
        else [item.model_dump(mode="json") for item in graph.unresolved],
        assumptions=[]
        if graph is None
        else [item.model_dump(mode="json") for item in graph.assumptions],
        warnings=list(outcome.warnings),
        blocking_reasons=[item.model_dump(mode="json") for item in outcome.reasons],
        failure=None
        if outcome.failure is None
        else {"step_key": None, "error": outcome.failure[0], "message": outcome.failure[1]},
        nodes_count=0 if graph is None else len(graph.nodes),
        unresolved_count=0 if graph is None else len(graph.unresolved),
        idempotency_key=payload.idempotency_key,
        request_sha256=request_sha256,
        created_by=author,
    )
    session.add(run)
    await session.flush()
    return run, True


# ---------------------------------------------------------------------------------- чтение


async def get(
    session: AsyncSession, *, workspace_id: uuid.UUID, run_id: uuid.UUID
) -> CalcSynthesisRun | None:
    result = await session.scalars(
        select(CalcSynthesisRun).where(
            CalcSynthesisRun.id == run_id, CalcSynthesisRun.workspace_id == workspace_id
        )
    )
    return result.one_or_none()


async def list_for_project(
    session: AsyncSession, *, project_id: uuid.UUID
) -> Sequence[CalcSynthesisRun]:
    result = await session.scalars(
        select(CalcSynthesisRun)
        .where(CalcSynthesisRun.project_id == project_id)
        .order_by(CalcSynthesisRun.created_at.desc(), CalcSynthesisRun.id)
    )
    return result.all()


async def decisions_made(
    session: AsyncSession, run: CalcSynthesisRun
) -> list[CalcSynthesisDecisionRead]:
    rows = await session.scalars(
        select(CalcSynthesisDecision)
        .where(CalcSynthesisDecision.synthesis_run_id == run.id)
        .order_by(CalcSynthesisDecision.created_at, CalcSynthesisDecision.id)
    )
    return [decision_read(row) for row in rows]


async def decide(
    session: AsyncSession,
    *,
    run: CalcSynthesisRun,
    payload: CalcSynthesisDecisionCreate,
    author: uuid.UUID | None,
) -> CalcSynthesisDecision:
    """Решение инженера по диапазону кратности запуска. Запуск не меняется."""
    graph = None if run.graph is None else CalcSystemGraph.model_validate(run.graph)
    node = (
        None if graph is None else next((n for n in graph.nodes if n.id == payload.node_id), None)
    )
    if node is None or node.cardinality.min == node.cardinality.max:
        raise DomainError(
            ErrorCode.CALC_SYNTHESIS_DECISION_INVALID,
            "решать можно только кратность-диапазон узла этого запуска",
        )
    alternatives = list(range(node.cardinality.min, node.cardinality.max + 1))
    if payload.selected_count not in alternatives:
        raise DomainError(
            ErrorCode.CALC_SYNTHESIS_DECISION_INVALID,
            f"выбор вне диапазона {node.cardinality.min}–{node.cardinality.max}",
        )
    decision = CalcSynthesisDecision(
        project_id=run.project_id,
        synthesis_run_id=run.id,
        node_id=payload.node_id,
        selected_count=payload.selected_count,
        variant_key=payload.variant_key,
        alternatives=alternatives,
        comment=payload.comment,
        decided_by=author,
    )
    session.add(decision)
    await session.flush()
    return decision


# ----------------------------------------------------------------------------------- повтор


async def replay(session: AsyncSession, run: CalcSynthesisRun) -> CalcSynthesisReplayRead:
    """Повтор из снимка, версий правил и решений самого запуска и его запуска расчёта."""

    def refused(*problems: str) -> CalcSynthesisReplayRead:
        return CalcSynthesisReplayRead(
            run_id=run.id,
            reproducible=False,
            original_graph_sha256=run.graph_sha256,
            replay_graph_sha256=None,
            problems=list(problems),
        )

    if run.graph_sha256 is None:
        return refused("повторяется только запуск с графом (SUCCEEDED или PARTIAL)")
    definition = synthesizer(run.synthesizer_id, run.synthesizer_version)
    if definition is None:
        return refused(
            f"синтезатора {run.synthesizer_id}@{run.synthesizer_version} больше нет в коде"
        )
    problems: list[str] = []
    if definition.implementation_sha256 != run.implementation_sha256:
        problems.append(
            f"реализация {run.synthesizer_id}@{run.synthesizer_version} изменилась после "
            "запуска — повтор новым алгоритмом был бы подменой"
        )
    stored = run_read(await calculation_of(session, run))
    if stored.result_sha256 != run.calculation_result_sha256:
        problems.append("результат исходного запуска расчёта не тот же")
    rules: dict[str, RuleOutcome] = {
        item["rule_key"]: Absence(CalcBlockCode(item["code"]), item["message"])
        for item in run.rule_absences
    }
    for raw in run.rule_bindings:
        binding = CalcRuleBinding.model_validate(raw)
        handler = HANDLERS.get(binding.implementation_key)
        if handler is None or handler.semantics_sha256 != binding.handler_semantics_sha256:
            problems.append(
                f"реализации {binding.implementation_key} в той же семантике больше нет"
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
    snapshot = CalcSnapshot.model_validate(run.snapshot)
    facts: dict[str, FactOutcome] = {item.fact_key: item for item in snapshot.items}
    decisions = [CalcSynthesisDecisionRead.model_validate(item) for item in run.decision_inputs]
    outcome = synthesize(
        definition,
        scenario=run.scenario,
        scope=CalcFactSubject.model_validate(run.scope),
        calculation_run_id=run.calculation_run_id,
        results={item.result_key: item for item in stored.results},
        facts=facts,
        rules=rules,
        handlers=HANDLERS,
        decisions=_inputs(decisions),
    )
    reproducible = outcome.graph_sha256 == run.graph_sha256
    return CalcSynthesisReplayRead(
        run_id=run.id,
        reproducible=reproducible,
        original_graph_sha256=run.graph_sha256,
        replay_graph_sha256=outcome.graph_sha256,
        problems=[] if reproducible else ["повтор дал другой граф"],
    )


async def calculation_of(session: AsyncSession, run: CalcSynthesisRun) -> CalcRun:
    """Исходный запуск расчёта. Он неизменяем и не удаляется из-под синтеза."""
    calculation = await engine_runs.get_run(
        session, workspace_id=run.workspace_id, run_id=run.calculation_run_id
    )
    if calculation is None:
        raise LookupError("запуск расчёта")
    return calculation
