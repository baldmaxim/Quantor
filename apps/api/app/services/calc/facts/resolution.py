"""Действующее значение ключа факта и снимок для расчётного ядра.

Чистые функции без базы: всё, что решает, какое значение пойдёт в расчёт, проверяется
тестами на обычных объектах.

Правило одно: **ничего не выбирается молча**. Одно утверждение или согласные — значение есть.
Расхождение — либо решение человека, либо значение по политике с открытым конфликтом, либо
значения нет вовсе. Утверждения, не допущенные к расчёту (ВОР Заказчика), в выборе не
участвуют и в снимок не попадают — это проверяется и здесь, и ограничением базы.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDocumentStage,
    CalcFactMethod,
    CalcFactStatus,
    CalcPolicyMode,
    CalcResolutionState,
    CalcReviewStatus,
    CalcSourceClass,
)
from app.contracts.calc.fact_types import FACT_TYPES_VERSION, CalcFactTypeDef, values_agree
from app.contracts.calc.values import CalcFactValue
from app.errors import InvariantError
from app.services.calc.facts.policy import POLICY_VERSION, PolicyEntry, rank_of

SNAPSHOT_VERSION: Final = "calc.facts_snapshot.v1"

_VALUED_STATES: Final = frozenset(
    {
        CalcResolutionState.SINGLE,
        CalcResolutionState.CORROBORATED,
        CalcResolutionState.DECIDED,
        CalcResolutionState.DECIDED_STALE,
        CalcResolutionState.AUTO_PREFERRED,
    }
)


@dataclass(frozen=True, slots=True)
class ClaimView:
    """Утверждение глазами алгоритма выбора."""

    id: uuid.UUID
    value: CalcFactValue
    method: CalcFactMethod
    confidence: CalcConfidence
    source_class: CalcSourceClass
    document_stage: CalcDocumentStage
    source_content_sha256: str | None
    review_status: CalcReviewStatus
    status: CalcFactStatus
    calculation_eligible: bool
    created_at: datetime
    source_id: uuid.UUID | None = None
    """Источник утверждения — чтобы показать, откуда взято значение."""


@dataclass(frozen=True, slots=True)
class DecisionView:
    chosen_fact_id: uuid.UUID
    claim_set_hash: str


@dataclass(frozen=True, slots=True)
class Resolution:
    state: CalcResolutionState
    value: CalcFactValue | None
    chosen: ClaimView | None
    claim_ids: tuple[uuid.UUID, ...]
    """Утверждения, участвовавшие в выборе."""
    excluded_ids: tuple[uuid.UUID, ...]
    """Действующие утверждения, не допущенные к расчёту."""
    claim_set_hash: str
    disagreement: bool
    warnings: tuple[str, ...]


def claim_set_hash(ids: Sequence[uuid.UUID]) -> str:
    """Отпечаток набора утверждений: по нему видно, что решение принималось не по нынешнему."""
    joined = "\n".join(sorted(str(item) for item in ids))
    return hashlib.sha256(joined.encode()).hexdigest()


def _collapse_duplicates(
    definition: CalcFactTypeDef, claims: Sequence[ClaimView]
) -> list[ClaimView]:
    """Один и тот же файл, заведённый дважды, — не два независимых подтверждения."""
    kept: list[ClaimView] = []
    for claim in sorted(claims, key=lambda item: (item.created_at, str(item.id))):
        duplicate = claim.source_content_sha256 is not None and any(
            other.source_content_sha256 == claim.source_content_sha256
            and values_agree(definition, other.value, claim.value)
            for other in kept
        )
        if not duplicate:
            kept.append(claim)
    return kept


def _all_agree(definition: CalcFactTypeDef, claims: Sequence[ClaimView]) -> bool:
    return all(
        values_agree(definition, a.value, b.value)
        for index, a in enumerate(claims)
        for b in claims[index + 1 :]
    )


def _preference(entry: PolicyEntry, claim: ClaimView) -> tuple[int, int, datetime, str]:
    """Порядок представителя согласных утверждений: ранг, проверка человеком, время."""
    rank = rank_of(entry, claim.source_class, claim.document_stage)
    confirmed = 0 if claim.review_status is CalcReviewStatus.CONFIRMED else 1
    return (
        rank if rank is not None else len(entry.ranking),
        confirmed,
        claim.created_at,
        str(claim.id),
    )


def resolve(
    definition: CalcFactTypeDef,
    claims: Sequence[ClaimView],
    decision: DecisionView | None,
    policy: PolicyEntry,
) -> Resolution:
    """Действующее значение одного ключа."""
    active = [claim for claim in claims if claim.status is CalcFactStatus.ACTIVE]
    excluded = tuple(sorted((c.id for c in active if not c.calculation_eligible), key=str))
    considered = [
        claim
        for claim in active
        if claim.calculation_eligible and claim.review_status is not CalcReviewStatus.REJECTED
    ]
    ids = tuple(sorted((claim.id for claim in considered), key=str))
    set_hash = claim_set_hash(ids)
    distinct = _collapse_duplicates(definition, considered)
    disagreement = not _all_agree(definition, distinct)
    warnings: list[str] = []

    def result(
        state: CalcResolutionState, chosen: ClaimView | None, extra: Sequence[str] = ()
    ) -> Resolution:
        return Resolution(
            state=state,
            value=None if chosen is None else chosen.value,
            chosen=chosen,
            claim_ids=ids,
            excluded_ids=excluded,
            claim_set_hash=set_hash,
            disagreement=disagreement,
            warnings=(*warnings, *extra),
        )

    if not distinct:
        return result(CalcResolutionState.MISSING, None)

    # Решение отвечает на расхождение. Когда расхождения больше нет (проигравшее утверждение
    # отклонено или отозвано), решать нечего: иначе висело бы «решение устарело», которое
    # нельзя снять — конфликт закрыт. Вернётся расхождение — решение снова в силе, но устаревшим.
    if decision is not None and disagreement:
        chosen = next((c for c in considered if c.id == decision.chosen_fact_id), None)
        if chosen is not None:
            if decision.claim_set_hash == set_hash:
                return result(CalcResolutionState.DECIDED, chosen)
            return result(CalcResolutionState.DECIDED_STALE, chosen, ("DECISION_STALE",))
        warnings.append("DECISION_CLAIM_INACTIVE")

    if not disagreement:
        best = min(distinct, key=lambda claim: _preference(policy, claim))
        state = (
            CalcResolutionState.SINGLE if len(distinct) == 1 else CalcResolutionState.CORROBORATED
        )
        return result(state, best)

    if policy.mode is CalcPolicyMode.AUTO_PREFER:
        ranked = [
            (rank, claim)
            for claim in distinct
            if (rank := rank_of(policy, claim.source_class, claim.document_stage)) is not None
        ]
        if ranked:
            top = min(rank for rank, _ in ranked)
            leaders = [claim for rank, claim in ranked if rank == top]
            if _all_agree(definition, leaders):
                best = min(leaders, key=lambda claim: _preference(policy, claim))
                return result(CalcResolutionState.AUTO_PREFERRED, best, ("CONFLICT_OPEN",))
    return result(CalcResolutionState.UNRESOLVED, None, ("CONFLICT_OPEN",))


# ------------------------------------------------------------------------ снимок для ядра


@dataclass(frozen=True, slots=True)
class SnapshotItem:
    fact_key: str
    fact_type: str
    subject_key: str
    state: CalcResolutionState
    value: CalcFactValue
    chosen_fact_id: uuid.UUID
    method: CalcFactMethod
    confidence: CalcConfidence
    review_status: CalcReviewStatus


@dataclass(frozen=True, slots=True)
class FactsSnapshot:
    """То, что увидит расчётное ядро: действующие значения только допущенных утверждений."""

    items: tuple[SnapshotItem, ...]
    sha256: str
    policy_version: str
    fact_types_version: str
    snapshot_version: str


@dataclass(frozen=True, slots=True)
class KeyResolution:
    fact_key: str
    fact_type: str
    subject_key: str
    resolution: Resolution


def build_snapshot(resolutions: Sequence[KeyResolution]) -> FactsSnapshot:
    """Снимок фактов для расчёта.

    Ключ без значения в снимок не попадает: отсутствие не превращается в ноль. Утверждение, не
    допущенное к расчёту, в снимке — нарушение инварианта, и сборка падает, а не пропускает его.
    """
    items: list[SnapshotItem] = []
    for entry in sorted(resolutions, key=lambda item: item.fact_key):
        resolution = entry.resolution
        chosen = resolution.chosen
        if resolution.state not in _VALUED_STATES or chosen is None:
            continue
        if not chosen.calculation_eligible or chosen.source_class is CalcSourceClass.CUSTOMER_VOR:
            raise InvariantError("в снимок расчёта попало утверждение, не допущенное к расчёту")
        items.append(
            SnapshotItem(
                fact_key=entry.fact_key,
                fact_type=entry.fact_type,
                subject_key=entry.subject_key,
                state=resolution.state,
                value=chosen.value,
                chosen_fact_id=chosen.id,
                method=chosen.method,
                confidence=chosen.confidence,
                review_status=chosen.review_status,
            )
        )
    payload = [
        {
            "fact_key": item.fact_key,
            "value": item.value.model_dump(mode="json"),
            "chosen_fact_id": str(item.chosen_fact_id),
            "state": item.state.value,
        }
        for item in items
    ]
    digest = hashlib.sha256(
        json.dumps(
            {
                "items": payload,
                "policy": POLICY_VERSION,
                "fact_types": FACT_TYPES_VERSION,
                "snapshot": SNAPSHOT_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return FactsSnapshot(
        items=tuple(items),
        sha256=digest,
        policy_version=POLICY_VERSION,
        fact_types_version=FACT_TYPES_VERSION,
        snapshot_version=SNAPSHOT_VERSION,
    )
