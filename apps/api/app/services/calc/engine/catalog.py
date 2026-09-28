"""Статические каталоги ядра: обработчики и калькуляторы из кода приложения.

Демонстрационные калькуляторы (PROMPT 04–05) скрыты из пользовательского списка; рабочие
калькуляторы ВК стадии П (PROMPT 06) и реализации их правил — в `systems/vk`. Примитивы живут в
своём реестре (`primitives.py`) и реализацией правила не бывают.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.services.calc.engine import calculators, handlers
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.demo import DEMO_CALCULATOR, DEMO_HANDLERS
from app.services.calc.engine.demo_structure import RISER_DEMAND_CALCULATOR, STRUCTURE_HANDLERS
from app.services.calc.engine.handlers import HandlerSpec
from app.services.calc.systems.vk.handlers import VK_HANDLERS
from app.services.calc.systems.vk.spec import VK_SPECS
from app.services.calc.systems.vk.steps import calculator_for

HANDLERS: Final[MappingProxyType[str, HandlerSpec]] = handlers.build_registry(
    (*DEMO_HANDLERS, *STRUCTURE_HANDLERS, *VK_HANDLERS)
)
CALCULATORS: Final[MappingProxyType[tuple[str, int], CalculatorDef]] = calculators.build_registry(
    (DEMO_CALCULATOR, RISER_DEMAND_CALCULATOR, *(calculator_for(spec) for spec in VK_SPECS))
)
