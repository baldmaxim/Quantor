"""Основа слоя D: входы генерации позиций, диапазоны, построение строки. Чистые функции.

Арифметика слоя D — только примитивы: экземпляры узла × атрибут на экземпляр, сумма
составляющих, ⌈длина / шаг⌉ с записанным округлением. Инженерных чисел здесь нет: шаг
креплений, признак изоляции, резерв — результаты утверждённых правил из запуска расчёта.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal

from app.contracts.calc.engine import CalcAssumptionRecord, CalcResultRead
from app.contracts.calc.enums import (
    CalcCompleteness,
    CalcDiscipline,
    CalcQuantityCategory,
    CalcQuantityDerivation,
    CalcScenario,
)
from app.contracts.calc.passport import (
    MINIMUM_NOTICE,
    CalcAmount,
    CalcExpectedQuantityBody,
    CalcQuantityComponent,
    CalcQuantityReserve,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcQuantityAttr, CalcSystemGraph, CalcSystemNode
from app.services.calc.engine.numbers import exact_text, parse_exact, ru_number
from app.services.calc.synthesis.graph import instances
from app.services.calc.systems.vk.spec import VkSystemSpec

Range = tuple[Decimal, Decimal]


@dataclass(frozen=True)
class VolumeInputs:
    spec: VkSystemSpec
    scenario: CalcScenario
    scope: CalcFactSubject
    graph: CalcSystemGraph | None
    results: Mapping[str, CalcResultRead]
    assumptions: tuple[CalcAssumptionRecord, ...]
    calculation_run_id: uuid.UUID | None
    synthesis_run_id: uuid.UUID | None
    material: str | None
    rule_refs: Mapping[str, str] = field(default_factory=dict)
    """Ключ результата → «правило@версия» шага, который его дал."""
    blocked_steps: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Шаг калькулятора, не давший результата → корневые заблокированные шаги."""


def text_range(value: Range, unit: str) -> str:
    low, high = value
    shown = ru_number(low) if low == high else f"{ru_number(low)}–{ru_number(high)}"
    return f"{shown} {unit}".rstrip()


def times(a: Range, b: Range) -> Range:
    return a[0] * b[0], a[1] * b[1]


def plus(a: Range, b: Range) -> Range:
    return a[0] + b[0], a[1] + b[1]


def ceil_div(a: Range, step: Decimal) -> Range:
    return (
        (a[0] / step).to_integral_value(rounding=ROUND_CEILING),
        (a[1] / step).to_integral_value(rounding=ROUND_CEILING),
    )


def attr_range(attribute: CalcQuantityAttr) -> Range:
    if attribute.value is not None:
        value = parse_exact(attribute.value)
        return value, value
    low = parse_exact(attribute.low or "0")
    return low, parse_exact(attribute.high or attribute.low or "0")


