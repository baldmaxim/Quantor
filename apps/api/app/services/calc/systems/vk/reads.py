"""Чтение паспортов и позиций и «почему это количество такое» (PROMPT 06).

Объяснение позиции собирается из сохранённых запусков, без модели:

позиция → составляющие (известные и «не определено») → элементы графа (синтез: основание,
правило, решение) → результаты расчёта → шаги → версии правил → факты → свидетельства;
тендерный резерв — отдельным узлом допущения; блокирующие неопределённости — узлами «не
определено» с причиной.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.calc.engine import CalcAssumptionRecord, CalcRunRead
from app.contracts.calc.enums import CalcScenario, CalcSynthesisTraceKind
from app.contracts.calc.passport import (
    CalcAmount,
    CalcExpectedQuantityBody,
    CalcExpectedQuantityRead,
    CalcPassportBody,
    CalcPassportRead,
    CalcPassportRun,
    CalcPassportSummaryRead,
    CalcQuantityTraceRead,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcSynthesisTraceNode, CalcSystemGraph
from app.contracts.calc.units import UNITS
from app.models import CalcExpectedQuantity, CalcPassport
from app.services.calc.engine import runs as engine_runs
from app.services.calc.engine.numbers import parse_exact, ru_number
from app.services.calc.engine.reads import run_read as calculation_read
from app.services.calc.engine.trace import explain
from app.services.calc.synthesis import reads as synthesis_reads
from app.services.calc.synthesis import runs as synthesis_runs
from app.services.calc.synthesis.trace import element_trace


def summary_read(passport: CalcPassport) -> CalcPassportSummaryRead:
    body = CalcPassportBody.model_validate(passport.body)
    return CalcPassportSummaryRead(
        id=passport.id,
        batch_id=passport.batch_id,
        project_id=passport.project_id,
        system_code=passport.system_code,
        system_title=passport.system_title,
        scope=CalcFactSubject.model_validate(passport.scope),
        status=passport.status,
        calculator_id=passport.calculator_id,
        calculator_version=passport.calculator_version,
        synthesizer_id=passport.synthesizer_id,
        synthesizer_version=passport.synthesizer_version,
        quantities_count=passport.quantities_count,
        highlights=body.highlights,
        problems=body.problems,
        passport_sha256=passport.passport_sha256,
        created_by=passport.created_by,
        created_at=passport.created_at,
    )


def passport_read(passport: CalcPassport) -> CalcPassportRead:
    return CalcPassportRead(
        **summary_read(passport).model_dump(),
        runs=[CalcPassportRun.model_validate(item) for item in passport.runs],
        body=CalcPassportBody.model_validate(passport.body),
    )


def quantity_read(row: CalcExpectedQuantity) -> CalcExpectedQuantityRead:
    return CalcExpectedQuantityRead.model_validate(
        {**row.body, "id": row.id, "passport_id": row.passport_id}
    )


def run_of(passport: CalcPassport, scenario: CalcScenario) -> CalcPassportRun | None:
    runs = [CalcPassportRun.model_validate(item) for item in passport.runs]
    return next((item for item in runs if item.scenario is scenario), None)


async def graph_of(
    session: AsyncSession, passport: CalcPassport, scenario: CalcScenario
) -> CalcSystemGraph | None:
    run = run_of(passport, scenario)
    if run is None or run.synthesis_run_id is None:
        return None
    synthesis = await synthesis_runs.get(
        session, workspace_id=passport.workspace_id, run_id=run.synthesis_run_id
    )
    return None if synthesis is None else synthesis_reads.graph_read(synthesis)


async def assumptions_of(
    session: AsyncSession, passport: CalcPassport
) -> list[CalcAssumptionRecord]:
    """Допущения всех сценариев: применённые (TENDER_SAFE) и не применённые с причиной."""
    found: list[CalcAssumptionRecord] = []
    for scenario in CalcScenario:
        run = run_of(passport, scenario)
        if run is None or run.calculation_run_id is None:
            continue
        calculation = await engine_runs.get_run(
            session, workspace_id=passport.workspace_id, run_id=run.calculation_run_id
        )
        if calculation is not None:
            found += calculation_read(calculation).assumptions
    return found


def _amount_text(amount: CalcAmount, unit: str) -> str:
    title = UNITS[unit].title if unit in UNITS else unit
    if amount.value is not None:
        return f"{ru_number(parse_exact(amount.value))} {title}"
    if amount.low is not None and amount.high is not None:
        low, high = ru_number(parse_exact(amount.low)), ru_number(parse_exact(amount.high))
        return f"{low}–{high} {title}"
    return "не определено"


def _components(body: CalcExpectedQuantityBody) -> list[CalcSynthesisTraceNode]:
    nodes = [
        CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.COMPONENT,
            key=item.key,
            title=item.title,
            text=_amount_text(item.amount, item.unit)
            + ("" if item.note is None else f" — {item.note}"),
        )
        for item in body.components
    ]
    if body.reserve is not None:
        reserve = body.reserve
        nodes.append(
            CalcSynthesisTraceNode(
                kind=CalcSynthesisTraceKind.ASSUMPTION,
                key=f"{reserve.rule_key}@{reserve.version}",
                title="Тендерный резерв — отдельно от базы",
                text=f"{_amount_text(reserve.amount, reserve.unit)}: {reserve.reason}. Влияние: "
                f"{reserve.impact or 'не описано'}",
            )
        )
    nodes += [
        CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.COMPONENT,
            key=f"blocked:{key}",
            title="Не определено",
            text=f"нужно: {key}",
        )
        for key in body.blocked_by
    ]
    return nodes


async def _calculation(
    session: AsyncSession, passport: CalcPassport, run_id: uuid.UUID
) -> CalcRunRead | None:
    run = await engine_runs.get_run(session, workspace_id=passport.workspace_id, run_id=run_id)
    return None if run is None else calculation_read(run)


async def quantity_trace(
    session: AsyncSession, row: CalcExpectedQuantity, passport: CalcPassport
) -> CalcQuantityTraceRead:
    body = quantity_read(row)
    children = _components(body)
    calculation = (
        None
        if body.calculation_run_id is None
        else await _calculation(session, passport, body.calculation_run_id)
    )
    covered: set[str] = set()
    if body.synthesis_run_id is not None and calculation is not None:
        synthesis = await synthesis_runs.get(
            session, workspace_id=passport.workspace_id, run_id=body.synthesis_run_id
        )
        graph = None if synthesis is None else synthesis_reads.graph_read(synthesis)
        if synthesis is not None and graph is not None:
            run = synthesis_reads.run_read(synthesis, [])
            known = {item.id for item in (*graph.nodes, *graph.edges)}
            for element_id in body.element_ids:
                if element_id not in known:
                    continue
                traced = element_trace(run, graph, calculation, element_id)
                children.append(traced.root)
                covered |= {
                    source.key
                    for element in (*graph.nodes, *graph.edges)
                    if element.id == element_id
                    for source in element.sources
                }
    if calculation is not None:
        present = {item.result_key for item in calculation.results}
        for key in body.result_keys:
            if key in covered or key not in present:
                continue
            chain = explain(calculation, key)
            children.append(
                CalcSynthesisTraceNode(
                    kind=CalcSynthesisTraceKind.CALCULATION_RESULT,
                    key=key,
                    title=chain.root.title,
                    text=chain.text,
                    ref=str(calculation.id),
                    calculation=chain,
                )
            )
    text = f"{body.title}: {_amount_text(body.amount, body.unit)}. {body.explanation}"
    if body.notice:
        text += f". {body.notice}"
    return CalcQuantityTraceRead(
        quantity_id=row.id,
        quantity_key=body.quantity_key,
        scenario=body.scenario,
        text=text,
        root=CalcSynthesisTraceNode(
            kind=CalcSynthesisTraceKind.QUANTITY,
            key=body.quantity_key,
            title=body.title,
            text=text,
            ref=str(row.id),
            children=children,
        ),
    )
