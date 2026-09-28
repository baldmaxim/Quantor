"""Эталонные сценарии калькулятора ВК G01–G08 (ADR-0030, PROMPT 06).

Синтетические здания и правила-шаблоны с синтетическими параметрами (не нормативы). Значения
позиций закреплены: изменение алгоритма, меняющее их, должно быть осознанным.
"""

from __future__ import annotations

from app.contracts.calc.enums import CalcBlockCode, CalcCompleteness, CalcScenario
from app.services.calc.engine.plan_types import Absence
from tests.calc_vk_fixtures import Building, rule_keys
from tests.calc_vk_pure import PureRun, count, facts_for, number, rules_for, run, system

E = CalcScenario.EXPECTED
B1 = tuple(rule_keys("В1"))


def _shape(result: PureRun) -> dict[str, tuple[str, str]]:
    shaped: dict[str, tuple[str, str]] = {}
    for key, row in result.rows.items():
        amount = row.amount
        value = amount.value or (f"{amount.low}–{amount.high}" if amount.low else "—")
        shaped[key] = (row.completeness.value, value)
    return shaped


def test_g01_simple_residential_building() -> None:
    result = run("В1", E, facts_for(Building()), rules_for(*B1))
    assert _shape(result) == {
        "vk.b1.pipe.riser": ("RANGE", "144.4–216.6"),
        "vk.b1.pipe.connection": ("RANGE", "92–241.5"),
        "vk.b1.pipe.main": ("BLOCKED", "—"),
        "vk.b1.pipe.total": ("PARTIAL", "236.4–458.1"),
        "vk.b1.fitting.branch": ("RANGE", "46–69"),
        "vk.b1.fitting.riser_end": ("RANGE", "2–3"),
        "vk.b1.fitting.transition": ("BLOCKED", "—"),
        "vk.b1.fitting.route_fallback": ("PARTIAL", "119–230"),
        "vk.b1.valve.riser_shutoff": ("RANGE", "2–3"),
        "vk.b1.penetration.slab": ("RANGE", "46–69"),
        "vk.b1.sleeve.slab": ("RANGE", "46–69"),
        "vk.b1.firestop.slab": ("RANGE", "46–69"),
        "vk.b1.insulation.riser": ("RANGE", "144.4–216.6"),
        "vk.b1.insulation.main": ("BLOCKED", "—"),
        "vk.b1.support.riser": ("RANGE", "50–75"),
        "vk.b1.support.horizontal": ("PARTIAL", "46–138"),
        "vk.b1.equipment.pump_station": ("BLOCKED", "—"),
        "vk.b1.connection.floor": ("RANGE", "46–69"),
    }


def test_g02_different_floor_heights_and_elevations() -> None:
    heights = {"1": "4.5", "2..10": "3", "11": "3.6", "12..24": "3"}
    by_heights = run("В1", E, facts_for(Building(heights=heights)), {})
    assert by_heights.results["structure.interfloor_length"].value == "71.1"
    with_levels = Building(heights=heights, elevations={"1": "0", "24": "71.15"})
    by_levels = run("В1", E, facts_for(with_levels), {})
    assert by_levels.results["structure.interfloor_length"].value == "71.15"


def test_g03_several_sections_are_separate_scopes() -> None:
    section_one = Building(section="1", apartments={"1": 0, "2..24": 4})
    section_two = Building(section="2", floors=24, apartments={"1": 0, "2..17": 6, "18..24": 0})
    facts = facts_for(section_one) | facts_for(section_two)
    one = run("В1", E, facts, rules_for(*B1), section="1")
    two = run("В1", E, facts, rules_for(*B1), section="2")
    assert one.results["structure.top_floor"].value == "24"
    assert two.results["structure.top_floor"].value == "17"
    assert two.results["structure.interfloor_length"].value == "49.2"
    assert one.rows["vk.b1.connection.floor"].amount.value == "46"
    assert (
        two.rows["vk.b1.connection.floor"].amount.low,
        two.rows["vk.b1.connection.floor"].amount.high,
    ) == ("32", "48")


def test_g04_incomplete_documentation() -> None:
    result = run("В1", E, facts_for(Building(heights={})), rules_for(*B1))
    riser = result.rows["vk.b1.pipe.riser"]
    assert riser.completeness is CalcCompleteness.BLOCKED
    assert "step:structure_vertical" in riser.blocked_by
    assert result.rows["vk.b1.connection.floor"].completeness is CalcCompleteness.RANGE
    assert result.rows["vk.b1.penetration.slab"].completeness is CalcCompleteness.BLOCKED


def test_g05_document_conflict() -> None:
    facts = facts_for(Building())
    key = next(key for key in facts if key.startswith("floor.apartments_count@") and "2..24" in key)
    facts[key] = Absence(CalcBlockCode.FACT_CONFLICT, "квартирография и экспликация расходятся")
    result = run("В1", E, facts, rules_for(*B1))
    assert {item.code for item in result.plan.reasons if item.step_key == "structure_floors"} == {
        CalcBlockCode.FACT_CONFLICT
    }
    assert "structure.top_floor" not in result.results
    assert all(
        row.completeness is CalcCompleteness.BLOCKED
        for key, row in result.rows.items()
        if key.startswith("vk.b1.pipe.")
    )


def test_g06_riser_count_range() -> None:
    building = Building(apartments={"1": 0, "2..24": 8}, apartments_total=184)
    result = run("В1", E, facts_for(building), rules_for(*B1))
    assert result.synthesis is not None
    assert [item.key for item in result.synthesis.variants] == ["risers_3", "risers_4"]
    riser = result.rows["vk.b1.pipe.riser"]
    assert (riser.amount.low, riser.amount.high) == ("216.6", "288.8")


def test_g07_known_and_unknown_routes() -> None:
    main = number("system.main_length", "38.5", "m", **system("В1"))
    rules = rules_for(*(key for key in B1 if "connection.length" not in key))
    result = run("В1", E, facts_for(Building(), [main]), rules)
    shaped = _shape(result)
    assert shaped["vk.b1.pipe.main"] == ("COMPLETE", "38.5")
    assert shaped["vk.b1.pipe.connection"] == ("BLOCKED", "—")
    assert shaped["vk.b1.pipe.total"] == ("PARTIAL", "182.9–255.1")


def test_g08_tender_safe_with_explicit_assumption() -> None:
    keys = rule_keys("В1", tender=True)
    observed = count("system.risers_count", 3, **system("В1"))
    facts = facts_for(Building(), [observed])
    expected = run("В1", E, facts, rules_for(*keys)).rows["vk.b1.pipe.riser"]
    tender = run("В1", CalcScenario.TENDER_SAFE, facts, rules_for(*keys)).rows["vk.b1.pipe.riser"]
    assert expected.amount.value == "216.6" and expected.reserve is None
    assert tender.base is not None and tender.base.value == "216.6"
    assert tender.reserve is not None and tender.reserve.amount.value == "3"
    assert tender.amount.value == "219.6"
    assert tender.completeness is CalcCompleteness.COMPLETE
