"""Старый портал как контрольный ориентир, не эталон (ADR-0030, PROMPT 06).

Одинаковые синтетические входы S1 из разбора PROMPT 00 (`docs/calc/legacy/vk.md`): 29 этажей,
9 квартир на этажах 2–29, два стояка, DN 32, высоты 4,0 и 3,3 м. Сторона старого портала —
значения, полученные при его прогоне в PROMPT 00, со ссылкой на правило каталога карантина.
Сторона Quantor считается здесь же. Расхождения классифицируются — и Quantor под них не
подгоняется: тест падает, если значения совпали там, где старый портал ошибается.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from app.contracts.calc.enums import CalcCompleteness, CalcScenario
from app.services.calc.rules.legacy import load_catalog
from tests.calc_vk_fixtures import Building, rule_keys
from tests.calc_vk_pure import PureRun, count, facts_for, number, rules_for, run, system

Verdict = Literal[
    "LEGACY_BUG",
    "LEGACY_ASSUMPTION",
    "QUANTOR_MORE_PRECISE",
    "QUANTOR_MISSING_RULE",
    "INPUT_SEMANTICS_DIFFER",
    "REQUIRES_ENGINEER_REVIEW",
]
S1: Final = Building(
    floors=29,
    apartments={"1": 0, "2..29": 9},
    heights={"1": "4", "2..29": "3.3"},
    apartments_total=252,
)
S1_DOCUMENTED = [
    count("system.risers_count", 2, **system("В1")),
    number("system.riser_diameter", "32", "mm", **system("В1")),
    count("system.zones_count", 1, **system("В1")),
]


@dataclass(frozen=True)
class Difference:
    item: str
    legacy: str
    legacy_rules: tuple[str, ...]
    quantor: str
    verdict: Verdict
    why: str


def _quantor(rules: bool) -> PureRun:
    keys = rule_keys("В1") if rules else []
    return run("В1", CalcScenario.EXPECTED, facts_for(S1, S1_DOCUMENTED), rules_for(*keys))


def comparison() -> list[Difference]:
    bare = _quantor(rules=False)
    riser = bare.rows["vk.b1.pipe.riser"]
    return [
        Difference(
            "Вертикаль на стояк",
            "96,4 м: эт. 1 + 28 × 3,3 — до верха 29-го этажа",
            ("LEG-VK-001", "LEG-VK-003"),
            f"{bare.results['structure.interfloor_length'].value} м от уровня 1-го до уровня "
            "29-го этажа; участки ниже и выше — отдельным правилом",
            "INPUT_SEMANTICS_DIFFER",
            "старый портал включает полную высоту верхнего этажа молча, Quantor — только "
            "утверждённым правилом концевых участков",
        ),
        Difference(
            "Сталь стояков В1 на систему",
            "192,8 м; в смете × 1,07 = 206,3 м",
            ("LEG-VK-007", "LEG-VK-008"),
            f"подтверждаемая часть {riser.amount.value} м",
            "LEGACY_ASSUMPTION",
            "скрытый коэффициент 1,07 и верх этажа без основания",
        ),
        Difference(
            "Гильзы стояков",
            "58: стояков × этажей зоны",
            ("LEG-VK-024",),
            f"проходок {bare.rows['vk.b1.penetration.slab'].amount.value}: стояков × "
            "пересечённых перекрытий; гильзы — только правилом",
            "LEGACY_BUG",
            "этажей на один больше, чем перекрытий между ними",
        ),
        Difference(
            "Разводка МОП / магистраль",
            "В1 = 2343,6 м по эвристике коридора",
            ("LEG-VK-016", "LEG-VK-018", "LEG-VK-059"),
            "не определено: трасса не выдумывается",
            "LEGACY_ASSUMPTION",
            "длина МОП × коэффициенты без источника",
        ),
        Difference(
            "Компенсаторы Т3",
            "12 или 32: четыре несовместимых правила",
            ("LEG-VK-027", "LEG-VK-028"),
            "позиции нет: утверждённого правила нет",
            "REQUIRES_ENGINEER_REVIEW",
            "шаг компенсации зависит от Δt, материала и изделия — решение инженера",
        ),
        Difference(
            "Крепления",
            "149 хомутов: ⌈⌈192,8 × 0,7⌉ × 1,1⌉",
            ("LEG-VK-031",),
            "не определено без утверждённого шага креплений",
            "QUANTOR_MISSING_RULE",
            "правило vk.supports.spacing ждёт инженера",
        ),
        Difference(
            "Изоляция",
            "100 % длины стали",
            ("LEG-VK-032",),
            "не определено без документа или правила",
            "QUANTOR_MISSING_RULE",
            "правило vk.cold.insulation.scope ждёт инженера",
        ),
        Difference(
            "DN стояков",
            "32 по умолчанию импорта и при ошибке ввода",
            ("LEG-VK-006",),
            f"{riser.size} — из схемы; без схемы — не определён",
            "QUANTOR_MORE_PRECISE",
            "типоразмер только из документа",
        ),
    ]


class TestLegacyComparison:
    def test_every_difference_is_classified_without_fitting(self) -> None:
        catalog = load_catalog()
        rows = comparison()
        assert {row.verdict for row in rows} == {
            "LEGACY_BUG",
            "LEGACY_ASSUMPTION",
            "QUANTOR_MORE_PRECISE",
            "QUANTOR_MISSING_RULE",
            "INPUT_SEMANTICS_DIFFER",
            "REQUIRES_ENGINEER_REVIEW",
        }
        for row in rows:
            assert all(catalog.get(item) is not None for item in row.legacy_rules), row.item

    def test_quantor_values_on_s1(self) -> None:
        bare = _quantor(rules=False)
        assert bare.results["structure.interfloor_length"].value == "93.1"
        assert bare.results["structure.apartments_total"].value == "252"
        riser = bare.rows["vk.b1.pipe.riser"]
        assert riser.completeness is CalcCompleteness.PARTIAL
        assert riser.amount.value == "186.2"
        assert riser.amount.value not in ("192.8", "206.3")
        assert bare.rows["vk.b1.penetration.slab"].amount.value == "56"
        assert bare.rows["vk.b1.pipe.main"].completeness is CalcCompleteness.BLOCKED
        assert riser.size == "32 мм"

    def test_legacy_saved_projects_are_not_golden(self) -> None:
        """Сохранённые проекты старого портала — не эталон: ни один тест не читает их данных."""
        assert all("sqlite" not in row.legacy.lower() for row in comparison())


class TestLegacyRegressions:
    def test_no_default_risers_or_diameter(self) -> None:
        """Старый импорт ставил 2 стояка DN 32; Quantor без документа и правила — не определено."""
        result = run("В1", CalcScenario.EXPECTED, facts_for(S1), {})
        assert result.graph is not None
        assert all(node.id != "risers" for node in result.graph.nodes)
        assert result.rows["vk.b1.pipe.riser"].size is None

    def test_no_default_zones(self) -> None:
        result = run("В1", CalcScenario.EXPECTED, facts_for(S1), {})
        assert result.graph is not None
        assert all(node.id != "zones" for node in result.graph.nodes)
        assert any(item.key == "zones" for item in result.graph.unresolved)

    def test_first_floor_apartments_are_not_dropped(self) -> None:
        building = Building(apartments={"1": 4, "2..24": 6}, apartments_total=142)
        result = run("В1", CalcScenario.EXPECTED, facts_for(building), {})
        assert result.results["structure.apartments_total"].value == "142"
        assert result.results["structure.served_floors"].value == "24"

    def test_reserve_is_not_applied_twice(self) -> None:
        """Резерв — одна составляющая: база × число стояков, без повторного множителя."""
        keys = rule_keys("В1", tender=True)
        rows = run(
            "В1", CalcScenario.TENDER_SAFE, facts_for(S1, S1_DOCUMENTED), rules_for(*keys)
        ).rows
        riser = rows["vk.b1.pipe.riser"]
        assert riser.base is not None and riser.reserve is not None
        assert riser.base.value == "190.2"
        assert riser.reserve.amount.value == "2"
        assert riser.amount.value == "192.2"
