"""Расчётный паспорт системы ВК (PROMPT 06): сборка разделов и статуса. Чистые функции.

Паспорт отвечает на вопросы: что за система и что она значит в проекте; какие исходные данные
использованы и каких нет (и что именно без них не определяется); какие конфликты ждут решения;
что рассчитано; какая структура; какие объёмы; какие допущения; что Quantor определить не может.
Каждая позиция раскрывается цепочкой до свидетельства (`trace.py`).

Статус: BLOCKED — расчёт системы нельзя корректно начать (назначение не подтверждено, запуск
заблокирован); READY — всё определено (диапазоны допустимы); иначе PARTIAL: надёжно
определённое показывается, неопределённое названо, а не спрятано.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.contracts.calc.engine import CalcBlockingReason, CalcRunRead
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcCompleteness,
    CalcPassportStatus,
    CalcQuantityCategory,
    CalcRuleReadiness,
    CalcRunStatus,
    CalcScenario,
    CalcSemanticsStatus,
    CalcSynthesisStatus,
)
from app.contracts.calc.passport import (
    CalcExpectedQuantityBody,
    CalcPassportBody,
    CalcPassportIssue,
    CalcPassportRule,
)
from app.contracts.calc.readiness import CalcSystemReadinessRead
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcSynthesisRunRead, CalcSystemGraph
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.systems.vk import passport_sections as sections
from app.services.calc.systems.vk.readiness import function_title, input_counts
from app.services.calc.systems.vk.spec import VkSystemSpec

_RULE_CODES = frozenset(
    {
        CalcBlockCode.RULE_NOT_FOUND,
        CalcBlockCode.RULE_NOT_APPROVED,
        CalcBlockCode.RULE_NOT_EFFECTIVE,
        CalcBlockCode.RULE_NOT_APPLICABLE,
    }
)
_DETERMINED = frozenset({CalcCompleteness.COMPLETE, CalcCompleteness.RANGE})


@dataclass(frozen=True)
class ScenarioOutcome:
    scenario: CalcScenario
    calculation: CalcRunRead | None
    synthesis: CalcSynthesisRunRead | None
    graph: CalcSystemGraph | None
    rows: tuple[CalcExpectedQuantityBody, ...]


@dataclass(frozen=True)
class PassportInputs:
    spec: VkSystemSpec
    scope: CalcFactSubject
    semantics: CalcSemanticsStatus
    semantics_note: str
    readiness: CalcSystemReadinessRead | None
    rules: tuple[CalcPassportRule, ...]
    outcomes: Mapping[CalcScenario, ScenarioOutcome]
    definition: CalculatorDef


def _step_issues(
    inputs: PassportInputs, run: CalcRunRead | None, rows: Sequence[CalcExpectedQuantityBody]
) -> list[CalcPassportIssue]:
    if run is None:
        return []
    grouped: dict[str, list[CalcBlockingReason]] = {}
    for reason in run.blocking_reasons:
        if reason.step_key is not None:
            grouped.setdefault(reason.step_key, []).append(reason)
    titles = {step.step_key: step.title for step in inputs.definition.steps}
    issues: list[CalcPassportIssue] = []
    for step_key, reasons in grouped.items():
        rule_keys = sorted({item.rule_key for item in reasons if item.rule_key})
        needed = (
            "утверждённая версия правила " + ", ".join(rule_keys)
            if any(item.code in _RULE_CODES for item in reasons) and rule_keys
            else "исходные данные объекта: " + "; ".join(item.message for item in reasons[:3])
        )
        blocks, not_blocks = sections.blocks_of([f"step:{step_key}"], rows)
        issues.append(
            CalcPassportIssue(
                key=f"step:{step_key}",
                title=titles.get(step_key, step_key),
                kind=None,
                known="; ".join(item.message for item in reasons[:3]),
                needed=needed,
                structural=False,
                blocks=blocks,
                not_blocks=not_blocks if blocks else [],
            )
        )
    return issues


def unresolved(inputs: PassportInputs, expected: ScenarioOutcome | None) -> list[CalcPassportIssue]:
    rows = [] if expected is None else list(expected.rows)
    issues: list[CalcPassportIssue] = []
    if inputs.semantics is not CalcSemanticsStatus.CONFIRMED:
        issues.append(
            CalcPassportIssue(
                key="semantics",
                title=f"Назначение системы {inputs.spec.code}",
                kind=None,
                known=inputs.semantics_note,
                needed="легенда, пояснительная записка или подтверждение инженера",
                structural=True,
                blocks=["весь расчёт системы"],
                not_blocks=[],
            )
        )
    graph = None if expected is None else expected.graph
    if expected is not None and expected.calculation is not None and graph is None:
        issues.append(
            CalcPassportIssue(
                key="synthesis",
                title="Структура системы",
                kind=None,
                known="синтез структуры не выполнен",
                needed="успешный запуск синтеза",
                structural=True,
                blocks=[row.title for row in rows],
                not_blocks=[],
            )
        )
    for item in [] if graph is None else graph.unresolved:
        blocks, not_blocks = sections.blocks_of([item.key], rows)
        issues.append(
            CalcPassportIssue(
                key=item.key,
                title=item.title,
                kind=item.kind,
                known=item.known,
                needed=item.needed,
                structural=item.structural,
                blocks=blocks,
                not_blocks=not_blocks if blocks else [],
            )
        )
    issues += _step_issues(inputs, None if expected is None else expected.calculation, rows)
    return issues


def _status(inputs: PassportInputs, expected: ScenarioOutcome | None) -> CalcPassportStatus:
    calculation = None if expected is None else expected.calculation
    if (
        inputs.semantics is not CalcSemanticsStatus.CONFIRMED
        or calculation is None
        or calculation.status in (CalcRunStatus.BLOCKED, CalcRunStatus.FAILED)
    ):
        return CalcPassportStatus.BLOCKED
    synthesis = None if expected is None else expected.synthesis
    rows = [] if expected is None else expected.rows
    if (
        calculation.status is CalcRunStatus.SUCCEEDED
        and synthesis is not None
        and synthesis.status is CalcSynthesisStatus.SUCCEEDED
        and all(row.completeness in _DETERMINED for row in rows)
    ):
        return CalcPassportStatus.READY
    return CalcPassportStatus.PARTIAL


def _highlights(expected: ScenarioOutcome | None) -> list[str]:
    if expected is None or expected.calculation is None:
        return []
    results = {item.result_key: item.value for item in expected.calculation.results}
    lines: list[str] = []
    if "structure.served_floors" in results:
        lines.append(
            f"Этажей с квартирами: {results['structure.served_floors']} (верхний — "
            f"{results.get('structure.top_floor', '?')}-й), квартир "
            f"{results.get('structure.apartments_total', '?')}"
        )
    if "structure.interfloor_length" in results:
        span = results["structure.interfloor_length"].replace(".", ",")
        lines.append(f"Межэтажный пролёт стояка: {span} м на стояк")
    for element in sections.structure(expected.graph):
        if element.element_id in ("risers", "zones"):
            lines.append(f"{element.title}: {element.count}")
    for row in expected.rows:
        if row.category is not CalcQuantityCategory.PIPE or row.aggregate:
            continue
        amount = row.amount
        shown = amount.value or (f"{amount.low}–{amount.high}" if amount.low else None)
        if shown is None:
            lines.append(f"{row.title}: не определено")
        else:
            prefix = "подтверждаемая часть " if row.completeness is CalcCompleteness.PARTIAL else ""
            lines.append(f"{row.title}: {prefix}{shown.replace('.', ',')} м")
    return lines


def _problems(inputs: PassportInputs, issues: Sequence[CalcPassportIssue]) -> list[str]:
    lines = [f"{item.title}: {item.needed}" for item in issues if item.structural][:4]
    missing_required = [
        row.title
        for row in ([] if inputs.readiness is None else inputs.readiness.rows)
        if row.level.value == "REQUIRED" and row.status.value not in ("FOUND", "DERIVABLE")
    ]
    if missing_required:
        lines.append("Нет обязательных данных: " + ", ".join(missing_required))
    waiting = [
        rule
        for rule in inputs.rules
        if rule.status in (CalcRuleReadiness.DRAFT, CalcRuleReadiness.SOURCE_REQUIRED)
    ]
    if waiting:
        lines.append(f"Правил, ожидающих инженера: {len(waiting)}")
    return lines


def assemble(inputs: PassportInputs) -> tuple[CalcPassportStatus, CalcPassportBody]:
    expected = inputs.outcomes.get(CalcScenario.EXPECTED)
    tender = inputs.outcomes.get(CalcScenario.TENDER_SAFE)
    rows = [] if expected is None else list(expected.rows)
    calculation = None if expected is None else expected.calculation
    issues = unresolved(inputs, expected)
    assumptions = [
        f"{item.rule_key}@{item.version}: {item.reason}; разница {item.delta} {item.unit or ''}"
        f"{'; влияние: ' + item.impact if item.impact else ''}"
        for item in (
            [] if tender is None or tender.calculation is None else tender.calculation.assumptions
        )
        if item.applied
    ] or ["TENDER_SAFE = EXPECTED: утверждённых тендерных допущений нет"]
    warnings: list[str] = []
    for outcome in inputs.outcomes.values():
        if outcome.calculation is not None:
            warnings += outcome.calculation.warnings
        if outcome.graph is not None:
            warnings += outcome.graph.warnings
    snapshots = [
        snapshot
        for outcome in (expected,)
        if outcome is not None
        for snapshot in (
            [] if outcome.calculation is None else outcome.calculation.snapshot.items,
            [] if outcome.synthesis is None else outcome.synthesis.snapshot.items,
        )
    ]
    body = CalcPassportBody(
        system_title=inputs.spec.title,
        function=function_title(inputs.spec.function),
        semantics=inputs.semantics,
        semantics_note=inputs.semantics_note,
        highlights=_highlights(expected),
        problems=_problems(inputs, issues),
        inputs=input_counts(inputs.readiness),
        used_facts=sections.used_facts(snapshots),
        missing=sections.missing(inputs.readiness, rows),
        conflicts=sections.conflicts(inputs.readiness, calculation),
        calculation=sections.calculation(calculation),
        checks=sections.checks(calculation, inputs.readiness, inputs.scope.section is not None),
        structure=sections.structure(None if expected is None else expected.graph),
        assumptions=assumptions,
        unresolved=issues,
        rules=list(inputs.rules),
        warnings=list(dict.fromkeys(warnings)),
        completeness=dict(Counter(row.completeness.value for row in rows)),
    )
    return _status(inputs, expected), body
