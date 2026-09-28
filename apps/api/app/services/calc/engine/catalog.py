"""Статические каталоги ядра: обработчики и калькуляторы из кода приложения.

Сейчас в них только демонстрационные калькуляторы и обработчики (PROMPT 04–05), в том числе
обработчики правил синтеза структуры. Реальные калькуляторы ВК появятся кодом так же.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.services.calc.engine import calculators, handlers
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.demo import DEMO_CALCULATOR, DEMO_HANDLERS
from app.services.calc.engine.demo_structure import RISER_DEMAND_CALCULATOR, STRUCTURE_HANDLERS
from app.services.calc.engine.handlers import HandlerSpec

HANDLERS: Final[MappingProxyType[str, HandlerSpec]] = handlers.build_registry(
    (*DEMO_HANDLERS, *STRUCTURE_HANDLERS)
)
CALCULATORS: Final[MappingProxyType[tuple[str, int], CalculatorDef]] = calculators.build_registry(
    (DEMO_CALCULATOR, RISER_DEMAND_CALCULATOR)
)
