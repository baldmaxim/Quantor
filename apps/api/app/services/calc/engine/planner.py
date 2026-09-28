"""Планирование запуска: всё, что можно проверить до арифметики. Чистые функции без базы.

На входе — определение калькулятора, сценарий, область, исходы по фактам (значение из снимка
или причина отсутствия) и исходы по правилам (точная версия или причина). На выходе — план
исполнения или полный список причин блокировки: планировщик не останавливается на первой,
чтобы человек увидел всё, чего не хватает.

Здесь ничего не выбирается молча: отсутствие факта, открытый конфликт, диапазон вместо числа,
неутверждённое правило, несовпадение контракта или единиц — причина блокировки, а не ноль,
не умолчание и не значение старого портала.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.contracts.calc.engine import (
    CalcBlockingReason,
    CalcRuleBinding,
    CalcSnapshotItem,
)
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcRuleInputKind,
    CalcRuleType,
    CalcScenario,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcCountValue, CalcNumberValue
from app.services.calc.engine import policy
from app.services.calc.engine.calculators import (
    CalculatorDef,
    StepDef,
    definition_problems,
    topological_order,
)
from app.services.calc.engine.handlers import HandlerSpec
from app.services.calc.engine.plan_types import (
    Absence,
    FactOutcome,
    FactRequirement,
    OutputContract,
    Plan,
    PlannedStep,
    ResolvedRule,
    RuleOutcome,
    contract_problems,
    fact_requirements,
    numeric_unit,
    reason,
    rule_binding,
    scope_problems,
    units_compatible,
)


class _Planner:
    def __init__(
        self,
        definition: CalculatorDef,
        scenario: CalcScenario,
        scope: CalcFactSubject,
        facts: Mapping[str, FactOutcome],
        rules: Mapping[str, RuleOutcome],
        handlers: Mapping[str, HandlerSpec],
        requirements: list[FactRequirement],
    ) -> None:
        self.definition = definition
        self.scenario = scenario
        self.scope = scope
        self.facts = facts
        self.rules = rules
        self.handlers = handlers
        self.requirements = {(item.step_key, item.input): item for item in requirements}
        self.reasons: list[CalcBlockingReason] = []
        self.warnings: list[str] = []
        self.planned: dict[str, PlannedStep] = {}
        self.bindings: list[CalcRuleBinding] = []
        self.used: dict[str, CalcSnapshotItem] = {}
        self.blocked: set[str] = set()

    def block(self, code: CalcBlockCode, message: str, step: StepDef, **refs: str) -> None:
        self.blocked.add(step.step_key)
        self.reasons.append(reason(code, message, step_key=step.step_key, **refs))

    def applicability(self, step: StepDef, rule: ResolvedRule) -> str | None:
        scope = rule.content.applicability
        if self.scope.system_code is not None and self.scope.system_code not in scope.systems:
            return (
                f"правило {rule.rule_key}@{rule.version} применимо к системам "
                f"{', '.join(scope.systems)}, а не к {self.scope.system_code}"
            )
        if self.definition.stage not in scope.stages:
            return (
                f"правило {rule.rule_key}@{rule.version} не применимо к стадии "
                f"{self.definition.stage.value}"
            )
        return None

    def passthrough(
        self, step: StepDef, position: int, reason: str, rule: ResolvedRule | None
    ) -> None:
        base = step.steps[step.assumption.base_input] if step.assumption else None
        upstream = self.planned.get(base.step_key) if base else None
        contract = (
            upstream.outputs.get(base.output) if upstream is not None and base is not None else None
        )
        output = step.outputs[0]
        self.planned[step.step_key] = PlannedStep(
            step=step,
            position=position,
            applied=False,
            not_applied_reason=reason,
            rule=rule,
            handler=None,
            facts={},
            outputs={output: contract or OutputContract(None, None)},
        )

    def plan_assumption(self, step: StepDef, position: int) -> None:
        if not policy.assumptions_apply(self.scenario):
            self.passthrough(step, position, policy.not_applied_reason(self.scenario), None)
            return
        outcome = self.rules.get(step.rule_key)
        if isinstance(outcome, Absence) or outcome is None:
            message = outcome.message if outcome else "правило не найдено"
            reason = f"Допущение не применено: {message}. Значение передано без изменения"
            self.warnings.append(f"{step.step_key}: {reason}")
            self.passthrough(step, position, reason, None)
            return
        if outcome.rule_type is not CalcRuleType.TENDER_ASSUMPTION:
            self.block(
                CalcBlockCode.RULE_TYPE_NOT_ALLOWED,
                f"шаг допущения ждёт TENDER_ASSUMPTION, а версия "
                f"{outcome.rule_key}@{outcome.version} — {outcome.rule_type.value}",
                step,
                rule_key=step.rule_key,
            )
            return
        inapplicable = self.applicability(step, outcome)
        if inapplicable is not None:
            reason = f"Допущение не применено: {inapplicable}. Значение передано без изменения"
            self.warnings.append(f"{step.step_key}: {reason}")
            self.passthrough(step, position, reason, outcome)
            return
        self.plan_rule_step(step, position, outcome)

    def plan_step(self, step: StepDef, position: int) -> None:
        outcome = self.rules.get(step.rule_key)
        if outcome is None:
            outcome = Absence(CalcBlockCode.RULE_NOT_FOUND, f"правила {step.rule_key} нет")
        if isinstance(outcome, Absence):
            self.block(outcome.code, outcome.message, step, rule_key=step.rule_key)
            return
        if outcome.rule_type not in step.allowed_rule_types or not policy.allows(
            self.scenario, outcome.rule_type
        ):
            self.block(
                CalcBlockCode.RULE_TYPE_NOT_ALLOWED,
                f"версия {outcome.rule_key}@{outcome.version} типа {outcome.rule_type.value} "
                f"не допускается шагом или сценарием {self.scenario.value}",
                step,
                rule_key=step.rule_key,
            )
            return
        inapplicable = self.applicability(step, outcome)
        if inapplicable is not None:
            self.block(
                CalcBlockCode.RULE_NOT_APPLICABLE, inapplicable, step, rule_key=step.rule_key
            )
            return
        self.plan_rule_step(step, position, outcome)

    def plan_rule_step(self, step: StepDef, position: int, rule: ResolvedRule) -> None:
        content = rule.content
        key = content.implementation_key
        handler = self.handlers.get(key or "")
        if handler is None:
            self.block(
                CalcBlockCode.IMPLEMENTATION_MISSING,
                f"нет реализации «{key}» для {rule.rule_key}@{rule.version}",
                step,
                rule_key=rule.rule_key,
            )
            return
        for problem in contract_problems(content, handler):
            self.block(CalcBlockCode.RULE_CONTRACT_MISMATCH, problem, step, rule_key=rule.rule_key)
        rule_outputs = {item.name: item for item in content.outputs}
        missing_outputs = set(step.outputs) - set(rule_outputs)
        if missing_outputs:
            self.block(
                CalcBlockCode.RULE_CONTRACT_MISMATCH,
                "у версии правила нет выходов: " + ", ".join(sorted(missing_outputs)),
                step,
                rule_key=rule.rule_key,
            )
        bound = set(step.facts) | set(step.steps)
        declared = {item.name for item in content.inputs}
        if bound != declared:
            self.block(
                CalcBlockCode.RULE_CONTRACT_MISMATCH,
                f"входы версии {rule.rule_key}@{rule.version} ({', '.join(sorted(declared))}) "
                f"не совпадают с привязками калькулятора ({', '.join(sorted(bound))})",
                step,
                rule_key=rule.rule_key,
            )
        facts: dict[str, CalcSnapshotItem] = {}
        for item in content.inputs:
            if item.kind is CalcRuleInputKind.FACT and item.name in step.facts:
                snapshot = self.fact_input(step, item.name, item.fact_type, item.unit, handler)
                if snapshot is not None:
                    facts[item.name] = snapshot
            elif item.kind is CalcRuleInputKind.QUANTITY and item.name in step.steps:
                self.step_input(step, item.name, item.quantity, item.unit)
            elif item.name in bound:
                self.block(
                    CalcBlockCode.RULE_CONTRACT_MISMATCH,
                    f"вход «{item.name}» правила — {item.kind.value}, а калькулятор привязал "
                    "его иначе",
                    step,
                    rule_key=rule.rule_key,
                )
        if step.step_key in self.blocked:
            return
        self.bindings.append(rule_binding(step, rule, handler))
        self.planned[step.step_key] = PlannedStep(
            step=step,
            position=position,
            applied=True,
            not_applied_reason=None,
            rule=rule,
            handler=handler,
            facts=facts,
            outputs={
                name: OutputContract(rule_outputs[name].unit, rule_outputs[name].quantity)
                for name in step.outputs
                if name in rule_outputs
            },
        )

    def fact_input(
        self,
        step: StepDef,
        name: str,
        fact_type: str | None,
        unit: str | None,
        handler: HandlerSpec,
    ) -> CalcSnapshotItem | None:
        binding = step.facts[name]
        if fact_type != binding.fact_type:
            self.block(
                CalcBlockCode.RULE_CONTRACT_MISMATCH,
                f"вход «{name}»: правило ждёт факт {fact_type}, калькулятор даёт "
                f"{binding.fact_type}",
                step,
            )
            return None
        requirement = self.requirements.get((step.step_key, name))
        if requirement is None:
            return None  # причина уже записана при разборе области
        outcome = self.facts.get(requirement.fact_key)
        if outcome is None:
            outcome = Absence(CalcBlockCode.FACT_MISSING, "значения нет")
        if isinstance(outcome, Absence):
            self.block(
                outcome.code,
                f"«{requirement.fact_key}»: {outcome.message}",
                step,
                fact_key=requirement.fact_key,
            )
            return None
        if not isinstance(outcome.value, CalcNumberValue | CalcCountValue):
            self.block(
                CalcBlockCode.FACT_NOT_EXACT,
                f"«{requirement.fact_key}»: значение {outcome.value.kind} — не точное число",
                step,
                fact_key=requirement.fact_key,
            )
            return None
        fact_unit = numeric_unit(outcome)
        if not units_compatible(fact_unit, unit) or not units_compatible(
            fact_unit, handler.inputs.get(name)
        ):
            self.block(
                CalcBlockCode.UNIT_INCOMPATIBLE,
                f"«{requirement.fact_key}»: единица {fact_unit} не совместима со входом "
                f"«{name}» ({unit})",
                step,
                fact_key=requirement.fact_key,
            )
            return None
        self.used[outcome.fact_key] = outcome
        return outcome

    def step_input(self, step: StepDef, name: str, quantity: str | None, unit: str | None) -> None:
        link = step.steps[name]
        upstream = self.planned.get(link.step_key)
        if upstream is None and link.step_key in self.blocked:
            # Шаг-источник уже заблокирован со своей причиной — повторять её незачем.
            self.blocked.add(step.step_key)
            return
        if upstream is None:
            self.block(
                CalcBlockCode.RULE_CONTRACT_MISMATCH,
                f"вход «{name}» зависит от шага «{link.step_key}», который не спланирован",
                step,
            )
            return
        contract = upstream.outputs.get(link.output)
        if contract is None:
            self.block(
                CalcBlockCode.RULE_CONTRACT_MISMATCH,
                f"у шага «{link.step_key}» нет выхода «{link.output}»",
                step,
            )
            return
        if contract.quantity is not None and quantity is not None and contract.quantity != quantity:
            self.block(
                CalcBlockCode.RULE_CONTRACT_MISMATCH,
                f"вход «{name}» ждёт величину {quantity}, а шаг «{link.step_key}» даёт "
                f"{contract.quantity}",
                step,
            )
        if not units_compatible(contract.unit, unit):
            self.block(
                CalcBlockCode.UNIT_INCOMPATIBLE,
                f"вход «{name}» ждёт {unit or 'безразмерное'}, а шаг «{link.step_key}» даёт "
                f"{contract.unit or 'безразмерное'}",
                step,
            )


def plan(
    definition: CalculatorDef,
    scenario: CalcScenario,
    scope: CalcFactSubject,
    facts: Mapping[str, FactOutcome],
    rules: Mapping[str, RuleOutcome],
    handlers: Mapping[str, HandlerSpec],
) -> Plan:
    """План запуска или причины блокировки — все, какие удалось найти."""

    def blocked(reasons: list[CalcBlockingReason]) -> Plan:
        return Plan(definition, scenario, scope, (), (), (), (), tuple(reasons))

    problems = definition_problems(definition)
    if problems:
        return blocked([reason(CalcBlockCode.CALCULATOR_INVALID, item) for item in problems])
    if scenario not in definition.scenarios:
        return blocked(
            [
                reason(
                    CalcBlockCode.SCENARIO_NOT_SUPPORTED,
                    f"калькулятор не поддерживает сценарий {scenario.value}",
                )
            ]
        )
    scope_reasons = scope_problems(definition, scope)
    if scope_reasons:
        return blocked(scope_reasons)
    requirements, requirement_reasons = fact_requirements(definition, scope)

    planner = _Planner(definition, scenario, scope, facts, rules, handlers, requirements)
    planner.reasons.extend(requirement_reasons)
    order, _ = topological_order(definition.steps)
    for position, step_key in enumerate(order):
        step = definition.step(step_key)
        if step.assumption is not None:
            planner.plan_assumption(step, position)
        else:
            planner.plan_step(step, position)
    steps = tuple(planner.planned[key] for key in order if key in planner.planned)
    return Plan(
        definition=definition,
        scenario=scenario,
        scope=scope,
        steps=steps if not planner.reasons else (),
        bindings=tuple(planner.bindings),
        snapshot_items=tuple(sorted(planner.used.values(), key=lambda item: item.fact_key)),
        warnings=tuple(planner.warnings),
        reasons=tuple(planner.reasons),
    )
