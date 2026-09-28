"""Представления синтезаторов и запусков синтеза для API — без записи."""

from __future__ import annotations

import uuid

from app.contracts.calc.engine import (
    CalcBlockingReason,
    CalcRuleBinding,
    CalcRunFailure,
    CalcRunVersions,
    CalcSnapshot,
)
from app.contracts.calc.enums import CalcCalculatorKind
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import (
    CalcSynthesisAssumption,
    CalcSynthesisDecisionRead,
    CalcSynthesisRunRead,
    CalcSynthesisRunSummaryRead,
    CalcSynthesisVariant,
    CalcSynthesizerRead,
    CalcSystemGraph,
    CalcUnresolvedItem,
)
from app.models import CalcSynthesisRun
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.synthesis.definitions import SynthesizerDef


def synthesizer_read(definition: SynthesizerDef) -> CalcSynthesizerRead:
    return CalcSynthesizerRead(
        synthesizer_id=definition.synthesizer_id,
        version=definition.version,
        title=definition.title,
        kind=definition.kind,
        discipline=definition.discipline,
        systems=list(definition.systems),
        stage=definition.stage,
        scenarios=sorted(definition.scenarios, key=lambda item: item.value),
        graph_type=definition.graph_type,
        calculator_id=definition.calculator_id,
        calculator_version=definition.calculator_version,
        results=list(definition.results),
        facts=[spec.fact_type for spec in definition.facts.values()],
        rules=[spec.rule_key for spec in definition.rules.values()],
        synthesizer_sha256=definition.sha256,
        implementation_sha256=definition.implementation_sha256,
    )


def list_synthesizers(*, include_demo: bool = False) -> list[CalcSynthesizerRead]:
    """Демонстрационные синтезаторы в пользовательском списке скрыты (решение владельца)."""
    return [
        synthesizer_read(item)
        for _, item in sorted(SYNTHESIZERS.items())
        if include_demo or item.kind is not CalcCalculatorKind.DEMO
    ]


def summary_read(run: CalcSynthesisRun) -> CalcSynthesisRunSummaryRead:
    blocking = (
        str(run.blocking_reasons[0]["message"])
        if run.blocking_reasons
        else str(run.failure["message"])
        if run.failure is not None
        else None
    )
    return CalcSynthesisRunSummaryRead(
        id=run.id,
        project_id=run.project_id,
        calculation_run_id=run.calculation_run_id,
        synthesizer_id=run.synthesizer_id,
        synthesizer_version=run.synthesizer_version,
        synthesizer_title=run.synthesizer_title,
        scenario=run.scenario,
        status=run.status,
        nodes_count=run.nodes_count,
        unresolved_count=run.unresolved_count,
        blocking=blocking,
        graph_sha256=run.graph_sha256,
        created_by=run.created_by,
        created_at=run.created_at,
    )


def run_read(
    run: CalcSynthesisRun, decisions: list[CalcSynthesisDecisionRead]
) -> CalcSynthesisRunRead:
    inputs = [CalcSynthesisDecisionRead.model_validate(item) for item in run.decision_inputs]
    applied = {uuid.UUID(item) for item in run.applied_decision_ids}
    return CalcSynthesisRunRead(
        **summary_read(run).model_dump(),
        scope=CalcFactSubject.model_validate(run.scope),
        idempotency_key=run.idempotency_key,
        synthesizer_sha256=run.synthesizer_sha256,
        implementation_sha256=run.implementation_sha256,
        versions=CalcRunVersions.model_validate(run.versions),
        calculation_result_sha256=run.calculation_result_sha256,
        snapshot=CalcSnapshot.model_validate(run.snapshot),
        rule_bindings=[CalcRuleBinding.model_validate(item) for item in run.rule_bindings],
        rule_bindings_sha256=run.rule_bindings_sha256,
        applied_decisions=[item for item in inputs if item.id in applied],
        blocking_reasons=[CalcBlockingReason.model_validate(item) for item in run.blocking_reasons],
        failure=None if run.failure is None else CalcRunFailure.model_validate(run.failure),
        unresolved=[CalcUnresolvedItem.model_validate(item) for item in run.unresolved],
        variants=[CalcSynthesisVariant.model_validate(item) for item in run.variants],
        assumptions=[CalcSynthesisAssumption.model_validate(item) for item in run.assumptions],
        warnings=list(run.warnings),
        decisions=decisions,
    )


def graph_read(run: CalcSynthesisRun) -> CalcSystemGraph | None:
    return None if run.graph is None else CalcSystemGraph.model_validate(run.graph)
