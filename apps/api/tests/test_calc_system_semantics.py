"""Назначение систем ВК из легенды и записки (PROMPT 06) — без базы.

Назначение принимается только из строки, где названа ровно одна система и её смысл сказан
словами. Две системы в строке или два смысла сразу — строка пропускается: догадки нет.
"""

from __future__ import annotations

import pytest

from app.contracts.calc.enums import CalcConfidence
from app.services.calc.adapters.system_semantics import function_of, legend_pairs


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("водопровод хозяйственно-питьевой", ("COLD_WATER", CalcConfidence.HIGH)),
        ("Водопровод холодной воды", ("COLD_WATER", CalcConfidence.HIGH)),
        ("водопровод горячей воды подающий", ("HOT_WATER_SUPPLY", CalcConfidence.HIGH)),
        # Без слова «подающий» — горячая вода, но уверенность ниже.
        ("Горячее водоснабжение", ("HOT_WATER_SUPPLY", CalcConfidence.MEDIUM)),
        ("трубопровод горячей воды циркуляционный", ("HOT_WATER_CIRCULATION", CalcConfidence.HIGH)),
        ("Канализация бытовая", ("DOMESTIC_SEWER", CalcConfidence.HIGH)),
        # Два смысла сразу — не угадываем.
        ("холодной воды и горячей воды", None),
        ("водосток", None),
    ],
)
def test_function_of(text: str, expected: tuple[str, CalcConfidence] | None) -> None:
    assert function_of(text) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Т3 — водопровод горячей воды подающий", [("Т3", "водопровод горячей воды подающий")]),
        ("В1: водопровод хозяйственно-питьевой", [("В1", "водопровод хозяйственно-питьевой")]),
        ("| К1 | Канализация бытовая |", [("К1", "Канализация бытовая")]),
        # Латинская буква в обозначении — та же система.
        ("T4 — трубопровод циркуляционный", [("T4", "трубопровод циркуляционный")]),
        # Две системы в одной строке: назначения каждой не определены.
        ("Т3, Т4 — горячее водоснабжение", []),
        ("| Т3 | Т4 | горячее водоснабжение |", []),
        # Строка таблицы без описания или с двумя описаниями.
        ("| В1 |", []),
        ("| В1 | водопровод | хозяйственно-питьевой |", []),
        ("Примечание: см. лист 3", []),
    ],
)
def test_legend_pairs(line: str, expected: list[tuple[str, str]]) -> None:
    assert legend_pairs(line) == expected
