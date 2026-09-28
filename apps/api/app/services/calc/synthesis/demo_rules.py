"""Синтетические правила демо-синтеза (PROMPT 05) — данные, не инженерная методика ВК.

Содержания версий правил `test.*`, на которых держатся контрольные примеры демо-синтезатора и
тесты. В рабочую базу они не засеваются: утверждённые версии заводят только тесты через API
реестра правил.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

_NOTE: Final = "Синтетика проверки синтеза структуры, не инженерное правило."
_APPLICABILITY: Final[dict[str, Any]] = {
    "systems": ["В1"],
    "stages": ["P"],
    "scope": "Синтетический дом для тестов синтеза структуры.",
    "limitations": ["только синтетика тестов"],
}
_METHOD: Final[dict[str, Any]] = {
    "kind": "ENGINEERING_METHOD",
    "title": "Тестовая методика синтеза",
    "author": "Тестовый отдел",
    "reference": "тестовое хранилище методик",
    "summary": _NOTE,
}


def _quantity(name: str, quantity: str, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "QUANTITY",
        "quantity": quantity,
        "unit": "riser",
        "description": description,
    }


def riser_range(per_riser_min: str = "20", per_riser_max: str = "24") -> dict[str, Any]:
    return {
        "title": "Тест: диапазон числа стояков",
        "description": "Квартир на стояк — тестовая вместимость, не норма.",
        "rule_type": "ENGINEERING",
        "discipline": "VK",
        "applicability": _APPLICABILITY,
        "inputs": [
            {
                "name": "apartments",
                "kind": "FACT",
                "fact_type": "building.apartments_total",
                "unit": "apartment",
                "description": "Квартир в корпусе.",
            }
        ],
        "parameters": [
            {"name": "per_riser_min", "value": per_riser_min, "description": "Тест: не меньше."},
            {"name": "per_riser_max", "value": per_riser_max, "description": "Тест: не больше."},
        ],
        "outputs": [
            {
                "name": "risers_min",
                "quantity": "vk.risers.min",
                "unit": "riser",
                "description": "Стояков не меньше.",
            },
            {
                "name": "risers_max",
                "quantity": "vk.risers.max",
                "unit": "riser",
                "description": "Стояков не больше.",
            },
        ],
        "formula": "n_min = ⌈квартир / макс⌉; n_max = ⌈квартир / мин⌉",
        "explanation": "Тестовая вместимость стояка даёт диапазон, а не одно число.",
        "implementation_key": "test.riser_range.v1",
        "sources": [_METHOD],
    }


def riser_topology() -> dict[str, Any]:
    return {
        "title": "Тест: ветвь на стояк на каждом типовом этаже",
        "description": "Топология демо-синтеза: ввод → стояки → этажные ветви.",
        "rule_type": "ENGINEERING",
        "discipline": "VK",
        "applicability": _APPLICABILITY,
        "parameters": [
            {"name": "per_floor", "value": "1", "description": "Ветвей на стояк на этаже."}
        ],
        "outputs": [
            {
                "name": "branches",
                "quantity": "vk.floor_branch.per_riser",
                "unit": None,
                "description": "Ветвей на стояк на этаже.",
            }
        ],
        "formula": "ветвей = стояков × типовых этажей × 1",
        "explanation": "Каждый стояк отдаёт одну ветвь на каждом типовом этаже.",
        "implementation_key": "test.branches_per_floor.v1",
        "sources": [_METHOD],
    }


def riser_choice() -> dict[str, Any]:
    return {
        "title": "Тест: выбор числа стояков из диапазона",
        "description": "При тестовых условиях выбирается верхняя граница диапазона расчёта.",
        "rule_type": "ENGINEERING",
        "discipline": "VK",
        "applicability": _APPLICABILITY,
        "inputs": [
            _quantity("count_min", "vk.risers.min", "Нижняя граница."),
            _quantity("count_max", "vk.risers.max", "Верхняя граница."),
        ],
        "outputs": [
            {
                "name": "count",
                "quantity": "vk.risers.selected",
                "unit": "riser",
                "description": "Выбранное число стояков.",
            }
        ],
        "formula": "n = n_max",
        "explanation": "Тестовое правило выбора — не методика ВК.",
        "implementation_key": "test.select_upper_count.v1",
        "sources": [_METHOD],
    }


def riser_reserve(reserve: str = "1") -> dict[str, Any]:
    return {
        "title": "Тест: тендерный резерв стояков",
        "description": "Резерв на неопределённость стадии П — тендерное допущение.",
        "rule_type": "TENDER_ASSUMPTION",
        "discipline": "VK",
        "applicability": _APPLICABILITY,
        "parameters": [
            {
                "name": "reserve_count",
                "value": reserve,
                "unit": "riser",
                "description": "Тест: резерв.",
            }
        ],
        "outputs": [
            {
                "name": "reserve",
                "quantity": "vk.risers.reserve",
                "unit": "riser",
                "description": "Резервных стояков.",
            }
        ],
        "formula": "резерв = k",
        "explanation": "Тендерный резерв на отсутствие решения по стоякам.",
        "implementation_key": "test.reserve_count.v1",
        "impact": "Добавляет резервные стояки только в TENDER_SAFE.",
        "sources": [
            {
                "kind": "OWNER_DECISION",
                "decided_by": "Тестовый владелец",
                "decided_at": date(2026, 9, 28).isoformat(),
                "reference": "тестовый протокол",
                "basis": _NOTE,
            }
        ],
    }


RULE_KEYS: Final = {
    "riser_range": "test.engineering.riser_range",
    "topology": "test.synthesis.riser_topology",
    "selection": "test.synthesis.riser_choice",
    "reserve": "test.tender.riser_reserve",
}
