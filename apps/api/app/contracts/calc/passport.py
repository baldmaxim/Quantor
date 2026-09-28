"""Ожидаемые количества и Расчётный паспорт системы (ADR-0030, PROMPT 06).

`ExpectedQuantity` — позиция паспорта: стабильный ключ в пределах паспорта, система, область,
категория, тип, технические характеристики, значение или диапазон, сценарий, происхождение и
ссылки на запуски расчёта и синтеза и на элементы графа. Это не позиция ВОР и не `Quantity`
обмера: сверка с ВОР Заказчика — PROMPT 09, здесь её нет.

Неизвестное не становится нулём и не прячется в итог: позиция BLOCKED без значения, частичная —
с подтверждаемой частью и списком неизвестных составляющих. Тендерный резерв — отдельной
составляющей: база, резерв и итог хранятся раздельно.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.calc.engine import CalcCalculatorRead, ExactText, IdempotencyKey
from app.contracts.calc.enums import (
    CalcCompleteness,
    CalcDiscipline,
    CalcElementProvenance,
    CalcPassportStatus,
    CalcQuantityCategory,
    CalcQuantityDerivation,
    CalcReadinessStatus,
    CalcRequirementLevel,
    CalcRuleReadiness,
    CalcRuleType,
    CalcRunStatus,
    CalcScenario,
    CalcSemanticsStatus,
    CalcSynthesisStatus,
    CalcUnresolvedKind,
)
from app.contracts.calc.subjects import CalcFactSubject, normalize_system_code
from app.contracts.calc.synthesis import CalcSynthesisTraceNode, CalcSynthesizerRead

QUANTITY_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,5}$"
MINIMUM_NOTICE: Final = "Это нижняя оценка, не проектное решение"


class _Stored(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CalcAmount(_Stored):
    """Значение или диапазон. Диапазон не превращается в середину."""

    value: ExactText | None = None
    low: ExactText | None = None
    high: ExactText | None = None

    @model_validator(mode="after")
    def _shape(self) -> CalcAmount:
        if self.value is not None and (self.low is not None or self.high is not None):
            raise ValueError("либо значение, либо диапазон")
        if (self.low is None) != (self.high is None):
            raise ValueError("у диапазона две границы")
        return self

    @property
    def known(self) -> bool:
        return self.value is not None or self.low is not None


class CalcQuantityComponent(_Stored):
    """Составляющая позиции: «198 м — вертикали», «подключения — не определено»."""

    key: str
    title: str
    amount: CalcAmount
    unit: str
    known: bool
    note: str | None = None


class CalcQuantityReserve(_Stored):
    """Тендерный резерв — отдельно от базы; только утверждённое допущение, только TENDER_SAFE."""

    rule_key: str
    version: int
    amount: CalcAmount
    unit: str
    reason: str
    impact: str | None


class CalcExpectedQuantityBody(_Stored):
    """Позиция паспорта без служебных идентификаторов — то, что хранится и хешируется."""

    quantity_key: Annotated[str, Field(pattern=QUANTITY_KEY_PATTERN, max_length=120)]
    system_code: str
    discipline: CalcDiscipline
    scope: CalcFactSubject
    scenario: CalcScenario
    category: CalcQuantityCategory
    item_type: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{1,40}$")]
    title: str
    function: str | None
    """Функция участка: вертикаль, этажное подключение, магистраль, итог."""
    attributes: dict[str, str]
    """Технические характеристики: тип элемента, способ определения, что не определено."""
    material: str | None
    size: str | None
    """Типоразмер, если известен из документа. Пусто — UNKNOWN: диаметр не угадывается."""
    amount: CalcAmount
    """Значение сценария. У PARTIAL — подтверждаемая часть, у BLOCKED — пусто."""
    unit: str
    base: CalcAmount | None = None
    """TENDER_SAFE: значение без резерва."""
    reserve: CalcQuantityReserve | None = None
    completeness: CalcCompleteness
    derivation: CalcQuantityDerivation
    aggregate: bool = False
    """Итог по составляющим: с другими позициями не суммируется."""
    calculation_run_id: uuid.UUID | None
    synthesis_run_id: uuid.UUID | None
    element_ids: list[str]
    result_keys: list[str]
    rule_refs: list[str]
    """Версии правил: «vk.supports.spacing@1»."""
    assumptions: list[str]
    warnings: list[str]
    blocked_by: list[str]
    """Ключи неопределённостей, без которых позиция не определена."""
    components: list[CalcQuantityComponent]
    notice: str | None
    explanation: str


class CalcExpectedQuantityRead(CalcExpectedQuantityBody):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: uuid.UUID
    passport_id: uuid.UUID


# --------------------------------------------------------------------------------- паспорт


class CalcInputCounts(_Stored):
    """«Для В1 нужно 22 параметра: найдено 17, выводится 3, нужен человек 2»."""

    total: int
    found_auto: int
    found_manual: int
    derivable: int
    needs_human: int
    not_inspected: int
    required_total: int
    required_satisfied: int


class CalcPassportFact(_Stored):
    fact_key: str
    title: str
    value: str
    source: str
    method: str


class CalcPassportMissing(_Stored):
    requirement_id: str
    title: str
    level: CalcRequirementLevel
    status: CalcReadinessStatus
    reason: str | None
    blocks: list[str]
    """Какие позиции паспорта без него не определяются."""
    not_blocks: list[str]


class CalcPassportConflict(_Stored):
    fact_key: str
    message: str


class CalcPassportResult(_Stored):
    key: str
    title: str
    layer: str
    """A — потребность, B — структура, D — параметры количеств, T — тендер, C — сверка."""
    amount: CalcAmount
    unit: str | None
    explanation: str


class CalcPassportCheck(_Stored):
    """Документальное значение и независимая проверка — раздельно, расхождение видно."""

    title: str
    document_value: str | None
    check_value: str | None
    discrepancy: str | None
    status: str


class CalcPassportElement(_Stored):
    element_id: str
    title: str
    provenance: CalcElementProvenance
    count: str
    """«4», «3–4 — не выбрано», «×23»."""


class CalcPassportIssue(_Stored):
    key: str
    title: str
    kind: CalcUnresolvedKind | None
    known: str
    needed: str
    structural: bool
    blocks: list[str]
    not_blocks: list[str]


class CalcPassportRule(_Stored):
    rule_key: str
    title: str
    layer: str
    status: CalcRuleReadiness
    version: int | None
    rule_type: CalcRuleType | None
    blocks: str
    gate: bool


class CalcPassportRun(_Stored):
    scenario: CalcScenario
    calculation_run_id: uuid.UUID | None
    calculation_status: CalcRunStatus | None
    synthesis_run_id: uuid.UUID | None
    synthesis_status: CalcSynthesisStatus | None


class CalcPassportBody(_Stored):
    system_title: str
    function: str
    semantics: CalcSemanticsStatus
    semantics_note: str
    highlights: list[str]
    """«Quantor рассчитал»: стояки, вертикаль, что определено."""
    problems: list[str]
    """Главные проблемы: чего не хватает для остального."""
    inputs: CalcInputCounts
    used_facts: list[CalcPassportFact]
    missing: list[CalcPassportMissing]
    conflicts: list[CalcPassportConflict]
    calculation: list[CalcPassportResult]
    checks: list[CalcPassportCheck]
    structure: list[CalcPassportElement]
    assumptions: list[str]
    unresolved: list[CalcPassportIssue]
    rules: list[CalcPassportRule]
    warnings: list[str]
    completeness: dict[str, int]
    """Позиций EXPECTED по полноте."""


class CalcPassportSummaryRead(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    project_id: uuid.UUID
    system_code: str
    system_title: str
    scope: CalcFactSubject
    status: CalcPassportStatus
    calculator_id: str
    calculator_version: int
    synthesizer_id: str
    synthesizer_version: int
    quantities_count: int
    highlights: list[str]
    problems: list[str]
    passport_sha256: str
    created_by: uuid.UUID | None
    created_at: datetime


class CalcPassportRead(CalcPassportSummaryRead):
    runs: list[CalcPassportRun]
    body: CalcPassportBody


VK_SYSTEM_CODES: Final = ("В1", "Т3", "Т4", "К1")


class CalcVkRunCreate(BaseModel):
    """Расчёт комплекта ВК: корпус (и секция), системы. Три сценария — всегда вместе."""

    model_config = ConfigDict(extra="forbid")

    building: Annotated[str, Field(min_length=1, max_length=64)]
    section: Annotated[str | None, Field(min_length=1, max_length=64)] = None
    systems: Annotated[list[str], Field(min_length=1, max_length=4)] = Field(
        default_factory=lambda: list(VK_SYSTEM_CODES)
    )
    idempotency_key: IdempotencyKey | None = None

    @field_validator("systems")
    @classmethod
    def _systems(cls, value: list[str]) -> list[str]:
        codes = [normalize_system_code(item) for item in value]
        unknown = [code for code in codes if code not in VK_SYSTEM_CODES]
        if unknown:
            raise ValueError("рабочие калькуляторы ВК есть для В1, Т3, Т4, К1")
        if len(set(codes)) != len(codes):
            raise ValueError("система указана дважды")
        return codes


class CalcVkBatchRead(BaseModel):
    batch_id: uuid.UUID
    created: bool
    passports: list[CalcPassportSummaryRead]


class CalcQuantityTraceRead(BaseModel):
    quantity_id: uuid.UUID
    quantity_key: str
    scenario: CalcScenario
    text: str
    root: CalcSynthesisTraceNode


# -------------------------------------------------------------------------- готовность


class CalcVkSystemReadinessRead(BaseModel):
    system_code: str
    title: str
    calculator_id: str
    calculator_version: int
    synthesizer_id: str
    function: str
    semantics: CalcSemanticsStatus
    semantics_note: str
    inputs: CalcInputCounts
    missing: list[CalcPassportMissing]
    rules: list[CalcPassportRule]


class CalcVkReadinessRead(BaseModel):
    building: str
    section: str | None
    systems: list[CalcVkSystemReadinessRead]


# ---------------------------------------------------------------- каталог калькуляторов ВК


class CalcRuleTermRead(BaseModel):
    name: str
    unit: str | None
    meaning: str
    quantity: str | None


class CalcVkRuleNeedRead(BaseModel):
    """Инженерное решение калькулятора: контракт реализации, что без него не определяется."""

    rule_key: str
    title: str
    systems: list[str]
    layer: str
    rule_types: list[CalcRuleType]
    implementation_key: str | None
    formula: str
    inputs: list[CalcRuleTermRead]
    parameters: list[CalcRuleTermRead]
    outputs: list[CalcRuleTermRead]
    used_in: str
    blocks: str
    affects: list[str]
    gate: bool
    example: str


class CalcVkCalculatorRead(BaseModel):
    system_code: str
    title: str
    function: str
    calculator: CalcCalculatorRead
    synthesizer: CalcSynthesizerRead
    rules: list[CalcVkRuleNeedRead]
