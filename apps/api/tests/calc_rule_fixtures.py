"""Синтетические правила для проверки механики реестра (PROMPT 03).

Не инженерные правила: ключи начинаются с `test.`, источники — фиктивные документы внутри
тестов. В рабочий реестр они не попадают — живут только в тестовой базе.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.contracts.calc.rules import CalcRuleContent

TEST_NOTE = "Синтетическая тестовая фикстура реестра правил, не инженерное правило."


def geometry_content(**overrides: Any) -> dict[str, Any]:
    """Длина стояка = высота этажа × этажи + запас. Размерность сходится: м × эт + м = м."""
    content: dict[str, Any] = {
        "title": "Тестовая длина стояка",
        "description": "Проверка механики реестра: геометрическое правило с запасом.",
        "rule_type": "GEOMETRY",
        "discipline": "VK",
        "applicability": {
            "systems": ["В1"],
            "stages": ["P"],
            "scope": "Синтетический жилой дом для тестов.",
            "limitations": [],
        },
        "inputs": [
            {
                "name": "floor_height",
                "kind": "FACT",
                "fact_type": "floor.height",
                "unit": "m",
                "description": "Высота этажа.",
            },
            {
                "name": "floors",
                "kind": "FACT",
                "fact_type": "building.floors_above_ground",
                "unit": "floor",
                "description": "Этажей над землёй.",
            },
        ],
        "parameters": [
            {
                "name": "reserve",
                "value": "0.5",
                "unit": "m",
                "description": "Тестовый запас длины.",
            }
        ],
        "outputs": [
            {
                "name": "length",
                "quantity": "pipe.length",
                "unit": "m",
                "description": "Длина стояка.",
            }
        ],
        "dimension_checks": [
            {
                "output": "length",
                "terms": [
                    {"factors": [{"name": "floor_height"}, {"name": "floors"}]},
                    {"factors": [{"name": "reserve"}]},
                ],
            }
        ],
        "formula": "L = h × n + reserve",
        "explanation": "Высота этажа, умноженная на число этажей, плюс запас.",
        "implementation_key": "test.riser_length.v1",
        "sources": [{"kind": "OTHER", "description": TEST_NOTE}],
    }
    content.update(overrides)
    return content


def normative_source(**overrides: Any) -> dict[str, Any]:
    """Фиктивный нормативный документ — существует только внутри тестов."""
    source: dict[str, Any] = {
        "kind": "NORMATIVE_DOCUMENT",
        "document_title": "Тестовый свод правил",
        "designation": "ТЕСТ 00.00000.0000",
        "edition": "ред. 1",
        "clause": "п. 1.1",
        "page": "3",
        "edition_date": date(2020, 1, 1).isoformat(),
    }
    source.update(overrides)
    return source


def manufacturer_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "kind": "MANUFACTURER_DOCUMENT",
        "manufacturer": "Тест-Завод",
        "product_line": "Линейка А",
        "document_title": "Тестовый каталог",
        "document_version": "2.1",
        "document_date": date(2024, 5, 1).isoformat(),
        "location": "табл. 4",
        "scope": "Только линейка А тестового производителя.",
    }
    source.update(overrides)
    return source


def engineering_source() -> dict[str, Any]:
    return {
        "kind": "ENGINEERING_METHOD",
        "title": "Тестовая методика",
        "author": "Тестовый отдел",
        "reference": "тестовое хранилище методик",
        "summary": "Методика существует только в тестах.",
    }


def decision_source(**overrides: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "kind": "OWNER_DECISION",
        "decided_by": "Тестовый владелец",
        "decided_at": date(2026, 9, 28).isoformat(),
        "reference": "тестовый протокол № 1",
        "basis": "Тендерная стадия, трасс нет.",
    }
    source.update(overrides)
    return source


def content(**overrides: Any) -> CalcRuleContent:
    return CalcRuleContent.model_validate(geometry_content(**overrides))
