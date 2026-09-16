"""`MepBoq` v0.3 — ВОР только с количествами, выведенный из `MepNetworkGraph`.

Цен, ставок и сумм здесь нет: расценка — отдельный слой поверх неизменяемых количеств. Модель и
изображение в расчёте не участвуют; всё, чего нет в графе, становится блокером, а не догадкой.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.contracts.mep.common import (
    CONTRACT_VERSION,
    Attribute,
    Confidence,
    ContractModel,
    Identifier,
    ProfileKey,
    ProfileRef,
    ScalarValue,
    Sha256,
    SubjectRef,
)
from app.contracts.mep.network import EvidenceGraphRef, GenerationProvenance

Quantity = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]


class BoqStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    REFUSED = "refused"


class BlockerCode(StrEnum):
    NETWORK_INVALID = "NETWORK_INVALID"
    DECISION_BLOCKS_QUANTITY = "DECISION_BLOCKS_QUANTITY"
    CLASS_UNRESOLVED = "CLASS_UNRESOLVED"
    PARAMETER_MISSING = "PARAMETER_MISSING"
    PARAMETER_UNRESOLVED = "PARAMETER_UNRESOLVED"
    NODE_SYSTEM_AMBIGUOUS = "NODE_SYSTEM_AMBIGUOUS"
    NO_SCALE = "NO_SCALE"
    CROSS_SHEET_PLANAR = "CROSS_SHEET_PLANAR"
    ELEVATION_INCOMPLETE = "ELEVATION_INCOMPLETE"
    LENGTH_UNDETERMINED = "LENGTH_UNDETERMINED"
    FITTING_RULES_NOT_APPROVED = "FITTING_RULES_NOT_APPROVED"


class NetworkGraphRef(ContractModel):
    graph_id: Identifier
    sha256: Sha256


class EngineRef(ContractModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[str, Field(min_length=1, max_length=32)]


class ProvenanceCount(ContractModel):
    provenance: GenerationProvenance
    count: Annotated[int, Field(ge=1)]


class GroupValueRef(ContractModel):
    """Откуда значение ключа группы: параметр элемента сети. История вывода — у самого параметра."""

    key: ProfileKey
    subject: SubjectRef
    parameter_key: ProfileKey


class Participant(ContractModel):
    """Участник производной величины: узел-якорь, подключённые или сравниваемые участки."""

    subject: SubjectRef
    role: Literal["anchor", "connected", "compared"]
    parameter_key: ProfileKey | None = None
    value: ScalarValue | None = None


class LineSource(ContractModel):
    """Источник строки. Вклад есть только у аддитивной строки и выдан движком, а не интерфейсом."""

    subject: SubjectRef
    quantity: Quantity | None = None
    canonical_quantity: Quantity | None = None
    group_values: tuple[GroupValueRef, ...] = ()
    participants: tuple[Participant, ...] = ()


class BoqLine(ContractModel):
    """Строка ВОР: правило, группа по ключам профиля, количество и все элементы-источники."""

    line_id: Identifier
    rule_id: Annotated[str, Field(min_length=1, max_length=64)]
    category: Literal["length", "count", "topology"]
    system_key: ProfileKey
    class_key: ProfileKey | None
    group: tuple[Attribute, ...] = ()
    unit: Literal["m", "pcs"]
    quantity: Quantity
    # Канон длины — миллиметр (ADR-0018); у штучных строк совпадает с количеством.
    canonical_unit: Literal["mm", "pcs"]
    canonical_quantity: Quantity
    source_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    provenance: tuple[ProvenanceCount, ...]
    min_confidence: Confidence | None = None
    # Есть вклад выведенного генератором, а не наблюдённого: строку смотрит инженер.
    review_required: bool
    # Строка — сумма вкладов источников. Для неаддитивных правил вкладов нет.
    additive: bool = False
    sources: tuple[LineSource, ...] = ()

    @model_validator(mode="after")
    def _sources_are_consistent(self) -> BoqLine:
        if not self.sources:
            return self
        if sorted({s.subject.id for s in self.sources}) != sorted(set(self.source_ids)):
            raise ValueError("sources не совпадают с source_ids")
        with_quantity = [s for s in self.sources if s.quantity is not None]
        if not self.additive:
            if with_quantity:
                raise ValueError("у неаддитивной строки нет вкладов источников")
            return self
        if len(with_quantity) != len(self.sources) or any(
            s.canonical_quantity is None for s in self.sources
        ):
            raise ValueError("у аддитивной строки вклад есть у каждого источника")
        total = sum((s.quantity or Decimal(0) for s in self.sources), Decimal(0))
        canonical = sum((s.canonical_quantity or Decimal(0) for s in self.sources), Decimal(0))
        if total != self.quantity or canonical != self.canonical_quantity:
            raise ValueError("вклады источников не складываются в количество строки")
        return self


class QuantityBlocker(ContractModel):
    code: BlockerCode
    severity: Literal["blocker", "warning"]
    subject_ids: tuple[Identifier, ...] = ()
    key: ProfileKey | None = None
    message: Annotated[str, Field(max_length=512)]
    # Типизированные ссылки v0.3: только те subject_ids, вид которых однозначен.
    subjects: tuple[SubjectRef, ...] = ()


class RuleRef(ContractModel):
    rule_id: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(min_length=1, max_length=512)]


class MepBoq(ContractModel):
    schema_version: Literal["0.3.0"] = CONTRACT_VERSION
    boq_id: Identifier
    lane: Literal["STRICT"] = "STRICT"
    status: BoqStatus
    network_graph: NetworkGraphRef
    evidence_graph: EvidenceGraphRef
    profile: ProfileRef
    engine: EngineRef
    rules: tuple[RuleRef, ...]
    lines: tuple[BoqLine, ...]
    blockers: tuple[QuantityBlocker, ...] = ()
