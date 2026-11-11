"""Листы-планы по названию (ADR-0045): слово «план» отдельным словом, с падежными формами."""

from __future__ import annotations

import pytest

from app.services.cad_plan_sheets import is_plan_title


@pytest.mark.parametrize(
    "title",
    [
        "План 3 этажа",
        "ПЛАН КРОВЛИ",
        "Поэтажный план",
        "Фрагмент плана",
        "Планы этажей",
        "План на отм. +3,000",
        "Совмещённый план (ёмкость)",
        "Экспликация и планами жилых этажей",
        "на плане",
        "ПЛАНОМ",
    ],
)
def test_plan_titles(title: str) -> None:
    assert is_plan_title(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "Генплан",
        "Планировка",
        "Схема планировочной организации",
        "Разрез 1-1",
        "Фасад в осях 1-12",
        "Планета",
        "plan",
        "",
        None,
    ],
)
def test_not_plan_titles(title: str | None) -> None:
    assert is_plan_title(title) is False
