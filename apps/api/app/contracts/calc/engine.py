"""Контракты расчётного ядра (ADR-0030, PROMPT 04).

Запуск расчёта неизменяем и самодостаточен: снимок фактов, точные версии правил с их
содержанием, версия калькулятора и отпечатки реализаций хранятся в самом запуске. Поэтому
изменение фактов или правил после запуска его не меняет, а повтор (replay) воспроизводит тот
же отпечаток результата.

Числа ходят точными десятичными строками без экспоненты (`ExactText`): ядро считает в Decimal
и не округляет молча, поэтому значение шага может быть длиннее девяти знаков после запятой.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.calc.enums import (
    CalcBlockCode,
    CalcCalculatorKind,
    CalcConfidence,
    CalcDiscipline,
    CalcDocumentStage,
    CalcEvidenceKind,
    CalcFactMethod,
    CalcInputSource,
    CalcResolutionState,
    CalcResultCategory,
    CalcReviewStatus,
    CalcRoundingMode,
    CalcRuleStatus,
    CalcRuleType,
    CalcRunStatus,
    CalcScenario,
    CalcSourceClass,
    CalcStepStatus,
    CalcTraceKind,
)
from app.contracts.calc.rules import CalcRuleContent
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcFactValue, DecimalText

CALCULATOR_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,4}$"
STEP_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"

ExactText = Annotated[
    str,
    Field(
        pattern=r"^-?\d{1,40}(\.\d{1,40})?$",
        description="Точное десятичное число строкой, без экспоненты и без скрытого округления.",
    ),
]
CalculatorId = Annotated[str, Field(pattern=CALCULATOR_ID_PATTERN, max_length=100)]
IdempotencyKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,100}$")]


class _Stored(BaseModel):
    """Часть запуска, которая хранится в JSONB и читается обратно без потерь."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# ------------------------------------------------------------------------------- запрос


class CalcRoundingPolicy(_Stored):
    """Явное округление: способ и шаг. Без него ядро не округляет ничего."""

    mode: CalcRoundingMode
    quantum: DecimalText
    """Шаг округления: «0.1», «1»."""


class CalcRunCreate(BaseModel):
    """Запуск калькулятора. Область — какой корпус, этаж, система считаются."""

    model_config = ConfigDict(extra="forbid")

    calculator_id: CalculatorId
    calculator_version: Annotated[int, Field(ge=1)]
    scenario: CalcScenario
    scope: CalcFactSubject
    idempotency_key: IdempotencyKey | None = None
    """Повтор запроса с тем же ключом возвращает уже созданный запуск, а не второй."""


# ------------------------------------------------------------------------ снимок фактов


class CalcEvidenceRef(_Stored):
    """Ссылка на свидетельство утверждения — достаточно, чтобы дойти до места в документе."""

    id: uuid.UUID
    kind: CalcEvidenceKind
    document_revision_id: uuid.UUID | None
    page_index: int | None
    sheet_id: uuid.UUID | None
    locator: str | None
    region_id: uuid.UUID | None
    region_sha256: str | None


class CalcSnapshotItem(_Stored):
    """Факт, как его увидело ядро: значение, носитель, способ выбора и происхождение."""

    fact_key: str
    fact_type: str
    subject: CalcFactSubject
    fact_id: uuid.UUID
    """Утверждение-носитель значения."""
    fact_version: int
    value: CalcFactValue
    """Каноническое значение: в единице типа факта."""
    stated_value: CalcFactValue
    """Как значение было заявлено: «3300 мм» до перевода в метры."""
    method: CalcFactMethod
    confidence: CalcConfidence
    review_status: CalcReviewStatus
    resolution_state: CalcResolutionState
    source_id: uuid.UUID
    source_class: CalcSourceClass
    claim_ids: list[uuid.UUID]
    """Утверждения, участвовавшие в выборе значения."""
    evidence: list[CalcEvidenceRef]
    calculation_eligible: bool
    """Всегда true: иное в снимок не попадает."""
    item_sha256: str


class CalcSnapshot(_Stored):
    version: str
    items: list[CalcSnapshotItem]
    sha256: str


# ----------------------------------------------------------------------- правила запуска


class CalcRuleBinding(_Stored):
    """Точная версия правила, на которой шаг считался, — вместе с содержанием."""

    step_key: str
    rule_key: str
    rule_version_id: uuid.UUID
    version: int
    status_at_run: CalcRuleStatus
    rule_type: CalcRuleType
    content_sha256: str
    implementation_key: str
    handler_semantics_sha256: str
    """Отпечаток семантики реализации: контракт и контрольные примеры обработчика."""
    content: CalcRuleContent


