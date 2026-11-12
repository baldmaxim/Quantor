"""Листы-планы по названию (ADR-0045): слово «план» отдельным словом, с падежными формами."""

from __future__ import annotations

import pytest

from app.services.cad_plan_sheets import is_plan_sheet, is_plan_title


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


def _sheet(
    *,
    stamp: str | None = None,
    kind: str | None = None,
    title: str | None = None,
    label: str | None = None,
) -> bool:
    return is_plan_sheet(
        stamp_title=stamp, passport_kind=kind, passport_title=title, page_label=label
    )


def test_plan_sheet_stamp_plan_wins_over_other_kind() -> None:
    assert _sheet(stamp="План 3 этажа", kind="section") is True


def test_plan_sheet_floor_plan_kind_without_stamp() -> None:
    assert _sheet(kind="floor_plan", title="Лист 5") is True
    assert _sheet(stamp="Разрез 1-1", kind="floor_plan") is True


def test_plan_sheet_other_kind_is_not_plan() -> None:
    assert _sheet(kind="facade", title="Фрагменты планов и фасады") is False
    assert _sheet(kind="section", label="План") is False


def test_plan_sheet_null_kind_falls_back_to_titles() -> None:
    assert _sheet(title="План 3 этажа") is True
    assert _sheet(label="План кровли") is True
    assert _sheet(stamp="Разрез 1-1", title="План 3 этажа") is False
    assert _sheet(title="Генплан", label="План") is False
    assert _sheet() is False
