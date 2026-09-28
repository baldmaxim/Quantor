"""Определения калькуляторов и граф шагов.

Калькулятор — код, версионируемый вместе с приложением: шаги, их правила, привязка входов
правил к фактам и к выходам других шагов, итоговые результаты. Схемы расчёта в базе нет.

Шаг ссылается на правило стабильным ключом: точную утверждённую версию выбирает запуск.
Привязки входов объявлены калькулятором, а контракт — правилом: запуск сверяет одно с другим
и блокируется при расхождении.

Граф проверяется до инженерного расчёта: уникальность ключей, ссылки на существующие шаги и
выходы, отсутствие циклов, порядок исполнения — топологическая сортировка, при равенстве —
порядок объявления, поэтому порядок детерминирован.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from app.contracts.calc.engine import CALCULATOR_ID_PATTERN, STEP_KEY_PATTERN, CalcRoundingPolicy
from app.contracts.calc.enums import (
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcResultCategory,
    CalcRuleType,
    CalcScenario,
)
from app.contracts.calc.fact_types import fact_type_def
from app.contracts.calc.subjects import SUBJECT_FIELDS
from app.services.calc.engine.hashing import canonical_sha256

_CALCULATOR_ID: Final = re.compile(CALCULATOR_ID_PATTERN)
_STEP_KEY: Final = re.compile(STEP_KEY_PATTERN)


@dataclass(frozen=True, slots=True)
class FactBinding:
    """Вход правила из снимка фактов: тип факта и поля области запуска, задающие место."""

    fact_type: str
    subject_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StepBinding:
    """Вход правила — выход другого шага."""

    step_key: str
    output: str


@dataclass(frozen=True, slots=True)
class AssumptionSpec:
    """Шаг тендерного допущения: применяется только в TENDER_SAFE.

    Вне его значение входа `base_input` передаётся без изменения — и это видно в цепочке
    расчёта как «допущение не применено» с причиной.
    """

    base_input: str


@dataclass(frozen=True)
class StepDef:
    step_key: str
    title: str
    rule_key: str
    allowed_rule_types: frozenset[CalcRuleType]
    outputs: tuple[str, ...]
    """Выходы правила, которые калькулятор использует."""
    facts: Mapping[str, FactBinding] = field(default_factory=dict)
    steps: Mapping[str, StepBinding] = field(default_factory=dict)
    assumption: AssumptionSpec | None = None

    @property
    def depends_on(self) -> tuple[str, ...]:
        return tuple(sorted({binding.step_key for binding in self.steps.values()}))


@dataclass(frozen=True, slots=True)
class ResultDef:
    result_key: str
    title: str
    step_key: str
    output: str
    category: CalcResultCategory
    rounding: CalcRoundingPolicy | None = None
    """Округление итогового значения — явное и видимое в цепочке; промежуточные не округляются."""


@dataclass(frozen=True)
class CalculatorDef:
    calculator_id: str
    version: int
    title: str
    kind: CalcCalculatorKind
    discipline: CalcDiscipline
    systems: tuple[str, ...]
    stage: CalcDocumentStage
    scenarios: frozenset[CalcScenario]
    scope_fields: tuple[str, ...]
    """Поля области запуска, без которых калькулятор не запускается."""
    steps: tuple[StepDef, ...]
    results: tuple[ResultDef, ...]

    @property
    def rule_keys(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(step.rule_key for step in self.steps))

    def step(self, step_key: str) -> StepDef:
        return next(item for item in self.steps if item.step_key == step_key)

    def canonical(self) -> dict[str, object]:
        """Каноническое описание — основа отпечатка определения."""
        return {
            "calculator_id": self.calculator_id,
            "version": self.version,
            "kind": self.kind.value,
            "discipline": self.discipline.value,
            "systems": list(self.systems),
            "stage": self.stage.value,
            "scenarios": sorted(item.value for item in self.scenarios),
            "scope_fields": list(self.scope_fields),
            "steps": [
                {
                    "step_key": step.step_key,
                    "rule_key": step.rule_key,
                    "allowed_rule_types": sorted(item.value for item in step.allowed_rule_types),
                    "outputs": list(step.outputs),
                    "facts": {
                        name: {"fact_type": b.fact_type, "subject_fields": list(b.subject_fields)}
                        for name, b in sorted(step.facts.items())
                    },
                    "steps": {
                        name: {"step_key": b.step_key, "output": b.output}
                        for name, b in sorted(step.steps.items())
                    },
                    "assumption": None
                    if step.assumption is None
                    else {"base_input": step.assumption.base_input},
                }
                for step in self.steps
            ],
            "results": [
                {
                    "result_key": result.result_key,
                    "step_key": result.step_key,
                    "output": result.output,
                    "category": result.category.value,
                    "rounding": None
                    if result.rounding is None
                    else result.rounding.model_dump(mode="json"),
                }
                for result in self.results
            ],
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.canonical())


class DefinitionError(ValueError):
    """Определение калькулятора неверно — ошибка до инженерного расчёта."""


def topological_order(steps: Iterable[StepDef]) -> tuple[list[str], list[str]]:
    """Порядок исполнения и ошибки графа: неизвестные зависимости, цикл.

    Алгоритм Кана; из готовых к исполнению берётся первый по порядку объявления.
    """
    declared = list(steps)
    keys = [step.step_key for step in declared]
    problems: list[str] = []
    known = set(keys)
    edges: dict[str, set[str]] = {key: set() for key in keys}
    for step in declared:
        for dependency in step.depends_on:
            if dependency not in known:
                problems.append(f"шаг «{step.step_key}» зависит от неизвестного «{dependency}»")
            else:
                edges[step.step_key].add(dependency)
    if problems:
        return [], problems
    order: list[str] = []
    remaining = dict(edges)
    while remaining:
        ready = [key for key in keys if key in remaining and not remaining[key] - set(order)]
        if not ready:
            cycle = " → ".join(sorted(remaining))
            return [], [f"цикл в графе шагов: {cycle}"]
        order.append(ready[0])
        del remaining[ready[0]]
    return order, []


def definition_problems(definition: CalculatorDef) -> list[str]:
    """Ошибки определения калькулятора. Пустой список — граф можно исполнять."""
    problems: list[str] = []
    if not _CALCULATOR_ID.match(definition.calculator_id):
        problems.append(f"идентификатор «{definition.calculator_id}» не по шаблону")
    if definition.version < 1:
        problems.append("версия калькулятора начинается с 1")
    if not definition.scenarios:
        problems.append("не указан ни один сценарий")
    unknown_scope = set(definition.scope_fields) - set(SUBJECT_FIELDS)
    if unknown_scope:
        problems.append("неизвестные поля области: " + ", ".join(sorted(unknown_scope)))

    keys = [step.step_key for step in definition.steps]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        problems.append("ключи шагов повторяются: " + ", ".join(duplicates))
    for key in keys:
        if not _STEP_KEY.match(key):
            problems.append(f"ключ шага «{key}» не по шаблону")

    outputs = {step.step_key: set(step.outputs) for step in definition.steps}
    for step in definition.steps:
        problems.extend(_step_problems(definition, step, outputs))

    _, graph = topological_order(definition.steps)
    problems.extend(graph)

    result_keys = [result.result_key for result in definition.results]
    if len(set(result_keys)) != len(result_keys):
        problems.append("ключи результатов повторяются")
    for result in definition.results:
        if result.output not in outputs.get(result.step_key, set()):
            problems.append(
                f"результат «{result.result_key}» ссылается на неизвестный выход "
                f"«{result.step_key}.{result.output}»"
            )
    return problems


def _step_problems(
    definition: CalculatorDef, step: StepDef, outputs: Mapping[str, set[str]]
) -> list[str]:
    problems: list[str] = []
    where = f"шаг «{step.step_key}»"
    if not step.outputs:
        problems.append(f"{where}: не указаны выходы")
    overlap = set(step.facts) & set(step.steps)
    if overlap:
        problems.append(f"{where}: вход привязан дважды: " + ", ".join(sorted(overlap)))
    for name, binding in step.facts.items():
        definition_of_fact = fact_type_def(binding.fact_type)
        if definition_of_fact is None:
            problems.append(f"{where}: неизвестный тип факта «{binding.fact_type}»")
        missing = set(binding.subject_fields) - set(definition.scope_fields)
        if missing:
            problems.append(
                f"{where}: вход «{name}» берёт из области поля, которых калькулятор не требует: "
                + ", ".join(sorted(missing))
            )
    for name, link in step.steps.items():
        if link.step_key in outputs and link.output not in outputs[link.step_key]:
            problems.append(
                f"{where}: вход «{name}» ссылается на неизвестный выход «{link.output}»"
            )
    tender = CalcRuleType.TENDER_ASSUMPTION
    if step.assumption is None:
        if tender in step.allowed_rule_types:
            problems.append(f"{where}: тендерное допущение допускается только в шаге допущения")
    else:
        if step.allowed_rule_types != frozenset({tender}):
            problems.append(f"{where}: шаг допущения принимает только TENDER_ASSUMPTION")
        if step.assumption.base_input not in step.steps:
            problems.append(f"{where}: базовый вход допущения должен быть выходом другого шага")
        if len(step.outputs) != 1:
            problems.append(f"{where}: у шага допущения один выход")
    return problems


def build_registry(
    calculators: Iterable[CalculatorDef],
) -> MappingProxyType[tuple[str, int], CalculatorDef]:
    """Статический каталог калькуляторов. Неверное определение — ошибка импорта."""
    registry: dict[tuple[str, int], CalculatorDef] = {}
    for calculator in calculators:
        key = (calculator.calculator_id, calculator.version)
        if key in registry:
            raise DefinitionError(f"калькулятор {key} объявлен дважды")
        problems = definition_problems(calculator)
        if problems:
            raise DefinitionError("; ".join(problems))
        registry[key] = calculator
    return MappingProxyType(registry)