class CalcBlockingReason(_Stored):
    code: CalcBlockCode
    message: str
    step_key: str | None = None
    fact_key: str | None = None
    rule_key: str | None = None


class CalcRunFailure(_Stored):
    step_key: str | None
    error: str
    """Класс ошибки программы."""
    message: str


# ---------------------------------------------------------------------------------- шаги


class CalcConversion(_Stored):
    """Перевод единиц внутри ядра — всегда виден в цепочке расчёта."""

    from_value: ExactText
    from_unit: str
    to_value: ExactText
    to_unit: str


class CalcRoundingRecord(_Stored):
    target: str
    """Что округлено: выход шага или результат."""
    before: ExactText
    after: ExactText
    unit: str | None
    mode: CalcRoundingMode
    quantum: DecimalText
    reason: str


class CalcStepInput(_Stored):
    """Вход шага: откуда взят, какое значение, какой перевод единиц."""

    name: str
    source: CalcInputSource
    fact_key: str | None = None
    fact_id: uuid.UUID | None = None
    step_key: str | None = None
    output: str | None = None
    value: ExactText
    unit: str | None
    """Единица, в которой значение получил обработчик."""
    conversion: CalcConversion | None = None
    series: str | None = None
    """Набор, членом которого вход является (PROMPT 06): «heights»."""
    member: str | None = None
    """Код места члена набора: этаж «2..24», вид прибора «WC»."""


class CalcStepOutput(_Stored):
    name: str
    value: ExactText
    unit: str | None
    conversion: CalcConversion | None = None


class CalcAssumptionRecord(_Stored):
    """Использованное или не применённое допущение — никогда не скрытое."""

    step_key: str
    rule_key: str | None
    version: int | None
    applied: bool
    reason: str
    """Почему применено или нет: сценарий, применимость, утверждение."""
    impact: str | None
    """Влияние на результат словами — из правила."""
    base_value: ExactText
    value: ExactText
    unit: str | None
    delta: ExactText
    affected_results: list[str]


class CalcRuleRef(BaseModel):
    rule_key: str
    version: int
    rule_type: CalcRuleType
    content_sha256: str
    implementation_key: str


class CalcPrimitiveRef(BaseModel):
    """Вычислительный примитив шага: арифметика по фактам, не инженерное правило."""

    implementation_key: str
    title: str


class CalcStepRead(BaseModel):
    step_key: str
    position: int
    title: str
    status: CalcStepStatus
    rule: CalcRuleRef | None
    primitive: CalcPrimitiveRef | None = None
    """Шаг считается примитивом, а не правилом (PROMPT 06)."""
    inputs: list[CalcStepInput]
    parameters: list[CalcStepInput]
    outputs: list[CalcStepOutput]
    roundings: list[CalcRoundingRecord]
    explanation: str
    fingerprint: str
    """Отпечаток шага: калькулятор, реализация, версия правила, входы, сценарий, вверх по графу."""
    reused_from_run_id: uuid.UUID | None
    assumption: CalcAssumptionRecord | None


class CalcResultRead(BaseModel):
    """Инженерная величина запуска — ещё не позиция Расчётного паспорта."""

    run_id: uuid.UUID
    result_key: str
    title: str
    value: ExactText
    unit: str | None
    category: CalcResultCategory
    discipline: CalcDiscipline
    system_code: str | None
    scenario: CalcScenario
    step_key: str
    output: str
    rounding: CalcRoundingRecord | None


# --------------------------------------------------------------------------------- запуск


class CalcRunVersions(_Stored):
    """Версии всего, что определяет результат, кроме калькулятора и правил."""

    engine: str
    scenario_policy: str
    facts_policy: str
    fact_types: str
    snapshot: str


class CalcRunSummaryRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    calculator_id: str
    calculator_version: int
    calculator_title: str
    scenario: CalcScenario
    status: CalcRunStatus
    results_count: int
    blocking: str | None
    """Первая причина блокировки или ошибка — чтобы видеть её в списке."""
    result_sha256: str | None
    created_by: uuid.UUID | None
    created_at: datetime


