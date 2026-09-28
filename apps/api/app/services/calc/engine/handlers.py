"""Реестр обработчиков: `implementation_key` → проверенная функция Python.

Реестр статический — собирается из кода при импорте. Кода из базы, `eval`, `exec` и загрузки
модулей по имени здесь нет: ключ правила ищется в словаре, и только.

Обработчик:

- получает неизменяемые входы и параметры (`HandlerContext`) в канонических единицах своей
  размерности — базы, запроса, сессии он не видит и ничего не пишет;
- возвращает выходы в объявленных единицах и детерминированное пояснение;
- объявляет контракт (имена и единицы входов, параметров, выходов) и контрольные примеры.

Версия реализации — часть ключа (`….v1`, шаблон ключа закреплён реестром правил): семантика
ключа не меняется никогда, новый алгоритм — новый ключ и новая версия правила. Отпечаток
семантики — хеш контракта и контрольных примеров; запуск запоминает его, и повтор старого
запуска честно отказывает, если под тем же ключом стал другой алгоритм.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import localcontext
from types import MappingProxyType

from app.contracts.calc.rules import IMPLEMENTATION_KEY_PATTERN
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.numbers import ENGINE_CONTEXT, exact_text, parse_exact
from app.services.calc.engine.quantity import Quantity, is_working_unit

_KEY = re.compile(IMPLEMENTATION_KEY_PATTERN)


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """Всё, что видит обработчик: входы и параметры версии правила. Больше ничего."""

    inputs: Mapping[str, Quantity]
    parameters: Mapping[str, Quantity]


@dataclass(frozen=True, slots=True)
class HandlerResult:
    outputs: Mapping[str, Quantity]
    explanation: str
    """Пояснение для человека, собранное из чисел шага: «3,3 м × 24 эт. = 79,2 м»."""


HandlerFn = Callable[[HandlerContext], HandlerResult]


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """Контрольный пример: входы и параметры строками → ожидаемые выходы строками."""

    inputs: Mapping[str, str]
    parameters: Mapping[str, str]
    outputs: Mapping[str, str]


@dataclass(frozen=True)
class HandlerSpec:
    implementation_key: str
    title: str
    inputs: Mapping[str, str | None]
    """Имя входа → рабочая единица (каноническая или счётчик)."""
    parameters: Mapping[str, str | None]
    outputs: Mapping[str, str | None]
    compute: HandlerFn = field(repr=False)
    golden: tuple[GoldenCase, ...]

    def contract(self) -> dict[str, object]:
        return {
            "implementation_key": self.implementation_key,
            "inputs": dict(sorted(self.inputs.items())),
            "parameters": dict(sorted(self.parameters.items())),
            "outputs": dict(sorted(self.outputs.items())),
        }

    @property
    def semantics_sha256(self) -> str:
        """Отпечаток семантики: контракт и контрольные примеры, без текста кода."""
        return canonical_sha256(
            {
                "contract": self.contract(),
                "golden": [
                    {
                        "inputs": dict(sorted(case.inputs.items())),
                        "parameters": dict(sorted(case.parameters.items())),
                        "outputs": dict(sorted(case.outputs.items())),
                    }
                    for case in self.golden
                ],
            }
        )


def run_handler(spec: HandlerSpec, context: HandlerContext) -> HandlerResult:
    """Исполняет обработчик в контексте без скрытого округления."""
    with localcontext(ENGINE_CONTEXT):
        return spec.compute(context)


def check_golden(spec: HandlerSpec) -> list[str]:
    """Прогон контрольных примеров. Пустой список — реализация соответствует своей семантике."""
    problems: list[str] = []
    for number, case in enumerate(spec.golden, start=1):
        context = HandlerContext(
            inputs=MappingProxyType(
                {
                    name: Quantity.of(parse_exact(value), spec.inputs[name])
                    for name, value in case.inputs.items()
                }
            ),
            parameters=MappingProxyType(
                {
                    name: Quantity.of(parse_exact(value), spec.parameters[name])
                    for name, value in case.parameters.items()
                }
            ),
        )
        result = run_handler(spec, context)
        for name, expected in case.outputs.items():
            actual = result.outputs[name].in_unit(spec.outputs[name])
            if actual != parse_exact(expected):
                problems.append(
                    f"{spec.implementation_key}: пример {number}, «{name}» = {exact_text(actual)}, "
                    f"ожидалось {expected}"
                )
    return problems


def _check_spec(spec: HandlerSpec) -> list[str]:
    problems: list[str] = []
    if not _KEY.match(spec.implementation_key):
        problems.append(f"ключ «{spec.implementation_key}» не по шаблону реестра правил")
    for group in (spec.inputs, spec.parameters, spec.outputs):
        for name, unit in group.items():
            if not is_working_unit(unit):
                problems.append(
                    f"{spec.implementation_key}: «{name}» не в рабочей единице ({unit})"
                )
    if not spec.outputs:
        problems.append(f"{spec.implementation_key}: нет выходов")
    if not spec.golden:
        problems.append(f"{spec.implementation_key}: нет контрольных примеров")
    return problems


def build_registry(specs: Iterable[HandlerSpec]) -> MappingProxyType[str, HandlerSpec]:
    """Статический реестр. Ошибка в объявлении — ошибка импорта, а не расчёта."""
    registry: dict[str, HandlerSpec] = {}
    for spec in specs:
        if spec.implementation_key in registry:
            raise ValueError(f"обработчик {spec.implementation_key} объявлен дважды")
        problems = _check_spec(spec)
        if problems:
            raise ValueError("; ".join(problems))
        registry[spec.implementation_key] = spec
    return MappingProxyType(registry)
