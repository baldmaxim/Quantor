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
from decimal import Decimal, localcontext
from types import MappingProxyType

from app.contracts.calc.engine import CalcRoundingPolicy
from app.contracts.calc.rules import IMPLEMENTATION_KEY_PATTERN
from app.services.calc.engine.hashing import canonical_sha256
from app.services.calc.engine.numbers import ENGINE_CONTEXT, exact_text, parse_exact
from app.services.calc.engine.quantity import Quantity, is_working_unit

_KEY = re.compile(IMPLEMENTATION_KEY_PATTERN)


@dataclass(frozen=True, slots=True)
class SeriesMember:
    """Член набора: код места («2..24») и значение в рабочей единице набора."""

    member: str
    value: Quantity


@dataclass(frozen=True, slots=True)
class HandlerContext:
    """Всё, что видит обработчик: входы и параметры версии правила. Больше ничего."""

    inputs: Mapping[str, Quantity]
    parameters: Mapping[str, Quantity]
    series: Mapping[str, tuple[SeriesMember, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """Наборы — только у примитивов; члены упорядочены по коду места."""


class InsufficientInputError(Exception):
    """Данных набора недостаточно, чтобы выполнить шаг: пробел или перекрытие этажей.

    Не ошибка программы: шаг не определён, причина записывается в запуск.
    """


@dataclass(frozen=True, slots=True)
class HandlerRounding:
    """Округление внутри обработчика, которого требует правило: видно в шаге, а не спрятано."""

    target: str
    before: Decimal
    after: Decimal
    unit: str | None
    policy: CalcRoundingPolicy
    reason: str


@dataclass(frozen=True, slots=True)
class HandlerResult:
    outputs: Mapping[str, Quantity]
    explanation: str
    """Пояснение для человека, собранное из чисел шага: «3,3 м × 24 эт. = 79,2 м»."""
    roundings: tuple[HandlerRounding, ...] = ()


HandlerFn = Callable[[HandlerContext], HandlerResult]


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """Контрольный пример: входы и параметры строками → ожидаемые выходы строками."""

    inputs: Mapping[str, str]
    parameters: Mapping[str, str]
    outputs: Mapping[str, str]
    series: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    """Наборы примера: имя → код места → значение."""


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
    series: Mapping[str, str | None] = field(default_factory=dict)
    """Наборы: имя → рабочая единица членов. Только у примитивов."""

    def contract(self) -> dict[str, object]:
        contract: dict[str, object] = {
            "implementation_key": self.implementation_key,
            "inputs": dict(sorted(self.inputs.items())),
            "parameters": dict(sorted(self.parameters.items())),
            "outputs": dict(sorted(self.outputs.items())),
        }
        if self.series:
            contract["series"] = dict(sorted(self.series.items()))
        return contract

    @property
    def semantics_sha256(self) -> str:
        """Отпечаток семантики: контракт и контрольные примеры, без текста кода."""
        return canonical_sha256(
            {
                "contract": self.contract(),
                "golden": [_golden_canonical(case) for case in self.golden],
            }
        )


def _golden_canonical(case: GoldenCase) -> dict[str, object]:
    canonical: dict[str, object] = {
        "inputs": dict(sorted(case.inputs.items())),
        "parameters": dict(sorted(case.parameters.items())),
        "outputs": dict(sorted(case.outputs.items())),
    }
    if case.series:
        canonical["series"] = {
            name: dict(sorted(members.items())) for name, members in sorted(case.series.items())
        }
    return canonical


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
            series=MappingProxyType(
                {
                    name: tuple(
                        SeriesMember(member, Quantity.of(parse_exact(value), spec.series[name]))
                        for member, value in sorted(members.items())
                    )
                    for name, members in case.series.items()
                }
            ),
        )
        try:
            result = run_handler(spec, context)
        except InsufficientInputError as error:
            if case.outputs:
                problems.append(f"{spec.implementation_key}: пример {number}: {error}")
            continue
        if not case.outputs:
            problems.append(
                f"{spec.implementation_key}: пример {number} должен был не определиться"
            )
            continue
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
    for group in (spec.inputs, spec.parameters, spec.outputs, spec.series):
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