class CalcRunRead(CalcRunSummaryRead):
    scope: CalcFactSubject
    effective_on: date
    """Дата, на которую выбирались действующие версии правил."""
    idempotency_key: str | None
    calculator_sha256: str
    versions: CalcRunVersions
    snapshot: CalcSnapshot
    rule_bindings: list[CalcRuleBinding]
    rule_bindings_sha256: str
    blocking_reasons: list[CalcBlockingReason]
    failure: CalcRunFailure | None
    assumptions: list[CalcAssumptionRecord]
    warnings: list[str]
    steps: list[CalcStepRead]
    results: list[CalcResultRead]


class CalcRunValidateRead(BaseModel):
    """Проверка запроса без запуска: что будет использовано и что мешает."""

    calculator_id: str
    calculator_version: int
    scenario: CalcScenario
    valid: bool
    blocking_reasons: list[CalcBlockingReason]
    warnings: list[str]
    snapshot: CalcSnapshot
    rule_bindings: list[CalcRuleBinding]


# ---------------------------------------------------------------------------- объяснение


class CalcTraceNode(BaseModel):
    """Узел цепочки объяснения: результат → шаг → правило, входы → факт → свидетельство."""

    kind: CalcTraceKind
    key: str
    title: str
    value: ExactText | None = None
    unit: str | None = None
    text: str
    """Детерминированное пояснение, собранное из структуры расчёта — без модели."""
    ref: str | None = None
    """Идентификатор объекта: утверждение, версия правила, свидетельство."""
    children: list[CalcTraceNode] = Field(default_factory=list)


class CalcResultTraceRead(BaseModel):
    run_id: uuid.UUID
    result_key: str
    text: str
    root: CalcTraceNode


# ------------------------------------------------------------------- сравнение и повтор


class CalcFactDiff(BaseModel):
    fact_key: str
    base_value: CalcFactValue | None
    other_value: CalcFactValue | None
    base_fact_id: uuid.UUID | None
    other_fact_id: uuid.UUID | None


class CalcRuleDiff(BaseModel):
    step_key: str
    rule_key: str
    base_version: int | None
    other_version: int | None
    base_content_sha256: str | None
    other_content_sha256: str | None


class CalcStepDiff(BaseModel):
    """Шаг, который пересчитывается: его отпечаток изменился, и названо почему."""

    step_key: str
    base_fingerprint: str | None
    other_fingerprint: str | None
    causes: list[str]


class CalcResultDiff(BaseModel):
    result_key: str
    base_value: ExactText | None
    other_value: ExactText | None
    unit: str | None


class CalcRunCompareRead(BaseModel):
    base_run_id: uuid.UUID
    other_run_id: uuid.UUID
    same_calculator: bool
    same_scenario: bool
    facts: list[CalcFactDiff]
    rules: list[CalcRuleDiff]
    invalidated_steps: list[CalcStepDiff]
    results: list[CalcResultDiff]


class CalcRunReplayRead(BaseModel):
    """Повтор исторического запуска из его снимка и его версий правил."""

    run_id: uuid.UUID
    reproducible: bool
    original_result_sha256: str | None
    replay_result_sha256: str | None
    problems: list[str]
    """Почему повтор невозможен: реализации или калькулятора этой версии больше нет."""


# ---------------------------------------------------------------------------- калькуляторы


class CalcCalculatorFactRead(BaseModel):
    step_key: str
    input: str
    fact_type: str
    subject_fields: list[str]
    member_field: str | None = None
    """Для набора — поле, которым различаются члены: «floor»."""


class CalcCalculatorStepRead(BaseModel):
    step_key: str
    title: str
    rule_key: str | None
    """Ключ правила; пусто — шаг-примитив."""
    primitive: str | None = None
    allowed_rule_types: list[CalcRuleType]
    depends_on: list[str]
    assumption: bool
    """Шаг тендерного допущения: применяется только в TENDER_SAFE."""


class CalcCalculatorResultRead(BaseModel):
    result_key: str
    title: str
    step_key: str
    output: str
    category: CalcResultCategory
    rounding: CalcRoundingPolicy | None


class CalcCalculatorRead(BaseModel):
    calculator_id: str
    version: int
    title: str
    kind: CalcCalculatorKind
    partial: bool = False
    """Частичный результат: заблокированный шаг не останавливает независимые."""
    discipline: CalcDiscipline
    systems: list[str]
    stage: CalcDocumentStage
    scenarios: list[CalcScenario]
    scope_fields: list[str]
    calculator_sha256: str
    facts: list[CalcCalculatorFactRead]
    rules: list[str]
    steps: list[CalcCalculatorStepRead]
    results: list[CalcCalculatorResultRead]
