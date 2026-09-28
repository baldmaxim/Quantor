"""Контрольные примеры демо-синтезатора: детерминированные входы без базы.

Отпечатки графов этих примеров закреплены в определении синтезатора и входят в отпечаток его
реализации. Изменил алгоритм — примеры не сходятся (тест), и версию синтезатора надо поднять.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from app.contracts.calc.engine import CalcBlockingReason, CalcResultRead, CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDiscipline,
    CalcFactMethod,
    CalcResolutionState,
    CalcResultCategory,
    CalcReviewStatus,
    CalcRuleStatus,
    CalcRuleType,
    CalcScenario,
    CalcSourceClass,
)
from app.contracts.calc.rules import CalcRuleContent
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcCountValue
from app.services.calc.engine.catalog import HANDLERS
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.plan_types import ResolvedRule
from app.services.calc.rules.validation import content_sha256
from app.services.calc.synthesis import demo_rules
from app.services.calc.synthesis.definitions import SynthesisContext, SynthesizerDef
from app.services.calc.synthesis.rules import RuleUse, use_rule

_NAMESPACE: Final = uuid.UUID("5f2b2d1e-0c4a-4f2e-9d53-6c1c7a9e0b05")
GOLDEN_RUN: Final = uuid.uuid5(_NAMESPACE, "golden-calculation-run")
SCOPE: Final = CalcFactSubject(building="1", floor="1..24", discipline="VK", system_code="В1")


def result(key: str, value: str) -> CalcResultRead:
    return CalcResultRead(
        run_id=GOLDEN_RUN,
        result_key=key,
        title=key,
        value=value,
        unit="riser",
        category=CalcResultCategory.ENGINEERING,
        discipline=CalcDiscipline.VK,
        system_code="В1",
        scenario=CalcScenario.EXPECTED,
        step_key="riser_range",
        output=key.rsplit(".", 1)[-1],
        rounding=None,
    )


def fact(fact_type: str, subject: CalcFactSubject, count: int) -> CalcSnapshotItem:
    key = f"{fact_type}@{subject.key()}"
    fact_id = uuid.uuid5(_NAMESPACE, key)
    value = CalcCountValue(value=count)
    return CalcSnapshotItem(
        fact_key=key,
        fact_type=fact_type,
        subject=subject,
        fact_id=fact_id,
        fact_version=1,
        value=value,
        stated_value=value,
        method=CalcFactMethod.TABLE_EXPLICIT,
        confidence=CalcConfidence.HIGH,
        review_status=CalcReviewStatus.CONFIRMED,
        resolution_state=CalcResolutionState.SINGLE,
        source_id=uuid.uuid5(_NAMESPACE, "source"),
        source_class=CalcSourceClass.MEP_DESIGN,
        claim_ids=[fact_id],
        evidence=[],
        calculation_eligible=True,
        item_sha256=canonical_sha256({"key": key, "count": count}),
    )


def resolved(rule_key: str, content: dict[str, Any], version: int = 1) -> ResolvedRule:
    parsed = CalcRuleContent.model_validate(content)
    return ResolvedRule(
        rule_key=rule_key,
        rule_version_id=uuid.uuid5(_NAMESPACE, f"{rule_key}@{version}"),
        version=version,
        status=CalcRuleStatus.APPROVED,
        rule_type=CalcRuleType(parsed.rule_type),
        content=parsed,
        content_sha256=content_sha256(parsed),
    )


def _uses(
    definition: SynthesizerDef,
    scenario: CalcScenario,
    results: dict[str, CalcResultRead],
    names: tuple[str, ...],
) -> dict[str, RuleUse]:
    contents = {
        "topology": demo_rules.riser_topology(),
        "selection": demo_rules.riser_choice(),
        "reserve": demo_rules.riser_reserve(),
    }
    uses: dict[str, RuleUse] = {}
    for name in names:
        spec = definition.rules[name]
        used = use_rule(
            name,
            spec,
            resolved(spec.rule_key, contents[name]),
            scenario=scenario,
            scope=SCOPE,
            stage=definition.stage,
            results=results,
            handlers=HANDLERS,
        )
        if isinstance(used, CalcBlockingReason):
            raise ValueError(f"контрольный пример: правило {name} блокирует: {used.message}")
        uses[name] = used
    return uses


def golden_contexts() -> dict[str, SynthesisContext]:
    """Два примера: диапазон без правила выбора и TENDER_SAFE с выбором и резервом."""
    from app.services.calc.synthesis.demo import RISER_STRUCTURE

    definition = RISER_STRUCTURE
    results = {
        "demo.risers_min": result("demo.risers_min", "4"),
        "demo.risers_max": result("demo.risers_max", "5"),
    }
    facts = {
        "inlets": fact(
            "system.inlets_count",
            CalcFactSubject(building="1", discipline="VK", system_code="В1"),
            1,
        ),
        "floors": fact("building.floors_above_ground", CalcFactSubject(building="1"), 24),
        "shafts": fact("floor.shafts_count", CalcFactSubject(building="1", floor="1..24"), 2),
    }

    def context(scenario: CalcScenario, names: tuple[str, ...]) -> SynthesisContext:
        return SynthesisContext(
            definition=definition,
            scenario=scenario,
            scope=SCOPE,
            calculation_run_id=GOLDEN_RUN,
            results=results,
            facts=facts,
            rules=_uses(definition, scenario, results, names),
        )

    return {
        "range_expected": context(CalcScenario.EXPECTED, ("topology",)),
        "tender_selected": context(CalcScenario.TENDER_SAFE, ("topology", "selection", "reserve")),
    }
