"""Определения синтезаторов и общий порядок синтеза. Чистые функции без базы.

Синтезатор — код, версионируемый с приложением: какой калькулятор и какие его результаты
нужны, какие дополнительные факты для структуры, какие правила и в какой роли, тип графа,
детерминированный алгоритм и контрольные примеры. Языка построения систем в базе нет.

Отпечаток реализации — определение и отпечатки графов контрольных примеров: изменил алгоритм
под той же версией — не сходятся примеры, изменил и примеры — меняется отпечаток, и повтор
старых запусков честно отказывает.

Порядок: сценарий → результаты расчёта → факты (тот же строгий допуск, что у ядра) → правила
→ алгоритм → проверка графа → статус. Отсутствие результата или обязательного факта —
BLOCKED; открытое структурное решение — PARTIAL; ошибка алгоритма — FAILED.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.contracts.calc.engine import (
    CalcBlockingReason,
    CalcResultRead,
    CalcRuleBinding,
    CalcSnapshotItem,
)
from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcScenario,
    CalcSynthesisRuleRole,
    CalcSynthesisStatus,
)
from app.contracts.calc.fact_types import check_subject, fact_type_def
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcSynthesisVariant, CalcSystemGraph
from app.services.calc.engine.handlers import HandlerSpec
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.plan_types import Absence, FactOutcome, RuleOutcome
from app.services.calc.synthesis.graph import graph_problems, graph_sha256
from app.services.calc.synthesis.rules import (
    AppliedRule,
    RuleUse,
    SynthesisRuleError,
    SynthesisRuleSpec,
    use_rule,
)


@dataclass(frozen=True, slots=True)
class SynthesisFactSpec:
    """Дополнительный факт для структуры: тип и поля области, задающие место."""

    fact_type: str
    subject_fields: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True, slots=True)
class DecisionInput:
    """Решение инженера, переданное новому запуску."""

    id: uuid.UUID
    node_id: str
    selected_count: int
    comment: str


@dataclass(frozen=True)
class SynthesisContext:
    """Всё, что видит алгоритм синтезатора. Базы, запроса, реестров — нет."""

    definition: SynthesizerDef
    scenario: CalcScenario
    scope: CalcFactSubject
    calculation_run_id: uuid.UUID
    results: Mapping[str, CalcResultRead]
    facts: Mapping[str, CalcSnapshotItem]
    rules: Mapping[str, RuleUse]
    decisions: tuple[DecisionInput, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    graph: CalcSystemGraph
    variants: tuple[CalcSynthesisVariant, ...]
    applied_decisions: tuple[uuid.UUID, ...] = ()


BuildFn = Callable[[SynthesisContext], BuildResult]
GoldenFn = Callable[[], Mapping[str, SynthesisContext]]


@dataclass(frozen=True)
class SynthesizerDef:
    synthesizer_id: str
    version: int
    title: str
    kind: CalcCalculatorKind
    discipline: CalcDiscipline
    systems: tuple[str, ...]
    stage: CalcDocumentStage
    scenarios: frozenset[CalcScenario]
    graph_type: str
    calculator_id: str
    calculator_version: int
    results: tuple[str, ...]
    facts: Mapping[str, SynthesisFactSpec]
    rules: Mapping[str, SynthesisRuleSpec]
    build: BuildFn = field(repr=False, compare=False)
    golden: tuple[tuple[str, str], ...] = ()
    """Контрольные примеры: имя → ожидаемый отпечаток графа."""
    golden_contexts: GoldenFn | None = field(default=None, repr=False, compare=False)

    def canonical(self) -> dict[str, object]:
        return {
            "synthesizer_id": self.synthesizer_id,
            "version": self.version,
            "kind": self.kind.value,
            "discipline": self.discipline.value,
            "systems": list(self.systems),
            "stage": self.stage.value,
            "scenarios": sorted(item.value for item in self.scenarios),
            "graph_type": self.graph_type,
            "calculator": [self.calculator_id, self.calculator_version],
            "results": list(self.results),
            "facts": {
                name: [spec.fact_type, list(spec.subject_fields), spec.required]
                for name, spec in sorted(self.facts.items())
            },
            "rules": {
                name: {
                    "role": spec.role.value,
                    "rule_key": spec.rule_key,
                    "allowed_types": sorted(item.value for item in spec.allowed_types),
                    "outputs": list(spec.outputs),
                    "inputs": {k: v.result_key for k, v in sorted(spec.inputs.items())},
                }
                for name, spec in sorted(self.rules.items())
            },
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.canonical())

    @property
    def implementation_sha256(self) -> str:
        return canonical_sha256({"definition": self.canonical(), "golden": list(self.golden)})


def check_golden(definition: SynthesizerDef) -> list[str]:
    """Контрольные примеры сходятся — реализация соответствует своему отпечатку."""
    if definition.golden_contexts is None:
        return [f"{definition.synthesizer_id}: нет контрольных примеров"]
    contexts = definition.golden_contexts()
    problems: list[str] = []
    for name, expected in definition.golden:
        result = definition.build(contexts[name])
        actual = graph_sha256(result.graph)
        if actual != expected:
            problems.append(f"{definition.synthesizer_id}: пример «{name}» даёт {actual}")
    return problems


def build_registry(
    synthesizers: Iterable[SynthesizerDef],
) -> MappingProxyType[tuple[str, int], SynthesizerDef]:
    registry: dict[tuple[str, int], SynthesizerDef] = {}
    for item in synthesizers:
        key = (item.synthesizer_id, item.version)
        if key in registry:
            raise ValueError(f"синтезатор {key} объявлен дважды")
        if not item.golden:
            raise ValueError(f"синтезатор {key} без контрольных примеров")
        for spec in item.facts.values():
            if fact_type_def(spec.fact_type) is None:
                raise ValueError(f"синтезатор {key}: неизвестный тип факта {spec.fact_type}")
        registry[key] = item
    return MappingProxyType(registry)


# --------------------------------------------------------------------------------- порядок


@dataclass(frozen=True, slots=True)
class FactKey:
    name: str
    fact_key: str


def fact_keys(
    definition: SynthesizerDef, scope: CalcFactSubject
) -> tuple[list[FactKey], list[CalcBlockingReason]]:
    """Ключи дополнительных фактов для области запуска."""
    found: list[FactKey] = []
    reasons: list[CalcBlockingReason] = []
    for name, spec in definition.facts.items():
        definition_of_fact = fact_type_def(spec.fact_type)
        values = {item: getattr(scope, item) for item in spec.subject_fields}
        try:
            subject = CalcFactSubject.model_validate(values)
        except ValueError as error:
            reasons.append(CalcBlockingReason(code=CalcBlockCode.SCOPE_INVALID, message=str(error)))
            continue
        problem = None if definition_of_fact is None else check_subject(definition_of_fact, subject)
        if problem is not None:
            reasons.append(
                CalcBlockingReason(
                    code=CalcBlockCode.SCOPE_INVALID, message=f"факт «{spec.fact_type}»: {problem}"
                )
            )
            continue
        found.append(FactKey(name, f"{spec.fact_type}@{subject.key()}"))
    return found, reasons


@dataclass(frozen=True)
class SynthesisOutcome:
    status: CalcSynthesisStatus
    graph: CalcSystemGraph | None
    graph_sha256: str | None
    variants: tuple[CalcSynthesisVariant, ...]
    bindings: tuple[CalcRuleBinding, ...]
    snapshot_items: tuple[CalcSnapshotItem, ...]
    reasons: tuple[CalcBlockingReason, ...]
    warnings: tuple[str, ...]
    applied_decisions: tuple[uuid.UUID, ...]
    failure: tuple[str, str] | None = None
    """Класс ошибки и текст — для FAILED."""


def _roles_for(scenario: CalcScenario) -> frozenset[CalcSynthesisRuleRole]:
    """Какие правила синтеза применимы в сценарии.

    MINIMUM — только неизбежная структура: правило выбора кратности не применяется, диапазон
    даёт нижнюю оценку. Тендерное допущение — только TENDER_SAFE.
    """
    roles = {CalcSynthesisRuleRole.TOPOLOGY}
    if scenario is not CalcScenario.MINIMUM:
        roles.add(CalcSynthesisRuleRole.SELECTION)
    if scenario is CalcScenario.TENDER_SAFE:
        roles.add(CalcSynthesisRuleRole.ASSUMPTION)
    return frozenset(roles)


def synthesize(
    definition: SynthesizerDef,
    *,
    scenario: CalcScenario,
    scope: CalcFactSubject,
    calculation_run_id: uuid.UUID,
    results: Mapping[str, CalcResultRead],
    facts: Mapping[str, FactOutcome],
    rules: Mapping[str, RuleOutcome],
    handlers: Mapping[str, HandlerSpec],
    decisions: tuple[DecisionInput, ...] = (),
) -> SynthesisOutcome:
    """Синтез из подготовленных входов. `facts` — исходы по ключам фактов области."""
    reasons: list[CalcBlockingReason] = []
    warnings: list[str] = []

    def outcome(
        status: CalcSynthesisStatus, failure: tuple[str, str] | None = None
    ) -> SynthesisOutcome:
        """Запуск без графа: блокировка или ошибка алгоритма."""
        return SynthesisOutcome(
            status=status,
            graph=None,
            graph_sha256=None,
            variants=(),
            bindings=(),
            snapshot_items=(),
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            applied_decisions=(),
            failure=failure,
        )

    if scenario not in definition.scenarios:
        reasons.append(
            CalcBlockingReason(
                code=CalcBlockCode.SCENARIO_NOT_SUPPORTED,
                message=f"синтезатор не поддерживает сценарий {scenario.value}",
            )
        )
        return outcome(CalcSynthesisStatus.BLOCKED)
    for key in definition.results:
        if key not in results:
            reasons.append(
                CalcBlockingReason(
                    code=CalcBlockCode.CALCULATION_RESULT_MISSING,
                    message=f"в запуске расчёта нет результата «{key}»",
                )
            )

    keys, key_reasons = fact_keys(definition, scope)
    reasons.extend(key_reasons)
    admitted: dict[str, CalcSnapshotItem] = {}
    for item in keys:
        found = facts.get(item.fact_key)
        if isinstance(found, CalcSnapshotItem):
            admitted[item.name] = found
            continue
        absence = found if isinstance(found, Absence) else None
        if definition.facts[item.name].required:
            reasons.append(
                CalcBlockingReason(
                    code=absence.code if absence else CalcBlockCode.FACT_MISSING,
                    message=f"«{item.fact_key}»: {absence.message if absence else 'значения нет'}",
                    fact_key=item.fact_key,
                )
            )

    uses: dict[str, RuleUse] = {}
    applicable = _roles_for(scenario)
    for name, spec in definition.rules.items():
        if spec.role not in applicable:
            continue
        used = use_rule(
            name,
            spec,
            rules.get(spec.rule_key),
            scenario=scenario,
            scope=scope,
            stage=definition.stage,
            results=results,
            handlers=handlers,
        )
        if isinstance(used, CalcBlockingReason):
            reasons.append(used)
        else:
            uses[name] = used
    if reasons:
        return outcome(CalcSynthesisStatus.BLOCKED)

    context = SynthesisContext(
        definition=definition,
        scenario=scenario,
        scope=scope,
        calculation_run_id=calculation_run_id,
        results=MappingProxyType(dict(results)),
        facts=MappingProxyType(admitted),
        rules=MappingProxyType(uses),
        decisions=decisions,
    )
    snapshot = tuple(sorted(admitted.values(), key=lambda item: item.fact_key))
    bindings = tuple(
        used.binding(name) for name, used in sorted(uses.items()) if isinstance(used, AppliedRule)
    )
    try:
        built = definition.build(context)
    except SynthesisRuleError as error:
        return outcome(CalcSynthesisStatus.FAILED, failure=("SynthesisRuleError", str(error)))
    except Exception as error:
        return outcome(CalcSynthesisStatus.FAILED, failure=(type(error).__name__, str(error)))
    problems = graph_problems(built.graph)
    if problems:
        return outcome(CalcSynthesisStatus.FAILED, failure=("GraphInvalid", "; ".join(problems)))
    structural = any(item.structural for item in built.graph.unresolved)
    return SynthesisOutcome(
        status=CalcSynthesisStatus.PARTIAL if structural else CalcSynthesisStatus.SUCCEEDED,
        graph=built.graph,
        graph_sha256=graph_sha256(built.graph),
        variants=built.variants,
        bindings=bindings,
        snapshot_items=snapshot,
        reasons=(),
        warnings=tuple(built.graph.warnings),
        applied_decisions=built.applied_decisions,
    )
