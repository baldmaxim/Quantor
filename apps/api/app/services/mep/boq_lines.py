"""Сборка строки ВОР из накопленных вкладов: округление, распределение остатка, происхождение."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Final, Literal

from app.contracts.mep.boq import (
    BoqLine,
    GroupValueRef,
    LineSource,
    Participant,
    ProvenanceCount,
)
from app.contracts.mep.common import Attribute, ScalarValue, SubjectKind, SubjectRef
from app.contracts.mep.network import Derivation, GenerationProvenance

INFERRED: Final = frozenset(
    {
        GenerationProvenance.RD_PRIOR_INFERRED,
        GenerationProvenance.RETRIEVED_PATTERN,
        GenerationProvenance.DETERMINISTIC_RULE,
    }
)
MILLIMETRE: Final = Decimal("0.001")
MM_PER_M: Final = Decimal(1000)
PIECE: Final = Decimal(1)

Group = tuple[tuple[str, ScalarValue], ...]


@dataclass
class SourceAccumulator:
    kind: SubjectKind
    amount: Decimal = Decimal(0)
    group_values: tuple[GroupValueRef, ...] = ()
    participants: tuple[Participant, ...] = ()


@dataclass
class LineAccumulator:
    rule_id: str
    category: Literal["length", "count", "topology"]
    system_key: str
    class_key: str | None
    group: Group
    sources: dict[str, SourceAccumulator] = field(default_factory=dict)
    derivations: list[Derivation] = field(default_factory=list)

    @property
    def sort_key(self) -> str:
        values = [f"{key}={json.dumps(value)}" for key, value in self.group]
        return "|".join([self.rule_id, self.system_key, self.class_key or "-", *values])


def allocate(raw: dict[str, Decimal], total: Decimal, step: Decimal) -> dict[str, Decimal]:
    """Вклады, округлённые до шага и дающие ровно `total`.

    Метод наибольшего остатка: каждый вклад вниз до шага, недостающие шаги — источникам с большим
    отброшенным остатком, при равенстве — по id. Результат не зависит от порядка источников.
    """
    floors = {key: value.quantize(step, ROUND_FLOOR) for key, value in raw.items()}
    missing = int((total - sum(floors.values(), Decimal(0))) / step)
    ranked = sorted(raw, key=lambda key: (-(raw[key] - floors[key]), key))
    for key in ranked[:missing]:
        floors[key] += step
    return floors


def build_line(line: LineAccumulator) -> BoqLine:
    counts: dict[GenerationProvenance, int] = defaultdict(int)
    for derivation in line.derivations:
        counts[derivation.provenance] += 1
    confidences = [d.confidence for d in line.derivations if d.confidence is not None]
    raw = {key: source.amount for key, source in line.sources.items()}
    total_raw = sum(raw.values(), Decimal(0))

    # Округление — последний слой (ADR-0017): сумма копится без округления.
    if line.category == "length":
        canonical = total_raw.quantize(MILLIMETRE, ROUND_HALF_EVEN)
        quantity = (total_raw / MM_PER_M).quantize(MILLIMETRE, ROUND_HALF_EVEN)
        canonical_parts = allocate(raw, canonical, MILLIMETRE)
        quantity_parts = allocate({k: v / MM_PER_M for k, v in raw.items()}, quantity, MILLIMETRE)
    else:
        canonical = quantity = total_raw.quantize(PIECE)
        canonical_parts = quantity_parts = allocate(raw, quantity, PIECE)

    sources = tuple(
        LineSource(
            subject=SubjectRef(kind=line.sources[key].kind, id=key),
            quantity=quantity_parts[key],
            canonical_quantity=canonical_parts[key],
            group_values=line.sources[key].group_values,
            participants=line.sources[key].participants,
        )
        for key in sorted(line.sources)
    )
    digest = hashlib.sha256(line.sort_key.encode("utf-8")).hexdigest()[:16]
    return BoqLine(
        line_id=f"bl-{digest}",
        rule_id=line.rule_id,
        category=line.category,
        system_key=line.system_key,
        class_key=line.class_key,
        group=tuple(Attribute(key=key, value=value) for key, value in line.group),
        unit="m" if line.category == "length" else "pcs",
        quantity=quantity,
        canonical_unit="mm" if line.category == "length" else "pcs",
        canonical_quantity=canonical,
        source_ids=tuple(sorted(line.sources)),
        provenance=tuple(ProvenanceCount(provenance=p, count=counts[p]) for p in sorted(counts)),
        min_confidence=min(confidences) if confidences else None,
        review_required=any(d.provenance in INFERRED for d in line.derivations),
        # Все правила v0 — суммы вкладов (метры участков, штуки узлов и поворотов).
        additive=True,
        sources=sources,
    )