class VolumeContext:
    def __init__(self, inputs: VolumeInputs) -> None:
        self.inputs = inputs
        self.spec = inputs.spec
        self.graph = inputs.graph
        self.minimum = inputs.scenario is CalcScenario.MINIMUM
        self.rows: list[CalcExpectedQuantityBody] = []

    # --------------------------------------------------------------------------- граф

    def node(self, element_id: str) -> CalcSystemNode | None:
        if self.graph is None:
            return None
        return next((item for item in self.graph.nodes if item.id == element_id), None)

    def has_edge(self, element_id: str) -> bool:
        return self.graph is not None and any(item.id == element_id for item in self.graph.edges)

    def count(self, element_id: str) -> Range | None:
        if self.graph is None or (self.node(element_id) is None and not self.has_edge(element_id)):
            return None
        return instances(self.graph, element_id)

    def attribute(self, element_id: str, name: str) -> CalcQuantityAttr | None:
        node = self.node(element_id)
        if node is None:
            return None
        return next((item for item in node.attributes if item.name == name), None)

    def text(self, value: Range, unit: str) -> str:
        """Значение для пояснения: в MINIMUM — нижняя граница, как и в самой позиции."""
        return text_range((value[0], value[0]) if self.minimum else value, unit)

    def structure_blockers(self) -> list[str]:
        """Почему нет подключений: нет стояков, нет этажей с квартирами, нет схемы."""
        keys = [] if self.node("risers") is not None else ["risers.count"]
        keys += [] if self.node("served_floors") is not None else ["floors"]
        return keys + self.issue_keys("topology")

    def issue_keys(self, *keys: str) -> list[str]:
        """Ключи неопределённостей графа из числа названных — только те, что в графе есть."""
        if self.graph is None:
            return ["synthesis"]
        present = {item.key for item in self.graph.unresolved}
        return [key for key in keys if key in present]

    def step_block(self, step_key: str) -> list[str]:
        roots = self.inputs.blocked_steps.get(step_key)
        return [f"step:{item}" for item in (roots or (step_key,))]

    # ------------------------------------------------------------------------- расчёт

    def result(self, key: str) -> CalcResultRead | None:
        return self.inputs.results.get(key)

    def value(self, key: str) -> Decimal | None:
        found = self.result(key)
        return None if found is None else parse_exact(found.value)

    def rule_ref(self, key: str) -> list[str]:
        ref = self.inputs.rule_refs.get(key)
        return [] if ref is None else [ref]

    def reserve_per_riser(self) -> CalcAssumptionRecord | None:
        if self.inputs.scenario is not CalcScenario.TENDER_SAFE:
            return None
        return next(
            (
                item
                for item in self.inputs.assumptions
                if item.step_key == "tender_riser_reserve" and item.applied
            ),
            None,
        )

    # ------------------------------------------------------------------------ строки

    def amount(self, value: Range | None) -> CalcAmount:
        if value is None:
            return CalcAmount()
        low, high = value
        if self.minimum or low == high:
            return CalcAmount(value=exact_text(low))
        return CalcAmount(low=exact_text(low), high=exact_text(high))

    def completeness(self, value: Range | None, *, partial: bool = False) -> CalcCompleteness:
        if value is None:
            return CalcCompleteness.BLOCKED
        if partial:
            return CalcCompleteness.PARTIAL
        return CalcCompleteness.COMPLETE if value[0] == value[1] else CalcCompleteness.RANGE

    def component(
        self, key: str, title: str, value: Range | None, unit: str, note: str | None = None
    ) -> CalcQuantityComponent:
        return CalcQuantityComponent(
            key=key,
            title=title,
            amount=self.amount(value),
            unit=unit,
            known=value is not None,
            note=note,
        )

    def add(
        self,
        suffix: str,
        category: CalcQuantityCategory,
        item_type: str,
        title: str,
        *,
        value: Range | None,
        unit: str,
        derivation: CalcQuantityDerivation,
        explanation: str,
        completeness: CalcCompleteness | None = None,
        function: str | None = None,
        size: str | None = None,
        material: str | None = None,
        attributes: Mapping[str, str] | None = None,
        element_ids: Sequence[str] = (),
        result_keys: Sequence[str] = (),
        rule_refs: Sequence[str] = (),
        blocked_by: Sequence[str] = (),
        components: Sequence[CalcQuantityComponent] = (),
        notice: str | None = None,
        warnings: Sequence[str] = (),
        base: Range | None = None,
        reserve: CalcQuantityReserve | None = None,
        assumptions: Sequence[str] = (),
        aggregate: bool = False,
    ) -> CalcExpectedQuantityBody:
        state = completeness or self.completeness(value)
        if self.minimum and value is not None and notice is None:
            notice = MINIMUM_NOTICE
        row = CalcExpectedQuantityBody(
            quantity_key=f"vk.{self.spec.slug}.{suffix}",
            system_code=self.spec.code,
            discipline=CalcDiscipline.VK,
            scope=self.inputs.scope,
            scenario=self.inputs.scenario,
            category=category,
            item_type=item_type,
            title=title,
            function=function,
            attributes=dict(attributes or {}),
            material=material,
            size=size,
            amount=self.amount(value),
            unit=unit,
            base=None if base is None else self.amount(base),
            reserve=reserve,
            completeness=state,
            derivation=CalcQuantityDerivation.NOT_DETERMINED
            if state is CalcCompleteness.BLOCKED
            else derivation,
            aggregate=aggregate,
            calculation_run_id=self.inputs.calculation_run_id,
            synthesis_run_id=self.inputs.synthesis_run_id,
            element_ids=list(element_ids),
            result_keys=list(result_keys),
            rule_refs=sorted(set(rule_refs)),
            assumptions=list(assumptions),
            warnings=list(warnings),
            blocked_by=list(dict.fromkeys(blocked_by))
            if state is CalcCompleteness.BLOCKED or state is CalcCompleteness.PARTIAL
            else [],
            components=list(components),
            notice=notice,
            explanation=explanation,
        )
        self.rows.append(row)
        return row

    def element_rules(self, *element_ids: str) -> list[str]:
        refs: list[str] = []
        for element_id in element_ids:
            node = self.node(element_id)
            if node is not None:
                refs += [f"{item.rule_key}@{item.version}" for item in node.rules]
        return refs
