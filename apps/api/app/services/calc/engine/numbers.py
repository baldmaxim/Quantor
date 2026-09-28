"""Числа ядра: Decimal без скрытого округления.

Обработчик считает в контексте, где неточная операция — ошибка: деление с бесконечной дробью
или потеря знаков не превращаются молча в «примерно так». Округление — только явное, по
политике (`CalcRoundingPolicy`), и каждое записывается в цепочку расчёта.
"""

from __future__ import annotations

from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)
from typing import Final

from app.contracts.calc.engine import CalcRoundingPolicy
from app.contracts.calc.enums import CalcRoundingMode
from app.contracts.calc.values import decimal_text, parse_decimal

# 40 значащих цифр — с запасом для инженерных величин; неточная операция — исключение.
ENGINE_CONTEXT: Final = Context(
    prec=40,
    rounding=ROUND_HALF_EVEN,
    traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
)
# Контекст явного округления: здесь потеря знаков — и есть цель операции.
_ROUNDING_CONTEXT: Final = Context(
    prec=40, rounding=ROUND_HALF_EVEN, traps=[InvalidOperation, DivisionByZero, Overflow]
)
_MODES: Final = {
    CalcRoundingMode.HALF_UP: ROUND_HALF_UP,
    CalcRoundingMode.CEILING: ROUND_CEILING,
    CalcRoundingMode.FLOOR: ROUND_FLOOR,
}


def exact_text(value: Decimal) -> str:
    """Точная запись без экспоненты и хвостовых нулей."""
    return decimal_text(value)


def parse_exact(text: str) -> Decimal:
    return parse_decimal(text)


def apply_rounding(value: Decimal, policy: CalcRoundingPolicy) -> Decimal:
    quantum = parse_decimal(policy.quantum)
    if quantum <= 0:
        raise ValueError("шаг округления должен быть положительным")
    return value.quantize(quantum, rounding=_MODES[policy.mode], context=_ROUNDING_CONTEXT)


def ru_number(value: Decimal) -> str:
    """Число для человека: «79,2». Только отображение — значение не меняется."""
    return exact_text(value).replace(".", ",")
