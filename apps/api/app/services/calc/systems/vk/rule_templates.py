"""Содержание версии правила по заявке калькулятора — для инженера, тестов и контрольных примеров.

Шаблон повторяет контракт реализации: имена, единицы и величины входов, параметров, выходов.
Значения параметров и источники передаёт тот, кто создаёт версию: инженер — со ссылкой на
документ, тест — синтетику с пометкой «не инженерное основание». Шаблон ничего не утверждает.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.contracts.calc.enums import CalcRuleType
from app.contracts.calc.rules import CalcRuleContent
from app.services.calc.systems.vk.rule_needs import VkRuleNeed

SYNTHETIC_NOTE = "Синтетический пример для проверки реализации — не инженерное основание."


def rule_content(
    need: VkRuleNeed,
    parameters: Mapping[str, str],
    *,
    sources: Sequence[Mapping[str, object]] = (),
    rule_type: CalcRuleType | None = None,
    systems: Sequence[str] | None = None,
    impact: str | None = None,
    limitations: Sequence[str] = (),
) -> CalcRuleContent:
    """Версия правила по заявке. ValueError — нет реализации или не хватает параметра."""
    if need.implementation_key is None:
        raise ValueError(f"{need.rule_key}: методика не реализована — версию не создать")
    missing = [term.name for term in need.parameters if term.name not in parameters]
    if missing:
        raise ValueError(f"{need.rule_key}: не заданы параметры {', '.join(missing)}")
    return CalcRuleContent.model_validate(
        {
            "title": need.title,
            "description": f"{need.title}. Используется: {need.used_in}.",
            "rule_type": (rule_type or need.rule_types[0]).value,
            "discipline": "VK",
            "applicability": {
                "systems": list(systems or need.systems),
                "stages": ["P"],
                "scope": "Жилые здания, стадия П: оценка до РД.",
                "limitations": [
                    "Значения параметров — только из источника версии правила.",
                    *limitations,
                ],
            },
            "inputs": [
                {
                    "name": term.name,
                    "kind": "QUANTITY",
                    "quantity": term.quantity,
                    "unit": term.unit,
                    "description": term.meaning,
                }
                for term in need.inputs
            ],
            "parameters": [
                {
                    "name": term.name,
                    "value": parameters[term.name],
                    "unit": term.unit,
                    "description": term.meaning,
                }
                for term in need.parameters
            ],
            "outputs": [
                {
                    "name": term.name,
                    "quantity": term.quantity,
                    "unit": term.unit,
                    "description": term.meaning,
                }
                for term in need.outputs
            ],
            "formula": need.formula,
            "explanation": f"Без утверждённой версии: {need.blocks}.",
            "implementation_key": need.implementation_key,
            "sources": list(sources) or [{"kind": "OTHER", "description": SYNTHETIC_NOTE}],
            "impact": impact,
        }
    )
