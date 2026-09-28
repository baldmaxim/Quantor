"""Рабочие синтезаторы структуры В1, Т3, Т4, К1 стадии П (PROMPT 06).

Каждый строит граф по своему калькулятору (`vk.<система>.stage_p@1`), фактам системы и правилам
топологии. Все факты и результаты необязательны: чего нет — то неопределённость в графе, а не
блокировка всего синтеза. Отпечатки графов контрольных примеров закреплены ниже.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from app.contracts.calc.enums import (
    CalcCalculatorKind,
    CalcDiscipline,
    CalcDocumentStage,
    CalcRuleType,
    CalcScenario,
    CalcSynthesisRuleRole,
)
from app.services.calc.synthesis.definitions import (
    SynthesisContext,
    SynthesisFactSpec,
    SynthesizerDef,
)
from app.services.calc.synthesis.rules import SynthesisRuleSpec
from app.services.calc.systems.vk.spec import B1, K1, T3, T4, VkSystemSpec
from app.services.calc.systems.vk.steps import RESULTS
from app.services.calc.systems.vk.structure import build_for

_SYSTEM: Final = ("building", "section", "discipline", "system_code")
_TOPOLOGY: Final = CalcSynthesisRuleRole.TOPOLOGY

GOLDEN: Final[Mapping[str, tuple[tuple[str, str], ...]]] = {
    "В1": (
        (
            "complete_expected",
            "be6ee766e1d24a6cc59fd82bd42135549133e3b116d845673c4d494770cb4cdc",
        ),
        (
            "bare_minimum",
            "eaecd64572cc30ba2feb995c739b45e36eb686737facaa888c6880cb2ea751a6",
        ),
    ),
    "Т3": (
        (
            "complete_expected",
            "fe6d8f98e9b7ee37396b6d0fa68404257d3e575195d85f80bb2073f432ee10d6",
        ),
        (
            "bare_minimum",
            "066cef3d4ff0dbacb3db312449f3beb4a56bb9aafc937bb9a0a151e70ce8394b",
        ),
    ),
    "Т4": (
        (
            "complete_expected",
            "858ebdaad7c69cbf7325b6055f4aea098135b12b6f0b10f48de5ea505145e577",
        ),
        (
            "bare_minimum",
            "f654458d0e7546ca0a00b4b5dc3bce11cb840e71f8af5f29731cc5251afe6b5b",
        ),
    ),
    "К1": (
        (
            "complete_expected",
            "544b688b64d2931dc2f8e6ce22e723a266d956b40f8e1d44623495755c1fae23",
        ),
        (
            "bare_minimum",
            "9217264202a0ec8cfe18655f3e29c345eedc8cbceb08af353ea9876ddc0a00ad",
        ),
    ),
}


def _fact(fact_type: str) -> SynthesisFactSpec:
    return SynthesisFactSpec(fact_type, _SYSTEM, required=False)


def _facts(spec: VkSystemSpec) -> dict[str, SynthesisFactSpec]:
    facts = {
        "risers": _fact("system.risers_count"),
        "riser_diameter": _fact("system.riser_diameter"),
        "main_diameter": _fact("system.main_diameter"),
        "main_length": _fact("system.main_length"),
        "material": _fact("system.pipe_material"),
    }
    if spec.zones_rule is not None:
        facts["zones"] = _fact("system.zones_count")
    if spec.source == "INLET":
        facts |= {
            "inlets": _fact("system.inlets_count"),
            "pump": _fact("system.pump_station_present"),
            "meters": _fact("system.water_meter_units_count"),
        }
    elif spec.source == "HOT_SOURCE":
        facts["hot_source"] = _fact("system.hot_water_source")
    elif spec.source == "OUTLET":
        facts |= {"outlets": _fact("system.outlets_count"), "vent": _fact("system.vent_scheme")}
    return facts


def _rules(spec: VkSystemSpec) -> dict[str, SynthesisRuleSpec]:
    rules = {
        "topology": SynthesisRuleSpec(
            role=_TOPOLOGY,
            rule_key=spec.topology_rule,
            allowed_types=frozenset({CalcRuleType.ENGINEERING, CalcRuleType.GEOMETRY}),
            outputs=("connections",),
        )
    }
    if spec.riser_valves_rule is not None:
        rules["riser_valves"] = SynthesisRuleSpec(
            role=_TOPOLOGY,
            rule_key=spec.riser_valves_rule,
            allowed_types=frozenset({CalcRuleType.NORMATIVE, CalcRuleType.ENGINEERING}),
            outputs=("count",),
        )
    if spec.balancing_rule is not None:
        rules["balancing"] = SynthesisRuleSpec(
            role=_TOPOLOGY,
            rule_key=spec.balancing_rule,
            allowed_types=frozenset({CalcRuleType.ENGINEERING, CalcRuleType.MANUFACTURER}),
            outputs=("count",),
        )
    return rules


def synthesizer_for(spec: VkSystemSpec) -> SynthesizerDef:
    def contexts() -> Mapping[str, SynthesisContext]:
        from app.services.calc.systems.vk.structure_golden import golden_contexts

        return golden_contexts(definition, spec)

    definition = SynthesizerDef(
        synthesizer_id=spec.synthesizer_id,
        version=spec.version,
        title=f"Структура {spec.code} стадии П — {spec.title.lower()}",
        kind=CalcCalculatorKind.PRODUCTION,
        discipline=CalcDiscipline.VK,
        systems=(spec.code,),
        stage=CalcDocumentStage.P,
        scenarios=frozenset(CalcScenario),
        graph_type=f"vk.{spec.slug}.structure",
        calculator_id=spec.calculator_id,
        calculator_version=spec.version,
        results=(),
        facts=_facts(spec),
        rules=_rules(spec),
        build=build_for(spec),
        golden=GOLDEN[spec.code],
        golden_contexts=contexts,
        optional_results=tuple(key for key, *_ in RESULTS),
    )
    return definition


VK_SYNTHESIZERS: Final = tuple(synthesizer_for(spec) for spec in (B1, T3, T4, K1))
