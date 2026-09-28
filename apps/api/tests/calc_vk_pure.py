"""Чистый прогон калькулятора ВК без базы: снимок → ядро → синтез → позиции (PROMPT 06).

Тот же код, что в оркестраторе, но входы — синтетические снимки и версии правил в памяти.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.contracts.calc.engine import CalcResultRead, CalcSnapshotItem
from app.contracts.calc.enums import CalcScenario
from app.contracts.calc.passport import CalcExpectedQuantityBody
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.synthesis import CalcSystemGraph
from app.contracts.calc.values import CalcCountValue, CalcEnumValue, CalcFactValue, CalcNumberValue
from app.services.calc.engine import planner
from app.services.calc.engine.catalog import CALCULATORS, HANDLERS
from app.services.calc.engine.executor import Execution, execute
from app.services.calc.engine.plan_types import FactOutcome, Plan, ResolvedRule
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from app.services.calc.synthesis.definitions import SynthesisOutcome, fact_keys, synthesize
from app.services.calc.systems.vk.spec import SPECS_BY_CODE
from app.services.calc.systems.vk.volume_base import VolumeInputs
from app.services.calc.systems.vk.volumes import generate
from tests.calc_engine_fixtures import resolved, snapshot_item
from tests.calc_vk_fixtures import FUNCTIONS, Building, content_for


def item(fact_type: str, value: CalcFactValue, **subject: str) -> CalcSnapshotItem:
    return snapshot_item(fact_type, CalcFactSubject(**subject), value)


def count(fact_type: str, value: int, **subject: str) -> CalcSnapshotItem:
    return item(fact_type, CalcCountValue(value=value), **subject)


def number(fact_type: str, value: str, unit: str, **subject: str) -> CalcSnapshotItem:
    return item(fact_type, CalcNumberValue(value=value, unit=unit), **subject)


def system(code: str) -> dict[str, str]:
    return {"building": "1", "discipline": "VK", "system_code": code}


def facts_for(building: Building, extra: Iterable[CalcSnapshotItem] = ()) -> dict[str, FactOutcome]:
    place = {"building": "1"} | ({"section": building.section} if building.section else {})
    items = [count("building.floors_above_ground", building.floors, building="1")]
    if building.apartments_total is not None:
        items.append(count("building.apartments_total", building.apartments_total, building="1"))
    items += [
        count("floor.apartments_count", value, **place, floor=floor)
        for floor, value in building.apartments.items()
    ]
    items += [
        number("floor.height", value, "m", **place, floor=floor)
        for floor, value in building.heights.items()
    ]
    items += [
        number("floor.elevation", value, "m", **place, floor=floor)
        for floor, value in building.elevations.items()
    ]
    items += [
        item("system.function", CalcEnumValue(value=function), **system(code))
        for code, function in building.systems.items()
    ]
    items += list(extra)
    return {entry.fact_key: entry for entry in items}


def rules_for(
    *keys: str, overrides: Mapping[str, Mapping[str, str]] | None = None
) -> dict[str, ResolvedRule]:
    """Утверждённые в памяти версии правил из шаблонов с синтетическими параметрами."""
    changed = overrides or {}
    return {key: resolved(key, content_for(key, **dict(changed.get(key, {})))) for key in keys}


@dataclass(frozen=True)
class PureRun:
    plan: Plan
    execution: Execution | None
    results: dict[str, CalcResultRead]
    synthesis: SynthesisOutcome | None
    graph: CalcSystemGraph | None
    rows: dict[str, CalcExpectedQuantityBody]


def run(
    code: str,
    scenario: CalcScenario,
    facts: Mapping[str, FactOutcome],
    rules: Mapping[str, ResolvedRule],
    *,
    section: str | None = None,
) -> PureRun:
    spec = SPECS_BY_CODE[code]
    definition = CALCULATORS[(spec.calculator_id, spec.version)]
    scope = CalcFactSubject(building="1", section=section, discipline="VK", system_code=code)
    plan = planner.plan(definition, scenario, scope, facts, dict(rules), HANDLERS)
    run_id = uuid.uuid4()
    execution = execute(plan, run_id, {}) if plan.runnable else None
    results = {} if execution is None else {row.result_key: row for row in execution.results}
    synthesis: SynthesisOutcome | None = None
    if execution is not None:
        synthesizer = SYNTHESIZERS[(spec.synthesizer_id, spec.version)]
        keys, _ = fact_keys(synthesizer, scope)
        synthesis = synthesize(
            synthesizer,
            scenario=scenario,
            scope=scope,
            calculation_run_id=run_id,
            results=results,
            facts={key.fact_key: facts[key.fact_key] for key in keys if key.fact_key in facts},
            rules=dict(rules),
            handlers=HANDLERS,
        )
    graph = None if synthesis is None else synthesis.graph
    bindings = (
        {}
        if execution is None
        else {
            step.step_key: f"{step.rule.rule_key}@{step.rule.version}"
            for step in execution.steps
            if step.rule is not None
        }
    )
    rows = generate(
        VolumeInputs(
            spec=spec,
            scenario=scenario,
            scope=scope,
            graph=graph,
            results=results,
            assumptions=() if execution is None else execution.assumptions,
            calculation_run_id=run_id,
            synthesis_run_id=None if synthesis is None else uuid.uuid4(),
            material=None,
            rule_refs={
                key: bindings[result.step_key]
                for key, result in results.items()
                if result.step_key in bindings
            },
        )
    )
    return PureRun(
        plan, execution, results, synthesis, graph, {row.quantity_key: row for row in rows}
    )


__all__ = ["FUNCTIONS", "PureRun", "count", "facts_for", "number", "rules_for", "run", "system"]
