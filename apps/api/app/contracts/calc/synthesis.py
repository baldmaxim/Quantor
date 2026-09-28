"""Контракты синтеза структуры системы (ADR-0030, PROMPT 05).

Граф системы — расчётная гипотеза стадии П, а не РД и не знание об объекте: он не пишется в
реестр фактов. Каждый узел и каждая связь несут происхождение (наблюдено, рассчитано,
синтезировано, принято допущением) и отдельно — что известно о геометрии.

Кратность может быть диапазоном: «стояков 4–5» хранится как диапазон, без выбора середины или
границы, пока выбор не сделало утверждённое правило или инженер. Повторяемость (типовой этаж ×24)
— множитель группы, а количественный атрибут всегда знает, на экземпляр он или уже итог: так
двойное умножение старого портала невыразимо.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.calc.engine import (
    CalcBlockingReason,
    CalcResultTraceRead,
    CalcRuleBinding,
    CalcRunFailure,
    CalcRunVersions,
    CalcSnapshot,
    ExactText,
    IdempotencyKey,
)
from app.contracts.calc.enums import (
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcElementProvenance,
    CalcGeometryState,
    CalcQuantityBasis,
    CalcRuleType,
    CalcScenario,
    CalcSelectionSource,
    CalcSynthesisRuleRole,
    CalcSynthesisStatus,
    CalcSynthesisTraceKind,
    CalcUnresolvedKind,
)
from app.contracts.calc.subjects import CalcFactSubject

ELEMENT_ID_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"
SEMANTIC_TYPE_PATTERN: Final = r"^[A-Z][A-Z0-9_]{1,40}$"

ElementId = Annotated[str, Field(pattern=ELEMENT_ID_PATTERN)]
SemanticType = Annotated[str, Field(pattern=SEMANTIC_TYPE_PATTERN)]
"""Смысловой тип — строка по шаблону, а не закрытый список: типы добавляются с синтезаторами."""


class _Stored(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# -------------------------------------------------------------------------- ссылки и выбор


class CalcSynthesisRuleRef(_Stored):
    rule_key: str
    version: int
    rule_type: CalcRuleType
    content_sha256: str
    implementation_key: str
    role: CalcSynthesisRuleRole


class CalcElementSource(_Stored):
    """Основание элемента: результат расчёта, факт объекта или решение инженера."""

    kind: Literal["CALCULATION_RESULT", "FACT", "HUMAN_DECISION"]
    key: str
    """Ключ результата, ключ факта или идентификатор решения."""
    run_id: uuid.UUID | None = None
    """Запуск расчёта — для результата."""
    fact_id: uuid.UUID | None = None
    value: ExactText | None = None
    unit: str | None = None


class CalcSelection(_Stored):
    source: CalcSelectionSource
    rule: CalcSynthesisRuleRef | None = None
    decision_id: uuid.UUID | None = None
    explanation: str

    @model_validator(mode="after")
    def _reference(self) -> CalcSelection:
        if self.source is CalcSelectionSource.RULE and self.rule is None:
            raise ValueError("выбор по правилу ссылается на версию правила")
        if self.source is CalcSelectionSource.HUMAN_DECISION and self.decision_id is None:
            raise ValueError("выбор инженера ссылается на решение")
        return self


class CalcCardinality(_Stored):
    """Сколько экземпляров представляет элемент — точно или диапазоном."""

    min: Annotated[int, Field(ge=0)]
    max: Annotated[int, Field(ge=0)]
    selected: Annotated[int | None, Field(ge=0)] = None
    """Выбранная кратность. Пусто — выбор не сделан, диапазон остаётся диапазоном."""
    selection: CalcSelection | None = None

    @model_validator(mode="after")
    def _consistent(self) -> CalcCardinality:
        if self.min > self.max:
            raise ValueError("нижняя граница кратности больше верхней")
        if self.selected is not None and not self.min <= self.selected <= self.max:
            raise ValueError("выбранная кратность вне диапазона")
        if (self.selected is None) != (self.selection is None):
            raise ValueError("выбранная кратность всегда с основанием выбора")
        return self

    @property
    def exact(self) -> bool:
        """Кратность известна: границы совпали или выбор сделан по основанию."""
        return self.selected is not None or self.min == self.max


class CalcScenarioEstimate(_Stored):
    """Оценка сценария для кратности — например, нижняя граница в MINIMUM."""

    value: Annotated[int, Field(ge=0)]
    meaning: Literal["LOWER_BOUND"]
    note: str
    """«Нижняя оценка, а не проектное решение»."""


class CalcQuantityAttr(_Stored):
    """Количественный атрибут: значение или диапазон и его смысл — на экземпляр или итог."""

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
    value: ExactText | None = None
    low: ExactText | None = None
    high: ExactText | None = None
    unit: str | None
    basis: CalcQuantityBasis
    note: str | None = None

    @model_validator(mode="after")
    def _value_or_range(self) -> CalcQuantityAttr:
        if self.value is None and self.low is None and self.high is None:
            raise ValueError("у атрибута нет ни значения, ни диапазона")
        if self.value is not None and (self.low is not None or self.high is not None):
            raise ValueError("атрибут — либо значение, либо диапазон")
        return self


class CalcGeometry(_Stored):
    """Что известно о геометрии. Точные координаты — только из источника."""

    state: CalcGeometryState = CalcGeometryState.NONE
    anchor: Annotated[str | None, Field(max_length=200)] = None
    """Элемент или зона привязки: «шахта Ш-1», «коридор секции 1»."""
    bbox: Annotated[list[float] | None, Field(min_length=4, max_length=4)] = None
    """Нормализованная рамка источника [x0, y0, x1, y1] — только наблюдённая."""
    source_fact_key: str | None = None
    rule_key: str | None = None
    length: CalcQuantityAttr | None = None
    """Длина или диапазон длины трассы — только по утверждённому правилу."""

    @model_validator(mode="after")
    def _honest(self) -> CalcGeometry:
        if self.bbox is not None:
            if self.state is not CalcGeometryState.OBSERVED or self.source_fact_key is None:
                raise ValueError("координаты — только наблюдённые, со ссылкой на источник")
            if not all(0 <= item <= 1 for item in self.bbox):
                raise ValueError("рамка нормализована к 0…1")
        if self.state is CalcGeometryState.OBSERVED and self.source_fact_key is None:
            raise ValueError("наблюдённая геометрия ссылается на факт-источник")
        if self.state is CalcGeometryState.ANCHOR_ONLY and self.anchor is None:
            raise ValueError("привязка без элемента привязки")
        if self.state is CalcGeometryState.ESTIMATED and self.rule_key is None:
            raise ValueError("оценённая геометрия — только по утверждённому правилу")
        if self.length is not None and self.state not in (
            CalcGeometryState.RANGE,
            CalcGeometryState.ESTIMATED,
            CalcGeometryState.OBSERVED,
        ):
            raise ValueError("длина трассы без состояния геометрии, которое её допускает")
        if self.state is CalcGeometryState.NONE and (self.anchor or self.length):
            raise ValueError("состояние NONE — без геометрии")
        return self


# ------------------------------------------------------------------------------ граф


class _Element(_Stored):
    id: ElementId
    semantic_type: SemanticType
    title: Annotated[str, Field(min_length=1, max_length=200)]
    provenance: CalcElementProvenance
    sources: list[CalcElementSource] = Field(default_factory=list)
    rules: list[CalcSynthesisRuleRef] = Field(default_factory=list)
    attributes: list[CalcQuantityAttr] = Field(default_factory=list)
    geometry: CalcGeometry = Field(default_factory=CalcGeometry)
    multipliers: list[ElementId] = Field(default_factory=list)
    """Узлы, число экземпляров которых умножает кратность элемента: «на стояк и на этаж»."""
    support: str
    """Почему элемент нужен — словами, из основания: не «обычно так делают»."""


class CalcSystemNode(_Element):
    scope: CalcFactSubject
    cardinality: CalcCardinality
    multiplicity: Annotated[int, Field(ge=1)] = 1
    """Повторяемость группы: типовой этаж ×24 — один узел, а не 24 копии."""
    estimate: CalcScenarioEstimate | None = None


class CalcSystemEdge(_Element):
    source_node: ElementId
    target_node: ElementId


class CalcUnresolvedItem(_Stored):
    """Что Quantor пока не знает — и что нужно, чтобы узнать."""

    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]{0,79}$")]
    kind: CalcUnresolvedKind
    title: str
    element_id: ElementId | None = None
    known: str
    """Что известно: «4–5 стояков»."""
    needed: str
    """Что нужно: утверждённое правило выбора, решение инженера, документ."""
    structural: bool
    """Структурное решение открыто — запуск PARTIAL. Неизвестная трасса — не структурное."""


class CalcSynthesisAssumption(_Stored):
    element_ids: list[ElementId]
    rule: CalcSynthesisRuleRef
    reason: str
    impact: str | None
    notice: str
    value: ExactText
    unit: str | None


class CalcSystemGraph(_Stored):
    graph_type: str
    discipline: CalcDiscipline
    system_code: str | None
    scope: CalcFactSubject
    scenario: CalcScenario
    synthesizer_id: str
    synthesizer_version: int
    nodes: list[CalcSystemNode]
    edges: list[CalcSystemEdge]
    unresolved: list[CalcUnresolvedItem]
    assumptions: list[CalcSynthesisAssumption]
    warnings: list[str]


class CalcVariantSelection(_Stored):
    node_id: ElementId
    count: Annotated[int, Field(ge=0)]


class CalcSynthesisVariant(_Stored):
    """Допустимый вариант схемы. Без вероятностей: статистической модели нет."""

    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    title: str
    selections: list[CalcVariantSelection]
    reasons: list[str]
    """Почему вариант допустим: в пределах расчёта, не противоречит ограничениям."""
    open_questions: list[str]
    """Что остаётся нерешённым и в этом варианте."""


# ------------------------------------------------------------------------ решения инженера


class CalcSynthesisDecisionCreate(BaseModel):
    """Решение инженера по нерешённой кратности. Вход следующего запуска, не факт объекта."""

    model_config = ConfigDict(extra="forbid")

    node_id: ElementId
    selected_count: Annotated[int, Field(ge=0)]
    variant_key: str | None = None
    comment: Annotated[str, Field(min_length=10, max_length=2000)]


class CalcSynthesisDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    synthesis_run_id: uuid.UUID
    node_id: str
    selected_count: int
    variant_key: str | None
    alternatives: list[int]
    """Из чего выбирали: допустимые значения кратности."""
    comment: str
    decided_by: uuid.UUID | None
    created_at: datetime


# ---------------------------------------------------------------------------- запуск синтеза


class CalcSynthesisRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_run_id: uuid.UUID
    synthesizer_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,4}$")]
    synthesizer_version: Annotated[int, Field(ge=1)]
    decision_ids: Annotated[list[uuid.UUID], Field(max_length=20)] = Field(default_factory=list)
    """Решения инженера, которые новый запуск принимает как вход."""
    idempotency_key: IdempotencyKey | None = None


class CalcSynthesisRunSummaryRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    calculation_run_id: uuid.UUID
    synthesizer_id: str
    synthesizer_version: int
    synthesizer_title: str
    scenario: CalcScenario
    status: CalcSynthesisStatus
    nodes_count: int
    unresolved_count: int
    blocking: str | None
    graph_sha256: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class CalcSynthesisRunRead(CalcSynthesisRunSummaryRead):
    """Запуск без графа: граф — отдельной операцией."""

    scope: CalcFactSubject
    idempotency_key: str | None
    synthesizer_sha256: str
    implementation_sha256: str
    """Отпечаток реализации синтезатора: определение и контрольные примеры."""
    versions: CalcRunVersions
    calculation_result_sha256: str
    snapshot: CalcSnapshot
    rule_bindings: list[CalcRuleBinding]
    rule_bindings_sha256: str
    applied_decisions: list[CalcSynthesisDecisionRead]
    blocking_reasons: list[CalcBlockingReason]
    failure: CalcRunFailure | None
    unresolved: list[CalcUnresolvedItem]
    variants: list[CalcSynthesisVariant]
    assumptions: list[CalcSynthesisAssumption]
    warnings: list[str]
    decisions: list[CalcSynthesisDecisionRead]
    """Решения инженера, принятые по вариантам этого запуска (для следующих запусков)."""


class CalcSynthesisValidateRead(BaseModel):
    synthesizer_id: str
    synthesizer_version: int
    scenario: CalcScenario | None
    valid: bool
    blocking_reasons: list[CalcBlockingReason]
    warnings: list[str]


class CalcSynthesisTraceNode(BaseModel):
    kind: CalcSynthesisTraceKind
    key: str
    title: str
    text: str
    ref: str | None = None
    calculation: CalcResultTraceRead | None = None
    """Для результата расчёта — цепочка ядра: шаг → версия правила → факт → свидетельство."""
    children: list[CalcSynthesisTraceNode] = Field(default_factory=list)


class CalcSynthesisTraceRead(BaseModel):
    run_id: uuid.UUID
    element_id: str
    provenance: CalcElementProvenance
    text: str
    root: CalcSynthesisTraceNode


class CalcSynthesisReplayRead(BaseModel):
    run_id: uuid.UUID
    reproducible: bool
    original_graph_sha256: str | None
    replay_graph_sha256: str | None
    problems: list[str]


class CalcElementDiff(BaseModel):
    element_id: str
    change: Literal["ADDED", "REMOVED", "CHANGED"]
    fields: list[str]


class CalcSynthesisCompareRead(BaseModel):
    base_run_id: uuid.UUID
    other_run_id: uuid.UUID
    same_synthesizer: bool
    same_calculation: bool
    nodes: list[CalcElementDiff]
    edges: list[CalcElementDiff]
    unresolved_added: list[str]
    unresolved_removed: list[str]


class CalcSynthesizerRead(BaseModel):
    synthesizer_id: str
    version: int
    title: str
    kind: CalcCalculatorKind
    discipline: CalcDiscipline
    systems: list[str]
    stage: CalcDocumentStage
    scenarios: list[CalcScenario]
    graph_type: str
    calculator_id: str
    calculator_version: int
    results: list[str]
    facts: list[str]
    rules: list[str]
    synthesizer_sha256: str
    implementation_sha256: str
