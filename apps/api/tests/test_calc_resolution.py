"""Выбор действующего значения и снимок для расчётного ядра (ADR-0030, PROMPT 01).

Главное свойство: ничего не выбирается молча, а ВОР Заказчика в расчёт не попадает никогда.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDocumentStage,
    CalcFactMethod,
    CalcFactStatus,
    CalcResolutionState,
    CalcReviewStatus,
    CalcSourceClass,
)
from app.contracts.calc.fact_types import REGISTRY
from app.contracts.calc.values import CalcCountValue, CalcFactValue, CalcNumberValue, CalcTextValue
from app.errors import InvariantError
from app.services.calc.facts.policy import DEFAULT_POLICY, policy_for
from app.services.calc.facts.resolution import (
    ClaimView,
    DecisionView,
    KeyResolution,
    Resolution,
    build_snapshot,
    claim_set_hash,
    resolve,
)

T0 = datetime(2026, 9, 28, tzinfo=UTC)
APARTMENTS = REGISTRY["floor.apartments_count"]
HEIGHT = REGISTRY["floor.height"]
MATERIAL = REGISTRY["system.pipe_material"]


def _apts(count: int) -> CalcCountValue:
    return CalcCountValue(value=count, unit="apartment")


def claim(
    value: CalcFactValue,
    *,
    source_class: CalcSourceClass = CalcSourceClass.APARTMENT_SCHEDULE,
    stage: CalcDocumentStage = CalcDocumentStage.P,
    sha: str | None = None,
    review: CalcReviewStatus = CalcReviewStatus.UNREVIEWED,
    status: CalcFactStatus = CalcFactStatus.ACTIVE,
    minutes: int = 0,
) -> ClaimView:
    return ClaimView(
        id=uuid.uuid4(),
        value=value,
        method=CalcFactMethod.TABLE_EXPLICIT,
        confidence=CalcConfidence.HIGH,
        source_class=source_class,
        document_stage=stage,
        source_content_sha256=sha,
        review_status=review,
        status=status,
        calculation_eligible=source_class is not CalcSourceClass.CUSTOMER_VOR,
        created_at=T0 + timedelta(minutes=minutes),
    )


class TestResolve:
    def test_no_claims_means_missing_not_zero(self) -> None:
        result = resolve(APARTMENTS, [], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.MISSING
        assert result.value is None

    def test_single_claim(self) -> None:
        one = claim(_apts(9))
        result = resolve(APARTMENTS, [one], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.SINGLE
        assert result.value == _apts(9)

    def test_agreement_within_tolerance_is_corroboration(self) -> None:
        a = claim(CalcNumberValue(value="3.3", unit="m"), source_class=CalcSourceClass.ARCHITECTURE)
        b = claim(
            CalcNumberValue(value="3.305", unit="m"),
            source_class=CalcSourceClass.EXPLANATORY_NOTE,
            minutes=1,
        )
        result = resolve(HEIGHT, [a, b], None, policy_for(HEIGHT.key))
        assert result.state is CalcResolutionState.CORROBORATED
        assert not result.disagreement
        # Представитель — старший по политике источник: разрез АР, а не записка.
        assert result.chosen == a

    def test_disagreement_without_policy_is_unresolved(self) -> None:
        """По умолчанию политика требует человека: значения нет, а не «первое попавшееся»."""
        a = claim(CalcTextValue(value="сталь"), source_class=CalcSourceClass.MEP_DESIGN)
        b = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.EXPLANATORY_NOTE)
        result = resolve(MATERIAL, [a, b], None, DEFAULT_POLICY)
        assert result.state is CalcResolutionState.UNRESOLVED
        assert result.value is None
        assert result.disagreement

    def test_policy_depends_on_stage(self) -> None:
        """Квартирография РД сильнее квартирографии П; конфликт при этом остаётся открытым."""
        early = claim(_apts(9), stage=CalcDocumentStage.P)
        late = claim(_apts(8), stage=CalcDocumentStage.RD, minutes=5)
        result = resolve(APARTMENTS, [early, late], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.AUTO_PREFERRED
        assert result.value == _apts(8)
        assert "CONFLICT_OPEN" in result.warnings

    def test_policy_tie_is_unresolved(self) -> None:
        a = claim(_apts(9))
        b = claim(_apts(8), minutes=1)
        result = resolve(APARTMENTS, [a, b], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.UNRESOLVED

    def test_rejected_claim_does_not_vote(self) -> None:
        good = claim(_apts(9))
        rejected = claim(_apts(8), review=CalcReviewStatus.REJECTED, minutes=1)
        result = resolve(APARTMENTS, [good, rejected], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.SINGLE
        assert result.claim_ids == (good.id,)

    def test_inactive_claims_do_not_vote(self) -> None:
        current = claim(_apts(9))
        old = claim(_apts(8), status=CalcFactStatus.SUPERSEDED)
        result = resolve(APARTMENTS, [current, old], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.SINGLE

    def test_same_file_twice_is_not_two_confirmations(self) -> None:
        a = claim(_apts(9), sha="a" * 64)
        b = claim(_apts(9), sha="a" * 64, minutes=1)
        result = resolve(APARTMENTS, [a, b], None, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.SINGLE

    def test_decision_wins_and_goes_stale_when_claims_change(self) -> None:
        a = claim(CalcTextValue(value="сталь"), source_class=CalcSourceClass.MEP_DESIGN)
        b = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.EXPLANATORY_NOTE)
        decision = DecisionView(chosen_fact_id=b.id, claim_set_hash=claim_set_hash([a.id, b.id]))

        decided = resolve(MATERIAL, [a, b], decision, DEFAULT_POLICY)
        assert decided.state is CalcResolutionState.DECIDED
        assert decided.value == CalcTextValue(value="PE-X")

        c = claim(
            CalcTextValue(value="PP-R"), source_class=CalcSourceClass.ADJACENT_TASK, minutes=3
        )
        stale = resolve(MATERIAL, [a, b, c], decision, DEFAULT_POLICY)
        assert stale.state is CalcResolutionState.DECIDED_STALE
        assert "DECISION_STALE" in stale.warnings

    def test_decision_is_moot_without_disagreement(self) -> None:
        """Проигравшее утверждение отклонено: решать нечего, «решение устарело» не висит."""
        a = claim(_apts(8), source_class=CalcSourceClass.ARCHITECTURE)
        b = claim(_apts(9), minutes=1)
        decision = DecisionView(chosen_fact_id=a.id, claim_set_hash=claim_set_hash([a.id, b.id]))
        rejected = claim(_apts(9), review=CalcReviewStatus.REJECTED, minutes=1)
        result = resolve(APARTMENTS, [a, rejected], decision, policy_for(APARTMENTS.key))
        assert result.state is CalcResolutionState.SINGLE
        assert result.value == _apts(8)
        assert result.warnings == ()

    def test_decision_for_inactive_claim_is_ignored_visibly(self) -> None:
        a = claim(CalcTextValue(value="сталь"), source_class=CalcSourceClass.MEP_DESIGN)
        b = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.EXPLANATORY_NOTE)
        decision = DecisionView(chosen_fact_id=uuid.uuid4(), claim_set_hash="0" * 64)
        result = resolve(MATERIAL, [a, b], decision, DEFAULT_POLICY)
        assert result.state is CalcResolutionState.UNRESOLVED
        assert "DECISION_CLAIM_INACTIVE" in result.warnings


class TestCustomerVorIsNotAReference:
    """ВОР Заказчика — объект сверки: решение из ВОР не может подтвердить сам ВОР."""

    def test_vor_alone_gives_no_value(self) -> None:
        vor = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.CUSTOMER_VOR)
        result = resolve(MATERIAL, [vor], None, DEFAULT_POLICY)
        assert result.state is CalcResolutionState.MISSING
        assert result.excluded_ids == (vor.id,)

    def test_vor_does_not_corroborate_or_contradict(self) -> None:
        design = claim(CalcTextValue(value="сталь"), source_class=CalcSourceClass.MEP_DESIGN)
        vor = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.CUSTOMER_VOR)
        result = resolve(MATERIAL, [design, vor], None, DEFAULT_POLICY)
        assert result.state is CalcResolutionState.SINGLE
        assert not result.disagreement
        assert result.value == CalcTextValue(value="сталь")

    def test_snapshot_contains_no_customer_vor(self) -> None:
        design = claim(CalcTextValue(value="сталь"), source_class=CalcSourceClass.MEP_DESIGN)
        vor = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.CUSTOMER_VOR)
        vor_only = claim(CalcTextValue(value="PP-R"), source_class=CalcSourceClass.CUSTOMER_VOR)
        snapshot = build_snapshot(
            [
                KeyResolution(
                    "system.pipe_material@VK:В1",
                    MATERIAL.key,
                    "discipline=VK|system_code=В1",
                    resolve(MATERIAL, [design, vor], None, DEFAULT_POLICY),
                ),
                KeyResolution(
                    "system.pipe_material@VK:Т3",
                    MATERIAL.key,
                    "discipline=VK|system_code=Т3",
                    resolve(MATERIAL, [vor_only], None, DEFAULT_POLICY),
                ),
            ]
        )
        assert [item.chosen_fact_id for item in snapshot.items] == [design.id]
        # Ключ, известный только из ВОР, в снимок не попадает вовсе — не нулём, а отсутствием.
        assert all("Т3" not in item.fact_key for item in snapshot.items)

    def test_snapshot_refuses_an_ineligible_claim(self) -> None:
        """Даже если выбор ошибётся, сборка снимка не пропустит ВОР — она падает."""
        vor = claim(CalcTextValue(value="PE-X"), source_class=CalcSourceClass.CUSTOMER_VOR)
        forged = Resolution(
            state=CalcResolutionState.SINGLE,
            value=vor.value,
            chosen=vor,
            claim_ids=(vor.id,),
            excluded_ids=(),
            claim_set_hash=claim_set_hash([vor.id]),
            disagreement=False,
            warnings=(),
        )
        with pytest.raises(InvariantError):
            build_snapshot([KeyResolution("k", MATERIAL.key, "s", forged)])


class TestSnapshot:
    def test_unresolved_and_missing_are_absent_not_zero(self) -> None:
        a = claim(_apts(9))
        b = claim(_apts(8), minutes=1)
        unresolved = resolve(APARTMENTS, [a, b], None, policy_for(APARTMENTS.key))
        snapshot = build_snapshot([KeyResolution("k", APARTMENTS.key, "s", unresolved)])
        assert snapshot.items == ()

    def test_hash_does_not_depend_on_input_order(self) -> None:
        a = KeyResolution(
            "a", APARTMENTS.key, "s", resolve(APARTMENTS, [claim(_apts(9))], None, DEFAULT_POLICY)
        )
        b = KeyResolution(
            "b", APARTMENTS.key, "s", resolve(APARTMENTS, [claim(_apts(4))], None, DEFAULT_POLICY)
        )
        assert build_snapshot([a, b]).sha256 == build_snapshot([b, a]).sha256
