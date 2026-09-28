"""Объяснение результата и сравнение запусков — чистые функции над сохранённым запуском.

Объяснение собирается детерминированно из структуры расчёта, без модели: результат → шаг →
версия правила, допущение, входы → факт → свидетельство, выход другого шага → его шаг и так
до фактов. Текст — пояснения шагов по порядку графа и округление итога.

Сравнение двух запусков одного проекта — анализ инвалидирования: какие факты и версии правил
изменились, у каких шагов сменился отпечаток и почему, какие результаты разошлись.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.contracts.calc.engine import (
    CalcFactDiff,
    CalcResultDiff,
    CalcResultTraceRead,
    CalcRoundingRecord,
    CalcRuleBinding,
    CalcRuleDiff,
    CalcRunCompareRead,
    CalcRunRead,
    CalcSnapshotItem,
    CalcStepDiff,
    CalcStepInput,
    CalcStepRead,
    CalcTraceNode,
)
from app.contracts.calc.enums import (
    CalcInputSource,
    CalcRoundingMode,
    CalcStepStatus,
    CalcTraceKind,
)
from app.contracts.calc.fact_types import fact_type_def
from app.contracts.calc.units import UNITS
from app.contracts.calc.values import CalcCountValue, CalcFactValue, CalcNumberValue
from app.services.calc.engine.numbers import parse_exact, ru_number
from app.services.calc.rules.validation import source_label

_MODE_TITLES: Final = {
    CalcRoundingMode.HALF_UP: "по правилам арифметики",
    CalcRoundingMode.CEILING: "вверх",
    CalcRoundingMode.FLOOR: "вниз",
}


def _with_unit(value: str, unit: str | None) -> str:
    number = ru_number(parse_exact(value))
    return number if unit is None or unit not in UNITS else f"{number} {UNITS[unit].title}"


def _fact_value(value: CalcFactValue) -> str:
    if isinstance(value, CalcNumberValue):
        return _with_unit(value.value, value.unit)
    if isinstance(value, CalcCountValue):
        return _with_unit(str(value.value), value.unit)
    return str(getattr(value, "value", value.kind))


def _rounding_node(record: CalcRoundingRecord) -> CalcTraceNode:
    return CalcTraceNode(
        kind=CalcTraceKind.ROUNDING,
        key=record.target,
        title="Округление",
        value=record.after,
        unit=record.unit,
        text=(
            f"{_with_unit(record.before, record.unit)} → {_with_unit(record.after, record.unit)}: "
            f"{_MODE_TITLES[record.mode]} до {ru_number(parse_exact(record.quantum))} — "
            f"{record.reason}"
        ),
    )


class _Tracer:
    def __init__(self, run: CalcRunRead) -> None:
        self.run = run
        self.steps: Mapping[str, CalcStepRead] = {step.step_key: step for step in run.steps}
        self.facts: Mapping[str, CalcSnapshotItem] = {
            item.fact_key: item for item in run.snapshot.items
        }
        self.bindings: Mapping[str, CalcRuleBinding] = {
            binding.step_key: binding for binding in run.rule_bindings
        }
        self.lines: list[str] = []

    def step_node(self, step_key: str) -> CalcTraceNode:
        step = self.steps[step_key]
        children: list[CalcTraceNode] = []
        binding = self.bindings.get(step_key)
        if binding is not None:
            content = binding.content
            children.append(
                CalcTraceNode(
                    kind=CalcTraceKind.RULE,
                    key=f"{binding.rule_key}@{binding.version}",
                    title=content.title,
                    text=(
                        f"{binding.rule_type.value}; формула: {content.formula}; реализация "
                        f"{binding.implementation_key}; источники: "
                        + ("; ".join(source_label(item) for item in content.sources) or "—")
                    ),
                    ref=str(binding.rule_version_id),
                )
            )
        if step.primitive is not None:
            children.append(
                CalcTraceNode(
                    kind=CalcTraceKind.PRIMITIVE,
                    key=step.primitive.implementation_key,
                    title=step.primitive.title,
                    text="Вычислительный примитив: арифметика по фактам без констант, не "
                    "инженерное правило и не норматив",
                )
            )
        if step.assumption is not None:
            record = step.assumption
            children.append(
                CalcTraceNode(
                    kind=CalcTraceKind.ASSUMPTION,
                    key=step.step_key,
                    title="Тендерное допущение" if record.applied else "Допущение не применено",
                    value=record.delta,
                    unit=record.unit,
                    text=f"{record.reason}. Влияние: {record.impact or 'не описано'}; "
                    f"разница {_with_unit(record.delta, record.unit)}",
                )
            )
        for item in step.inputs:
            children.append(self.input_node(item))
        parameters = {}
        if binding is not None:
            parameters = {item.name: item for item in binding.content.parameters}
        for item in step.parameters:
            described = parameters.get(item.name)
            children.append(
                CalcTraceNode(
                    kind=CalcTraceKind.PARAMETER,
                    key=item.name,
                    title=item.name,
                    value=item.value,
                    unit=item.unit,
                    text=described.description if described is not None else item.name,
                    children=self.conversion(item),
                )
            )
        output = step.outputs[0] if step.outputs else None
        status = (
            f" (результат взят из запуска {step.reused_from_run_id})"
            if step.status is CalcStepStatus.REUSED
            else ""
        )
        self.lines.append(step.explanation + status)
        return CalcTraceNode(
            kind=CalcTraceKind.STEP,
            key=step.step_key,
            title=step.title,
            value=None if output is None else output.value,
            unit=None if output is None else output.unit,
            text=step.explanation + status,
            ref=step.fingerprint,
            children=children,
        )

    def conversion(self, item: CalcStepInput) -> list[CalcTraceNode]:
        if item.conversion is None:
            return []
        conversion = item.conversion
        return [
            CalcTraceNode(
                kind=CalcTraceKind.CONVERSION,
                key=item.name,
                title="Перевод единиц",
                value=conversion.to_value,
                unit=conversion.to_unit,
                text=(
                    f"{_with_unit(conversion.from_value, conversion.from_unit)} = "
                    f"{_with_unit(conversion.to_value, conversion.to_unit)}"
                ),
            )
        ]

    def input_node(self, item: CalcStepInput) -> CalcTraceNode:
        if item.source is CalcInputSource.STEP and item.step_key is not None:
            node = self.step_node(item.step_key)
            node.children = self.conversion(item) + node.children
            return node
        fact = self.facts.get(item.fact_key or "")
        definition = fact_type_def(fact.fact_type) if fact is not None else None
        title = definition.title if definition is not None else (item.fact_key or item.name)
        children = self.conversion(item)
        text = f"{title}: {_with_unit(item.value, item.unit)}"
        if fact is not None:
            if fact.stated_value != fact.value:
                text += f" (заявлено: {_fact_value(fact.stated_value)})"
            text += (
                f"; способ {fact.method.value}, уверенность {fact.confidence.value}, "
                f"выбор {fact.resolution_state.value}"
            )
            children += [
                CalcTraceNode(
                    kind=CalcTraceKind.EVIDENCE,
                    key=str(evidence.id),
                    title=evidence.kind.value,
                    text=", ".join(
                        part
                        for part in (
                            f"ревизия {evidence.document_revision_id}"
                            if evidence.document_revision_id
                            else None,
                            f"стр. {evidence.page_index + 1}"
                            if evidence.page_index is not None
                            else None,
                            evidence.locator,
                            f"блок {evidence.region_id}" if evidence.region_id else None,
                        )
                        if part
                    )
                    or "ручной ввод или допущение",
                    ref=str(evidence.id),
                )
                for evidence in fact.evidence
            ]
        return CalcTraceNode(
            kind=CalcTraceKind.FACT,
            key=item.fact_key or item.name,
            title=title,
            value=item.value,
            unit=item.unit,
            text=text,
            ref=None if item.fact_id is None else str(item.fact_id),
            children=children,
        )


def explain(run: CalcRunRead, result_key: str) -> CalcResultTraceRead:
    """Цепочка объяснения результата. KeyError — такого результата в запуске нет."""
    result = next(item for item in run.results if item.result_key == result_key)
    tracer = _Tracer(run)
    children = [tracer.step_node(result.step_key)]
    if result.rounding is not None:
        children.insert(0, _rounding_node(result.rounding))
    # Строки идут по порядку графа: источники раньше потребителей.
    lines = list(tracer.lines)
    if result.rounding is not None:
        lines.append("Округление: " + children[0].text)
    root = CalcTraceNode(
        kind=CalcTraceKind.RESULT,
        key=result.result_key,
        title=result.title,
        value=result.value,
        unit=result.unit,
        text=f"{result.title} = {_with_unit(result.value, result.unit)}",
        children=children,
    )
    return CalcResultTraceRead(
        run_id=run.id,
        result_key=result.result_key,
        # Единица вида «ст.» уже заканчивается точкой — вторая не нужна.
        text=root.text + (" " if root.text.endswith(".") else ". ") + "; ".join(lines),
        root=root,
    )


# ------------------------------------------------------------------------------ сравнение


def compare(base: CalcRunRead, other: CalcRunRead) -> CalcRunCompareRead:
    base_facts = {item.fact_key: item for item in base.snapshot.items}
    other_facts = {item.fact_key: item for item in other.snapshot.items}
    facts = [
        CalcFactDiff(
            fact_key=key,
            base_value=base_facts[key].value if key in base_facts else None,
            other_value=other_facts[key].value if key in other_facts else None,
            base_fact_id=base_facts[key].fact_id if key in base_facts else None,
            other_fact_id=other_facts[key].fact_id if key in other_facts else None,
        )
        for key in sorted(set(base_facts) | set(other_facts))
        if key not in base_facts
        or key not in other_facts
        or base_facts[key].item_sha256 != other_facts[key].item_sha256
    ]

    base_rules = {item.step_key: item for item in base.rule_bindings}
    other_rules = {item.step_key: item for item in other.rule_bindings}
    rules = [
        CalcRuleDiff(
            step_key=key,
            rule_key=(base_rules.get(key) or other_rules[key]).rule_key,
            base_version=base_rules[key].version if key in base_rules else None,
            other_version=other_rules[key].version if key in other_rules else None,
            base_content_sha256=base_rules[key].content_sha256 if key in base_rules else None,
            other_content_sha256=other_rules[key].content_sha256 if key in other_rules else None,
        )
        for key in sorted(set(base_rules) | set(other_rules))
        if key not in base_rules
        or key not in other_rules
        or base_rules[key].content_sha256 != other_rules[key].content_sha256
    ]

    base_steps = {item.step_key: item for item in base.steps}
    other_steps = {item.step_key: item for item in other.steps}
    changed_rules = {item.step_key for item in rules}
    invalidated: list[CalcStepDiff] = []
    for key in sorted(set(base_steps) | set(other_steps)):
        before, after = base_steps.get(key), other_steps.get(key)
        if before is not None and after is not None and before.fingerprint == after.fingerprint:
            continue
        causes: list[str] = []
        if before is None or after is None:
            causes.append("шага нет в одном из запусков")
        else:
            if base.calculator_sha256 != other.calculator_sha256:
                causes.append("другое определение калькулятора")
            if base.scenario is not other.scenario:
                causes.append("другой сценарий")
            if key in changed_rules:
                causes.append("другая версия правила")
            if [(i.name, i.value, i.unit) for i in before.inputs] != [
                (i.name, i.value, i.unit) for i in after.inputs
            ]:
                causes.append("другие входы")
            if [(i.name, i.value) for i in before.parameters] != [
                (i.name, i.value) for i in after.parameters
            ]:
                causes.append("другие параметры")
            if not causes:
                causes.append("изменился шаг-источник или реализация")
        invalidated.append(
            CalcStepDiff(
                step_key=key,
                base_fingerprint=None if before is None else before.fingerprint,
                other_fingerprint=None if after is None else after.fingerprint,
                causes=causes,
            )
        )

    base_results = {item.result_key: item for item in base.results}
    other_results = {item.result_key: item for item in other.results}
    results = [
        CalcResultDiff(
            result_key=key,
            base_value=base_results[key].value if key in base_results else None,
            other_value=other_results[key].value if key in other_results else None,
            unit=(base_results.get(key) or other_results[key]).unit,
        )
        for key in sorted(set(base_results) | set(other_results))
        if key not in base_results
        or key not in other_results
        or (base_results[key].value, base_results[key].unit)
        != (other_results[key].value, other_results[key].unit)
    ]
    return CalcRunCompareRead(
        base_run_id=base.id,
        other_run_id=other.id,
        same_calculator=(base.calculator_id, base.calculator_version, base.calculator_sha256)
        == (other.calculator_id, other.calculator_version, other.calculator_sha256),
        same_scenario=base.scenario is other.scenario,
        facts=facts,
        rules=rules,
        invalidated_steps=invalidated,
        results=results,
    )
