"""Контракты реестра правил (ADR-0030, PROMPT 03).

Реестр правил хранит не факты объекта, а утверждённые способы превратить факты в расчётные
величины. Правило — стабильный ключ (`vk.riser.vertical_length`) и неизменяемые версии: после
утверждения содержание версии не меняется, любое изменение — новая версия. Так запуск расчёта
(PROMPT 04) воспроизводится по ключу, номеру версии и хешу содержимого.

Формула хранится текстом для человека. Исполняет правило только детерминированная реализация,
найденная по `implementation_key` (PROMPT 04). Кода, выражений и `eval` в реестре нет: лишние
поля содержимого отклоняются, а размерности проверяются по объявленным членам, без вычисления.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcDocumentStage,
    CalcHazardOutcome,
    CalcLegacyAction,
    CalcLegacyCatalog,
    CalcLegacyClass,
    CalcLegacyHazard,
    CalcRuleInputKind,
    CalcRuleStatus,
    CalcRuleType,
)
from app.contracts.calc.subjects import normalize_system_code
from app.contracts.calc.values import DecimalText

RULE_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,5}$"
IMPLEMENTATION_KEY_PATTERN: Final = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*\.v[1-9][0-9]*$"
LEGACY_ID_PATTERN: Final = r"^LEG-[A-Z0-9]+-\d{3}$"

TENDER_NOTICE: Final = "Это не норматив и не факт документации. Это тендерное допущение."
LEGACY_NOTICE: Final = "НЕ ПРОВЕРЕНО / НЕ ИСПОЛЬЗУЕТСЯ В РАСЧЁТЕ"

RuleKey = Annotated[str, Field(pattern=RULE_KEY_PATTERN, max_length=120)]
"""Стабильный ключ правила: не название, а место в библиотеке — `vk.riser.vertical_length`."""
LocalName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
QuantityKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$", max_length=80)
]
ImplementationKey = Annotated[str, Field(pattern=IMPLEMENTATION_KEY_PATTERN, max_length=120)]
LegacyId = Annotated[str, Field(pattern=LEGACY_ID_PATTERN)]
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
LongText = Annotated[str, Field(min_length=1, max_length=2000)]


class _Content(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------- входы, параметры, выходы


class CalcRuleInput(_Content):
    """Что правилу нужно на входе. Значение приходит из снимка фактов или от другого шага."""

    name: LocalName
    kind: CalcRuleInputKind
    fact_type: Annotated[str | None, Field(default=None, max_length=64)] = None
    """Тип факта реестра фактов — для входа FACT."""
    quantity: QuantityKey | None = None
    """Величина другого шага — для входа QUANTITY."""
    unit: Annotated[str | None, Field(default=None, max_length=16)] = None
    """Единица из каталога; пусто — безразмерный вход."""
    required: bool = True
    description: LongText

    @model_validator(mode="after")
    def _source_of_value(self) -> CalcRuleInput:
        if self.kind is CalcRuleInputKind.FACT and (self.fact_type is None or self.quantity):
            raise ValueError("вход FACT указывает тип факта и не указывает величину")
        if self.kind is CalcRuleInputKind.QUANTITY and (self.quantity is None or self.fact_type):
            raise ValueError("вход QUANTITY указывает величину и не указывает тип факта")
        return self


class CalcRuleParameter(_Content):
    """Константа версии правила. Меняется только новой версией."""

    name: LocalName
    value: DecimalText
    unit: Annotated[str | None, Field(default=None, max_length=16)] = None
    description: LongText
    """Что это за число и откуда оно."""


class CalcRuleOutput(_Content):
    name: LocalName
    quantity: QuantityKey
    """Какая величина получается: `pipe.length`, `riser.count`."""
    unit: Annotated[str | None, Field(default=None, max_length=16)] = None
    description: LongText


class CalcDimensionFactor(_Content):
    name: LocalName
    """Вход или параметр правила."""
    exponent: Annotated[int, Field(ge=-3, le=3)] = 1

    @field_validator("exponent")
    @classmethod
    def _not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("степень множителя не может быть нулевой")
        return value


class CalcDimensionTerm(_Content):
    """Член суммы: произведение входов и параметров в степенях."""

    factors: Annotated[list[CalcDimensionFactor], Field(min_length=1, max_length=8)]


class CalcRuleDimensionCheck(_Content):
    """Проверка размерности выхода: каждый член суммы должен иметь размерность выхода.

    Это не формула и не исполняется: только объявленная структура, по которой реестр ловит
    «метры × давление = метры» до утверждения.
    """

    output: LocalName
    terms: Annotated[list[CalcDimensionTerm], Field(min_length=1, max_length=8)]


class CalcRuleApplicability(_Content):
    systems: Annotated[list[str], Field(min_length=1, max_length=20)]
    """Системы, к которым правило применимо: «В1», «К1»."""
    stages: Annotated[list[CalcDocumentStage], Field(min_length=1, max_length=3)]
    scope: LongText
    """Область применения словами: тип здания, этажность, схема."""
    limitations: Annotated[list[LongText], Field(max_length=20)] = Field(default_factory=list)
    manufacturer: ShortText | None = None
    """Производитель — для правила производителя; к другим оно не применяется."""
    product_line: ShortText | None = None

    @field_validator("systems")
    @classmethod
    def _systems(cls, value: list[str]) -> list[str]:
        codes = [normalize_system_code(item) for item in value]
        if len(set(codes)) != len(codes):
            raise ValueError("система указана дважды")
        return codes


# ------------------------------------------------------------------------------- источники


class CalcNormativeSource(_Content):
    """Нормативный документ: без обозначения, редакции, пункта и даты нормы нет."""

    kind: Literal["NORMATIVE_DOCUMENT"] = "NORMATIVE_DOCUMENT"
    document_title: ShortText
    designation: ShortText
    """Обозначение: «СП 30.13330.2020»."""
    edition: ShortText
    """Редакция или изменение."""
    clause: ShortText
    """Пункт, раздел, таблица."""
    page: ShortText | None = None
    edition_date: date
    """Дата редакции или введения в действие."""
    artifact: ShortText | None = None
    """Локальный файл или артефакт, если документ есть в проекте."""


class CalcManufacturerSource(_Content):
    kind: Literal["MANUFACTURER_DOCUMENT"] = "MANUFACTURER_DOCUMENT"
    manufacturer: ShortText
    product_line: ShortText
    document_title: ShortText
    document_version: ShortText
    document_date: date | None = None
    location: ShortText
    """Таблица, страница, раздел документа."""
    scope: LongText


class CalcEngineeringSource(_Content):
    kind: Literal["ENGINEERING_METHOD"] = "ENGINEERING_METHOD"
    title: ShortText
    author: ShortText
    """Автор или организация."""
    reference: ShortText
    """Где методика опубликована или хранится."""
    summary: LongText


class CalcDecisionSource(_Content):
    """Решение ответственного лица: владельца или проверяющего инженера."""

    kind: Literal["OWNER_DECISION", "REVIEWER_DECISION"]
    decided_by: ShortText
    decided_at: date
    reference: ShortText
    """Протокол, письмо, задача."""
    basis: LongText


class CalcLegacySource(_Content):
    """Правила старого портала, от которых версия происходит. Происхождение, не основание."""

    kind: Literal["LEGACY_CODE"] = "LEGACY_CODE"
    legacy_ids: Annotated[list[LegacyId], Field(min_length=1, max_length=20)]
    note: LongText | None = None


class CalcOtherSource(_Content):
    kind: Literal["OTHER"] = "OTHER"
    description: LongText


CalcRuleSource = Annotated[
    CalcNormativeSource
    | CalcManufacturerSource
    | CalcEngineeringSource
    | CalcDecisionSource
    | CalcLegacySource
    | CalcOtherSource,
    Field(discriminator="kind"),
]


# ------------------------------------------------------------------------------ содержание


class CalcRuleContent(_Content):
    """Содержание версии правила — то, что утверждается, хешируется и больше не меняется."""

    title: ShortText
    description: LongText
    rule_type: CalcRuleType
    discipline: CalcDiscipline
    applicability: CalcRuleApplicability
    inputs: Annotated[list[CalcRuleInput], Field(max_length=30)] = Field(default_factory=list)
    parameters: Annotated[list[CalcRuleParameter], Field(max_length=30)] = Field(
        default_factory=list
    )
    outputs: Annotated[list[CalcRuleOutput], Field(min_length=1, max_length=10)]
    dimension_checks: Annotated[list[CalcRuleDimensionCheck], Field(max_length=10)] = Field(
        default_factory=list
    )
    formula: LongText
    """Формула для человека. Не исполняется."""
    explanation: LongText
    implementation_key: ImplementationKey | None = None
    """Детерминированная реализация (PROMPT 04): `vk.riser_vertical_length.v1`."""
    sources: Annotated[list[CalcRuleSource], Field(max_length=10)] = Field(default_factory=list)
    impact: LongText | None = None
    """Влияние на результат — обязательно у тендерного допущения."""
    valid_from: date | None = None
    valid_to: date | None = None

    @model_validator(mode="after")
    def _consistent(self) -> CalcRuleContent:
        names = [
            item.name for group in (self.inputs, self.parameters, self.outputs) for item in group
        ]
        if len(set(names)) != len(names):
            raise ValueError("имена входов, параметров и выходов не должны повторяться")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("начало действия позже окончания")
        return self


# ------------------------------------------------------------------------------ запросы API


class CalcRuleCreate(BaseModel):
    """Новое правило: ключ и содержание версии 1 в статусе DRAFT."""

    model_config = ConfigDict(extra="forbid")

    rule_key: RuleKey
    content: CalcRuleContent


class CalcRuleDraftUpdate(BaseModel):
    """Новое содержание черновика. Утверждённую версию так не изменить."""

    model_config = ConfigDict(extra="forbid")

    content: CalcRuleContent


class CalcRuleVersionCreate(BaseModel):
    """Новая версия: всегда с основанием изменения. Пустое содержание — копия последней."""

    model_config = ConfigDict(extra="forbid")

    change_reason: LongText
    content: CalcRuleContent | None = None


ReviewText = Annotated[str, Field(min_length=10, max_length=2000)]


class CalcHazardResolution(BaseModel):
    """Решение проверяющего по одной известной опасности: итог и почему."""

    model_config = ConfigDict(extra="forbid")

    hazard: CalcLegacyHazard
    outcome: CalcHazardOutcome
    comment: ReviewText


class CalcLegacyResolution(BaseModel):
    """Разбор правила старого портала при утверждении версии, которая от него происходит.

    Отметки «проверено» недостаточно: по каждой известной опасности — свой итог и комментарий.
    """

    model_config = ConfigDict(extra="forbid")

    legacy_id: LegacyId
    resolution: ReviewText
    """Что проверено и почему взятое верно."""
    hazards: Annotated[list[CalcHazardResolution], Field(max_length=10)] = Field(
        default_factory=list
    )

    @field_validator("hazards")
    @classmethod
    def _each_hazard_once(cls, value: list[CalcHazardResolution]) -> list[CalcHazardResolution]:
        if len({item.hazard for item in value}) != len(value):
            raise ValueError("опасность разобрана дважды")
        return value


class CalcRuleApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: LongText
    """Что проверено и по какому документу."""
    legacy_review: Annotated[list[CalcLegacyResolution], Field(max_length=20)] = Field(
        default_factory=list
    )


class CalcRuleDecision(BaseModel):
    """Отклонение или вывод из действия — всегда с причиной."""

    model_config = ConfigDict(extra="forbid")

    comment: LongText


class CalcRuleFromLegacy(BaseModel):
    """Новое правило-черновик по мотивам правила старого портала.

    Тип, раздел, область применения и выходы задаёт человек: класс из разбора не переносится —
    эвристика не становится методикой от переноса. Текст старого правила попадает в черновик
    только как исходный материал, а само старое правило остаётся в карантине неизменным.
    """

    model_config = ConfigDict(extra="forbid")

    rule_key: RuleKey
    rule_type: CalcRuleType
    discipline: CalcDiscipline
    applicability: CalcRuleApplicability
    outputs: Annotated[list[CalcRuleOutput], Field(min_length=1, max_length=10)]
    title: ShortText | None = None


# ------------------------------------------------------------------------------ ответы API


class CalcRuleReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    from_status: CalcRuleStatus
    to_status: CalcRuleStatus
    reviewer_id: UUID | None
    comment: str
    legacy_review: list[CalcLegacyResolution]
    created_at: datetime


class CalcLegacyProvenanceRead(BaseModel):
    """Правило старого портала, от которого версия происходит, и его известные опасности.

    Снимок каталога на момент сохранения версии: у утверждённой версии не меняется.
    """

    legacy_id: str
    catalog_version: str
    class_primary: CalcLegacyClass
    actions: list[CalcLegacyAction]
    hazards: list[CalcLegacyHazard]
    group_ids: list[str]


class CalcRuleVersionRead(BaseModel):
    rule_key: str
    version: int
    status: CalcRuleStatus
    rule_type: CalcRuleType
    content: CalcRuleContent
    content_sha256: str
    """Отпечаток содержания: по нему запуск расчёта докажет, какой редакцией пользовался."""
    calculation_eligible: bool
    """Может ли версия участвовать в новом расчёте. Вычисляется, пользователем не задаётся."""
    notice: str | None
    """Предупреждение для человека: у тендерного допущения — что это не норматив."""
    change_reason: str | None
    created_by: UUID | None
    edited_by: UUID | None
    """Последний, кто менял содержание черновика."""
    created_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None
    deprecated_by: UUID | None
    deprecated_at: datetime | None
    deprecation_reason: str | None
    rejected_by: UUID | None
    rejected_at: datetime | None
    rejection_reason: str | None
    legacy_provenance: list[CalcLegacyProvenanceRead]
    """Опасности старых правил, которые проверяющий обязан разобрать до утверждения."""
    reviews: list[CalcRuleReviewRead]


class CalcRuleRead(BaseModel):
    rule_key: str
    discipline: CalcDiscipline
    created_by: UUID | None
    created_at: datetime
    versions: list[CalcRuleVersionRead]


class CalcRuleSummaryRead(BaseModel):
    """Строка списка правил: последняя версия и то, что можно использовать в расчёте."""

    rule_key: str
    discipline: CalcDiscipline
    title: str
    rule_type: CalcRuleType
    systems: list[str]
    latest_version: int
    latest_status: CalcRuleStatus
    approved_version: int | None
    """Действующая утверждённая версия, если есть."""
    calculation_eligible: bool
    sources: list[str]
    """Источники одной строкой каждый: «СП 30.13330.2020, п. 5.2.1»."""
    notice: str | None


class CalcLegacyCodeRef(BaseModel):
    file: str
    lines: str | None
    symbol: str | None


class CalcLegacyRuleRead(BaseModel):
    """Правило старого портала в карантинном каталоге — только для чтения."""

    legacy_id: str
    catalog: CalcLegacyCatalog
    section: str
    location: str
    code_refs: list[CalcLegacyCodeRef]
    rule_text: str
    class_primary: CalcLegacyClass
    class_secondary: list[CalcLegacyClass]
    class_raw: str
    assumptions: str
    action_raw: str
    actions: list[CalcLegacyAction]
    hazards: list[CalcLegacyHazard]
    group_ids: list[str]
    status: CalcRuleStatus
    """Всегда UNVERIFIED_LEGACY."""
    calculation_eligible: bool
    """Всегда false."""
    notice: str


class CalcLegacyGroupRead(BaseModel):
    """Группа одинаковой логики с разными реализациями: оригиналы не схлопываются."""

    group_id: str
    title: str
    finding: str
    members: list[str]


class CalcLegacyCountRead(BaseModel):
    key: str
    count: int


class CalcLegacyCatalogRead(BaseModel):
    catalog_version: str
    generator_version: str
    entry_count: int
    """Заявленное число записей каталога — 365; сверяется при загрузке."""
    source_sha256: str
    """Отпечаток каталогов разбора PROMPT 00, из которых собран карантин."""
    content_sha256: str
    """Отпечаток самих записей и групп: сверяется при загрузке."""
    by_catalog: list[CalcLegacyCountRead]
    by_class: list[CalcLegacyCountRead]
    groups: list[CalcLegacyGroupRead]
    items: list[CalcLegacyRuleRead]
