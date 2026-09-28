"""Представления запусков и калькуляторов для API — без записи и без расчёта."""

from __future__ import annotations

from app.contracts.calc.engine import (
    CalcAssumptionRecord,
    CalcBlockingReason,
    CalcCalculatorFactRead,
    CalcCalculatorRead,
    CalcCalculatorResultRead,
    CalcCalculatorStepRead,
    CalcResultRead,
    CalcRoundingRecord,
    CalcRuleBinding,
    CalcRuleRef,
    CalcRunFailure,
    CalcRunRead,
    CalcRunSummaryRead,
    CalcRunVersions,
    CalcSnapshot,
    CalcStepInput,
    CalcStepOutput,
    CalcStepRead,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.models import CalcRun, CalcRunResult, CalcRunStep
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.catalog import CALCULATORS


def calculator_read(definition: CalculatorDef) -> CalcCalculatorRead:
    return CalcCalculatorRead(
        calculator_id=definition.calculator_id,
        version=definition.version,
        title=definition.title,
        kind=definition.kind,
        discipline=definition.discipline,
        systems=list(definition.systems),
        stage=definition.stage,
        scenarios=sorted(definition.scenarios, key=lambda item: item.value),
        scope_fields=list(definition.scope_fields),
        calculator_sha256=definition.sha256,
        facts=[
            CalcCalculatorFactRead(
                step_key=step.step_key,
                input=name,
                fact_type=binding.fact_type,
                subject_fields=list(binding.subject_fields),
            )
            for step in definition.steps
            for name, binding in step.facts.items()
        ],
        rules=list(definition.rule_keys),
        steps=[
            CalcCalculatorStepRead(
                step_key=step.step_key,
                title=step.title,
                rule_key=step.rule_key,
                allowed_rule_types=sorted(step.allowed_rule_types, key=lambda item: item.value),
                depends_on=list(step.depends_on),
                assumption=step.assumption is not None,
            )
            for step in definition.steps
        ],
        results=[
            CalcCalculatorResultRead(
                result_key=result.result_key,
                title=result.title,
                step_key=result.step_key,
                output=result.output,
                category=result.category,
                rounding=result.rounding,
            )
            for result in definition.results
        ],
    )


def list_calculators() -> list[CalcCalculatorRead]:
    return [calculator_read(item) for _, item in sorted(CALCULATORS.items())]


def _blocking(run: CalcRun) -> str | None:
    if run.blocking_reasons:
        return str(run.blocking_reasons[0]["message"])
    if run.failure is not None:
        return str(run.failure["message"])
    return None


def summary_read(run: CalcRun) -> CalcRunSummaryRead:
    return CalcRunSummaryRead(
        id=run.id,
        project_id=run.project_id,
        calculator_id=run.calculator_id,
        calculator_version=run.calculator_version,
        calculator_title=run.calculator_title,
        scenario=run.scenario,
        status=run.status,
        results_count=run.results_count,
        blocking=_blocking(run),
        result_sha256=run.result_sha256,
        created_by=run.created_by,
        created_at=run.created_at,
    )


def step_read(row: CalcRunStep) -> CalcStepRead:
    rule = (
        None
        if row.rule_key is None or row.rule_version is None or row.rule_type is None
        else CalcRuleRef(
            rule_key=row.rule_key,
            version=row.rule_version,
            rule_type=row.rule_type,
            content_sha256=row.rule_content_sha256 or "",
            implementation_key=row.implementation_key or "",
        )
    )
    return CalcStepRead(
        step_key=row.step_key,
        position=row.position,
        title=row.title,
        status=row.status,
        rule=rule,
        inputs=[CalcStepInput.model_validate(item) for item in row.inputs],
        parameters=[CalcStepInput.model_validate(item) for item in row.parameters],
        outputs=[CalcStepOutput.model_validate(item) for item in row.outputs],
        roundings=[CalcRoundingRecord.model_validate(item) for item in row.roundings],
        explanation=row.explanation,
        fingerprint=row.fingerprint,
        reused_from_run_id=row.reused_from_run_id,
        assumption=None
        if row.assumption is None
        else CalcAssumptionRecord.model_validate(row.assumption),
    )


def result_read(row: CalcRunResult) -> CalcResultRead:
    return CalcResultRead(
        run_id=row.run_id,
        result_key=row.result_key,
        title=row.title,
        value=row.value,
        unit=row.unit,
        category=row.category,
        discipline=row.discipline,
        system_code=row.system_code,
        scenario=row.scenario,
        step_key=row.step_key,
        output=row.output,
        rounding=None if row.rounding is None else CalcRoundingRecord.model_validate(row.rounding),
    )


def run_read(run: CalcRun) -> CalcRunRead:
    summary = summary_read(run)
    return CalcRunRead(
        **summary.model_dump(),
        scope=CalcFactSubject.model_validate(run.scope),
        effective_on=run.effective_on,
        idempotency_key=run.idempotency_key,
        calculator_sha256=run.calculator_sha256,
        versions=CalcRunVersions.model_validate(run.versions),
        snapshot=CalcSnapshot.model_validate(run.snapshot),
        rule_bindings=[CalcRuleBinding.model_validate(item) for item in run.rule_bindings],
        rule_bindings_sha256=run.rule_bindings_sha256,
        blocking_reasons=[CalcBlockingReason.model_validate(item) for item in run.blocking_reasons],
        failure=None if run.failure is None else CalcRunFailure.model_validate(run.failure),
        assumptions=[CalcAssumptionRecord.model_validate(item) for item in run.assumptions],
        warnings=list(run.warnings),
        steps=[step_read(row) for row in run.steps],
        results=[result_read(row) for row in run.results],
    )
