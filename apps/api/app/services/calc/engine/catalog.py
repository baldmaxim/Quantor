"""Статические каталоги ядра: обработчики и калькуляторы из кода приложения.

Сейчас в них только демонстрационный калькулятор и его обработчики (PROMPT 04). Реальные
калькуляторы ВК появятся в PROMPT 05–06 — так же, кодом.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.services.calc.engine import calculators, handlers
from app.services.calc.engine.calculators import CalculatorDef
from app.services.calc.engine.demo import DEMO_CALCULATOR, DEMO_HANDLERS
from app.services.calc.engine.handlers import HandlerSpec

HANDLERS: Final[MappingProxyType[str, HandlerSpec]] = handlers.build_registry(DEMO_HANDLERS)
CALCULATORS: Final[MappingProxyType[tuple[str, int], CalculatorDef]] = calculators.build_registry(
    (DEMO_CALCULATOR,)
)
