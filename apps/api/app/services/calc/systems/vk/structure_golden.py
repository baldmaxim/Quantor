"""Контрольные примеры синтезаторов ВК: детерминированные синтетические входы без базы.

Отпечатки графов закреплены в определениях синтезаторов и входят в отпечаток реализации.
Правила примеров — шаблоны заявок с синтетическими параметрами и пометкой «не инженерное
основание»: они проверяют алгоритм построения графа, а не норму.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Final

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
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import (
    CalcBooleanValue,
    CalcCountValue,
    CalcEnumValue,
    CalcFactValue,
)
from app.services.calc.engine.catalog import HANDLERS
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.plan_types import ResolvedRule
from app.services.calc.rules.validation import content_sha256
from app.services.calc.synthesis.definitions import SynthesisContext, SynthesizerDef
from app.services.calc.synthesis.rules import RuleUse, use_rule
from app.services.calc.systems.vk.rule_needs import NEEDS_BY_KEY
from app.services.calc.systems.vk.rule_templates import rule_content
from app.services.calc.systems.vk.spec import VkSystemSpec

_NAMESPACE: Final = uuid.UUID("0b6f8f7e-3c61-4b7a-9b0e-6a0d5c2f7a11")
GOLDEN_RUN: Final = uuid.uuid5(_NAMESPACE, "vk-golden-calculation-run")
_PARAMETERS: Final[Mapping[str, Mapping[str, str]]] = {
    "topology": {"per_floor": "1"},
    "riser_valves": {"per_riser": "1"},
    "balancing": {"per_riser": "1"},
}
_RESULTS: Final[Mapping[str, tuple[str, str]]] = {
    "structure.top_floor": ("24", "floor"),
    "structure.served_floors": ("23", "floor"),
    "structure.interfloor_length": ("69", "m"),
    "structure.slab_crossings": ("23", "slab"),
    "structure.risers_min": ("3", "riser"),
    "structure.risers_max": ("4", "riser"),
    "structure.zones": ("2", "zone"),
    "structure.shafts_max": ("2", "shaft"),
    "demand.fixtures_observed": ("150", "fixture"),
    "quantity.end_bottom": ("1.5", "m"),
    "quantity.end_top": ("0.5", "m"),
    "quantity.connection_length_min": ("2", "m"),
    "quantity.connection_length_max": ("3.5", "m"),
}
_BARE: Final = (
    "structure.top_floor",
    "structure.served_floors",
    "structure.interfloor_length",
    "structure.slab_crossings",
    "structure.risers_min",
    "structure.risers_max",
)


def _result(spec: VkSystemSpec, key: str) -> CalcResultRead:
    value, unit = _RESULTS[key]
    return CalcResultRead(
        run_id=GOLDEN_RUN,
        result_key=key,
        title=key,
        value=value,
        unit=unit,
        category=CalcResultCategory.ENGINEERING,
        discipline=CalcDiscipline.VK,
        system_code=spec.code,
        scenario=CalcScenario.EXPECTED,
        step_key="golden",
        output=key.rsplit(".", 1)[-1],
        rounding=None,
    )


def _fact(fact_type: str, subject: CalcFactSubject, value: CalcFactValue) -> CalcSnapshotItem:
    key = f"{fact_type}@{subject.key()}"
    fact_id = uuid.uuid5(_NAMESPACE, key)
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
        item_sha256=canonical_sha256({"key": key, "value": value.model_dump(mode="json")}),
    )


def _facts(spec: VkSystemSpec) -> dict[str, CalcSnapshotItem]:
    system = CalcFactSubject(building="1", discipline="VK", system_code=spec.code)
    facts: dict[str, CalcSnapshotItem] = {}
    if spec.source == "INLET":
        facts["inlets"] = _fact("system.inlets_count", system, CalcCountValue(value=1))
        facts["pump"] = _fact("system.pump_station_present", system, CalcBooleanValue(value=True))
    elif spec.source == "HOT_SOURCE":
        facts["hot_source"] = _fact("system.hot_water_source", system, CalcEnumValue(value="ITP"))
    elif spec.source == "OUTLET":
        facts["outlets"] = _fact("system.outlets_count", system, CalcCountValue(value=2))
        facts["vent"] = _fact("system.vent_scheme", system, CalcEnumValue(value="VENTED_STACKS"))
    return facts


def _resolved(rule_key: str, name: str, spec: VkSystemSpec) -> ResolvedRule:
    content = rule_content(NEEDS_BY_KEY[rule_key], _PARAMETERS[name], systems=[spec.code])
    return ResolvedRule(
        rule_key=rule_key,
        rule_version_id=uuid.uuid5(_NAMESPACE, f"{rule_key}@1"),
        version=1,
        status=CalcRuleStatus.APPROVED,
        rule_type=CalcRuleType(content.rule_type),
        content=content,
        content_sha256=content_sha256(content),
    )


def _uses(
    definition: SynthesizerDef, spec: VkSystemSpec, scenario: CalcScenario
) -> dict[str, RuleUse]:
    uses: dict[str, RuleUse] = {}
    for name, rule_spec in definition.rules.items():
        used = use_rule(
            name,
            rule_spec,
            _resolved(rule_spec.rule_key, name, spec),
            scenario=scenario,
            scope=_scope(spec),
            stage=definition.stage,
            results={},
            handlers=HANDLERS,
        )
        if isinstance(used, CalcBlockingReason):
            raise ValueError(f"контрольный пример: правило {name} блокирует: {used.message}")
        uses[name] = used
    return uses


def _scope(spec: VkSystemSpec) -> CalcFactSubject:
    return CalcFactSubject(building="1", discipline="VK", system_code=spec.code)


def golden_contexts(definition: SynthesizerDef, spec: VkSystemSpec) -> dict[str, SynthesisContext]:
    """Два примера: полный набор с правилами (EXPECTED) и голый расчёт без правил (MINIMUM)."""
    results = {key: _result(spec, key) for key in _RESULTS}
    bare = {key: results[key] for key in _BARE}
    return {
        "complete_expected": SynthesisContext(
            definition=definition,
            scenario=CalcScenario.EXPECTED,
            scope=_scope(spec),
            calculation_run_id=GOLDEN_RUN,
            results=results,
            facts=_facts(spec),
            rules=_uses(definition, spec, CalcScenario.EXPECTED),
        ),
        "bare_minimum": SynthesisContext(
            definition=definition,
            scenario=CalcScenario.MINIMUM,
            scope=_scope(spec),
            calculation_run_id=GOLDEN_RUN,
            results=bare,
            facts={},
            rules={},
        ),
    }
