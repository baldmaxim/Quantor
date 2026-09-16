"""`MepNetworkGraph` v0.3 — сгенерированная система уровня РД.

Цепочка объяснения:

```text
EvidenceElement / EvidenceRelation   (MepEvidenceGraph, observed)
        ↓ evidence_ids
InferenceStep                        метод, входы, уверенность, альтернативы
        ↓ step_ids
NetworkNode / NetworkSegment / Parameter   derivation = provenance + step_ids + evidence_ids
```

Геометрия трёхмерна по возможности: вершина — точка листа (x, y) и/или отметка `z_mm` и
уровень. Один этаж в 2D — частный случай. Длины и количества граф не хранит: их считает
детерминированный Quantity Engine по геометрии, калибровке листа и топологии.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.contracts.mep.common import (
    CONTRACT_VERSION,
    Attribute,
    Confidence,
    ContractModel,
    DocumentRef,
    Identifier,
    Level,
    Millimetres,
    ProfileKey,
    ProfileRef,
    Sha256,
    SheetRef,
    SubjectRef,
    Tool,
    Unit,
)
from app.contracts.mep.evidence import EvidenceInputMode
from app.contracts.mep.profile import NodeRole


class GenerationProvenance(StrEnum):
    EVIDENCE_OBSERVED = "evidence_observed"
    RD_PRIOR_INFERRED = "rd_prior_inferred"
    RETRIEVED_PATTERN = "retrieved_pattern"
    DETERMINISTIC_RULE = "deterministic_rule"
    HUMAN_CONFIRMED = "human_confirmed"
    UNRESOLVED = "unresolved"


class InferenceKind(StrEnum):
    """Какое решение принято на шаге. Виды общие для любой дисциплины."""

    EVIDENCE_ADOPTION = "evidence_adoption"
    SYSTEM_ASSIGNMENT = "system_assignment"
    TOPOLOGY = "topology"
    ROUTING = "routing"
    ELEMENT_ADDITION = "element_addition"
    ATTRIBUTE = "attribute"
    RULE_APPLICATION = "rule_application"


class UnresolvedCode(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    AMBIGUOUS_CONNECTION = "ambiguous_connection"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    MISSING_ATTRIBUTE = "missing_attribute"
    MISSING_RULE = "missing_rule"
    MISSING_SCALE = "missing_scale"
    OUT_OF_PROFILE = "out_of_profile"


class EvidenceGraphRef(ContractModel):
    graph_id: Identifier
    sha256: Sha256
    input_mode: EvidenceInputMode


class GenerationRun(ContractModel):
    """Прогон генератора: без него шаги нельзя воспроизвести."""

    run_id: Identifier
    # Состояние кода: коммит и признак незакоммиченных правок, как в `RunRecord` (vision/).
    git_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{7,40}$")]
    dirty: bool
    config_sha256: Sha256
    seed: int | None = None


class CorpusRef(ContractModel):
    """Корпус случаев РД для retrieval. Только TRAIN: отложенные проекты — не источник."""

    corpus_id: Identifier
    dataset_fingerprint: Sha256
    split_sha256: Sha256
    split: Literal["train"] = "train"


class Derivation(ContractModel):
    """Происхождение элемента или значения сети."""

    provenance: GenerationProvenance
    step_ids: tuple[Identifier, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()
    confidence: Confidence | None = None


class InferenceStep(ContractModel):
    """Одно решение генератора. Входы шага — только evidence и более ранние шаги."""

    id: Identifier
    kind: InferenceKind
    tool_id: Identifier
    run_id: Identifier | None = None
    corpus_id: Identifier | None = None
    # Конфигурация шага, если отличается от конфигурации прогона.
    config_sha256: Sha256 | None = None
    evidence_ids: tuple[Identifier, ...] = ()
    relation_ids: tuple[Identifier, ...] = ()
    input_step_ids: tuple[Identifier, ...] = ()
    # Случаи TRAIN-корпуса, на которые опирается retrieval; id правил из профиля правил.
    retrieved_case_ids: tuple[Identifier, ...] = ()
    rule_ids: tuple[Identifier, ...] = ()
    confidence: Confidence | None = None
    alternatives_considered: Annotated[int, Field(ge=0)] = 0
    rationale: tuple[Annotated[str, Field(max_length=256)], ...] = ()


class Parameter(Attribute):
    """Параметр сети. Своё происхождение у каждого значения, а не у элемента целиком."""

    derivation: Derivation

    @model_validator(mode="after")
    def _unresolved_has_no_value(self) -> Parameter:
        unresolved = self.derivation.provenance == GenerationProvenance.UNRESOLVED
        if unresolved != (self.value is None):
            raise ValueError("значение отсутствует тогда и только тогда, когда оно unresolved")
        return self


class Vertex(ContractModel):
    """Точка сети: на листе (x, y нормализованы), по высоте (z_mm) и/или на уровне."""

    sheet_id: Identifier | None = None
    x: Unit | None = None
    y: Unit | None = None
    z_mm: Millimetres | None = None
    level_id: Identifier | None = None

    @model_validator(mode="after")
    def _planar_needs_sheet(self) -> Vertex:
        if (self.x is None) != (self.y is None):
            raise ValueError("x и y задаются вместе")
        if self.x is not None and self.sheet_id is None:
            raise ValueError("плановая точка задаётся на конкретном листе")
        if self.x is None and self.z_mm is None and self.level_id is None:
            raise ValueError("вершина без плана, отметки и уровня не определена")
        return self


class Port(ContractModel):
    id: Identifier
    direction: Literal["in", "out", "bidirectional", "unknown"] = "unknown"
    system_id: Identifier | None = None
    parameters: tuple[Parameter, ...] = ()


class PortRef(ContractModel):
    node_id: Identifier
    port_id: Identifier


class NetworkSystem(ContractModel):
    id: Identifier
    system_key: ProfileKey
    derivation: Derivation


class NetworkNode(ContractModel):
    id: Identifier
    role: NodeRole
    class_key: ProfileKey | None
    system_ids: tuple[Identifier, ...] = ()
    position: Vertex
    ports: tuple[Port, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    derivation: Derivation


class NetworkSegment(ContractModel):
    """Участок между двумя портами. Вертикальный переход — участок между уровнями или отметками."""

    id: Identifier
    class_key: ProfileKey | None
    system_id: Identifier
    start: PortRef
    end: PortRef
    # Включая концы; промежуточные вершины — повороты трассы.
    path: Annotated[tuple[Vertex, ...], Field(min_length=2)]
    orientation: Literal["horizontal", "vertical", "inclined", "unknown"] = "unknown"
    parameters: tuple[Parameter, ...] = ()
    derivation: Derivation


class UnresolvedDecision(ContractModel):
    """Решение, которое генератор не принял. Не прячется в уверенную выдумку."""

    id: Identifier
    code: UnresolvedCode
    subject_ids: tuple[Identifier, ...] = ()
    # Типизированные ссылки v0.3; при наличии совпадают с `subject_ids` по составу.
    subjects: tuple[SubjectRef, ...] = ()
    step_ids: tuple[Identifier, ...] = ()
    candidate_ids: tuple[Identifier, ...] = ()
    blocks_quantity: bool = True
    note: str | None = None


class MepNetworkGraph(ContractModel):
    schema_version: Literal["0.3.0"] = CONTRACT_VERSION
    graph_id: Identifier
    profile: ProfileRef
    document: DocumentRef
    evidence_graph: EvidenceGraphRef
    sheets: tuple[SheetRef, ...] = ()
    levels: tuple[Level, ...] = ()
    tools: Annotated[tuple[Tool, ...], Field(min_length=1)]
    run: GenerationRun | None = None
    corpora: tuple[CorpusRef, ...] = ()
    inference_steps: tuple[InferenceStep, ...] = ()
    systems: tuple[NetworkSystem, ...]
    nodes: tuple[NetworkNode, ...]
    segments: tuple[NetworkSegment, ...] = ()
    unresolved: tuple[UnresolvedDecision, ...] = ()
