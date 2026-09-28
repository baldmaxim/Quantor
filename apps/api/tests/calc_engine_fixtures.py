"""Синтетика для расчётного ядра (PROMPT 04): правила демо-калькулятора и снимок фактов.

Правила `test.*` существуют только в тестах — в рабочей базе их нет. Значения — синтетические.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from app.contracts.calc.engine import CalcSnapshotItem
from app.contracts.calc.enums import (
    CalcConfidence,
    CalcFactMethod,
    CalcResolutionState,
    CalcReviewStatus,
    CalcRuleStatus,
    CalcRuleType,
    CalcSourceClass,
)
from app.contracts.calc.rules import CalcRuleContent
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcCountValue, CalcFactValue, CalcNumberValue
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.plan_types import ResolvedRule
from app.services.calc.rules.validation import content_sha256

TEST_NOTE = "Синтетическая тестовая фикстура расчётного ядра, не инженерное правило."
SCOPE = CalcFactSubject(building="1", floor="2..24", discipline="VK", system_code="В1")
APPLICABILITY: dict[str, Any] = {
    "systems": ["В1"],
    "stages": ["P"],
    "scope": "Синтетический дом для тестов ядра.",
    "limitations": ["только тесты"],
}


def _input(name: str, fact_type: str, unit: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "FACT",
        "fact_type": fact_type,
        "unit": unit,
        "description": f"Тестовый вход {name}.",
    }


def vertical_length_rule(**overrides: Any) -> dict[str, Any]:
    content: dict[str, Any] = {
        "title": "Тест: вертикальная длина",
        "description": "Высота этажа × этажность — синтетика ядра.",
        "rule_type": "GEOMETRY",
        "discipline": "VK",
        "applicability": APPLICABILITY,
        "inputs": [
            _input("floor_height", "floor.height", "m"),
            _input("floors", "building.floors_above_ground", "floor"),
        ],
        "outputs": [
            {
                "name": "length",
                "quantity": "pipe.vertical_length",
                "unit": "m",
                "description": "Длина.",
            }
        ],
        "dimension_checks": [
            {
                "output": "length",
                "terms": [{"factors": [{"name": "floor_height"}, {"name": "floors"}]}],
            }
        ],
        "formula": "L = h × n",
        "explanation": "Высота этажа, умноженная на число этажей.",
        "implementation_key": "test.vertical_length.v1",
        "sources": [{"kind": "OTHER", "description": TEST_NOTE}],
    }
    content.update(overrides)
    return content


def total_length_rule(**overrides: Any) -> dict[str, Any]:
    content: dict[str, Any] = {
        "title": "Тест: длина по стоякам",
        "description": "Длина × число стояков — синтетика ядра.",
        "rule_type": "GEOMETRY",
        "discipline": "VK",
        "applicability": APPLICABILITY,
        "inputs": [
            {
                "name": "length",
                "kind": "QUANTITY",
                "quantity": "pipe.vertical_length",
                "unit": "m",
                "description": "Длина одного стояка.",
            },
            _input("risers", "system.risers_count", "riser"),
        ],
        "outputs": [
            {"name": "total", "quantity": "pipe.total_length", "unit": "m", "description": "Итог."}
        ],
        "dimension_checks": [
            {"output": "total", "terms": [{"factors": [{"name": "length"}, {"name": "risers"}]}]}
        ],
        "formula": "L_общ = L × стояков",
        "explanation": "Длина одного стояка, умноженная на число стояков.",
        "implementation_key": "test.multiply_by_count.v1",
        "sources": [{"kind": "OTHER", "description": TEST_NOTE}],
    }
    content.update(overrides)
    return content


def reserve_rule(factor: str = "1.07", **overrides: Any) -> dict[str, Any]:
    content: dict[str, Any] = {
        "title": "Тест: тендерный запас длины",
        "description": "Тендерный запас множителем — синтетика ядра.",
        "rule_type": "TENDER_ASSUMPTION",
        "discipline": "VK",
        "applicability": APPLICABILITY,
        "inputs": [
            {
                "name": "base",
                "kind": "QUANTITY",
                "quantity": "pipe.total_length",
                "unit": "m",
                "description": "Длина без запаса.",
            }
        ],
        "parameters": [
            {"name": "factor", "value": factor, "description": "Тестовый множитель запаса."}
        ],
        "outputs": [
            {
                "name": "value",
                "quantity": "pipe.total_length",
                "unit": "m",
                "description": "С запасом.",
            }
        ],
        "dimension_checks": [
            {"output": "value", "terms": [{"factors": [{"name": "base"}, {"name": "factor"}]}]}
        ],
        "formula": "L_тс = L × k",
        "explanation": "Тендерный запас на отсутствие трасс.",
        "implementation_key": "test.reserve_factor.v1",
        "impact": "Длина больше на долю запаса.",
        "sources": [
            {
                "kind": "OWNER_DECISION",
                "decided_by": "Тестовый владелец",
                "decided_at": date(2026, 9, 28).isoformat(),
                "reference": "тестовый протокол",
                "basis": "Синтетика ядра.",
            }
        ],
    }
    content.update(overrides)
    return content


RULE_CONTENTS: dict[str, Any] = {
    "test.geometry.vertical_length": vertical_length_rule,
    "test.geometry.total_length": total_length_rule,
    "test.tender.length_reserve": reserve_rule,
}


def resolved(rule_key: str, content: dict[str, Any], version: int = 1) -> ResolvedRule:
    parsed = CalcRuleContent.model_validate(content)
    return ResolvedRule(
        rule_key=rule_key,
        rule_version_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{rule_key}@{version}"),
        version=version,
        status=CalcRuleStatus.APPROVED,
        rule_type=CalcRuleType(parsed.rule_type),
        content=parsed,
        content_sha256=content_sha256(parsed),
    )


def demo_rules(**contents: dict[str, Any]) -> dict[str, ResolvedRule]:
    return {
        key: resolved(key, contents.get(key.split(".")[-1], factory()))
        for key, factory in RULE_CONTENTS.items()
    }


def snapshot_item(
    fact_type: str, subject: CalcFactSubject, value: CalcFactValue
) -> CalcSnapshotItem:
    fact_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{fact_type}@{subject.key()}")
    return CalcSnapshotItem(
        fact_key=f"{fact_type}@{subject.key()}",
        fact_type=fact_type,
        subject=subject,
        fact_id=fact_id,
        fact_version=1,
        value=value,
        stated_value=value,
        method=CalcFactMethod.MANUAL,
        confidence=CalcConfidence.HIGH,
        review_status=CalcReviewStatus.CONFIRMED,
        resolution_state=CalcResolutionState.SINGLE,
        source_id=uuid.uuid5(uuid.NAMESPACE_URL, "source"),
        source_class=CalcSourceClass.MANUAL,
        claim_ids=[fact_id],
        evidence=[],
        calculation_eligible=True,
        item_sha256=canonical_sha256(
            {"fact_key": f"{fact_type}@{subject.key()}", "value": value.model_dump(mode="json")}
        ),
    )


def demo_facts(
    height: str = "3.3", floors: int = 24, risers: int = 2
) -> dict[str, CalcSnapshotItem]:
    items = [
        snapshot_item(
            "floor.height",
            CalcFactSubject(building="1", floor="2..24"),
            CalcNumberValue(value=height, unit="m"),
        ),
        snapshot_item(
            "building.floors_above_ground",
            CalcFactSubject(building="1"),
            CalcCountValue(value=floors),
        ),
        snapshot_item(
            "system.risers_count",
            CalcFactSubject(building="1", discipline="VK", system_code="В1"),
            CalcCountValue(value=risers),
        ),
    ]
    return {item.fact_key: item for item in items}
