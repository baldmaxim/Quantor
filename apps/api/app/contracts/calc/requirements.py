"""Требования расчёта к исходным данным (ADR-0030, PROMPT 02).

Требование — декларация калькулятора, а не хранимая сущность: живёт в коде рядом с ним
(каталог ВК — `services/calc/systems/vk/requirements.py`) и версионируется вместе с ним.
Таблицы нет: пользователь требования не редактирует, а новая версия калькулятора приносит
свой каталог.

Уровень необходимости — не уверенность. REQUIRED говорит, что без значения расчёт системы не
выполняется; насколько надёжно найденное значение, говорит уверенность утверждения.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.contracts.calc.enums import (
    CalcAssumptionPolicy,
    CalcDiscipline,
    CalcRequirementGroup,
    CalcRequirementLevel,
    CalcRequirementScope,
    CalcSourceClass,
)


@dataclass(frozen=True, slots=True)
class CalcSystemDef:
    """Инженерная система каталога: раздел и обозначение."""

    discipline: CalcDiscipline
    code: str
    title: str


@dataclass(frozen=True, slots=True)
class CalcInputRequirement:
    """Одно исходное данное, которое понадобится калькулятору.

    Для требований с областью SYSTEM место факта берёт обозначение той системы, для которой
    строится матрица: «материал трубопроводов» для В1 — это `system.pipe_material` системы В1.
    """

    id: str
    title: str
    group: CalcRequirementGroup
    fact_type: str
    scope: CalcRequirementScope
    level: CalcRequirementLevel
    assumption: CalcAssumptionPolicy
    description: str
    """Зачем данное расчёту — одной-двумя фразами инженера."""
    systems: tuple[str, ...]
    """Для каких систем каталога требование действует."""
    derivable_from: tuple[str, ...] = ()
    """Типы фактов, из которых значение выведет правило расчёта (PROMPT 03–04)."""
    expected_sources: tuple[CalcSourceClass, ...] = ()
    """Где такое значение обычно бывает."""
    manual_when_sources_absent: bool = False
    """Если в проекте нет ни одного документа ожидаемых классов — нужен ручной ввод."""


class CalcSystemRead(BaseModel):
    discipline: CalcDiscipline
    code: str
    title: str


class CalcRequirementRead(BaseModel):
    id: str
    title: str
    group: CalcRequirementGroup
    fact_type: str
    fact_type_title: str
    scope: CalcRequirementScope
    level: CalcRequirementLevel
    assumption: CalcAssumptionPolicy
    description: str
    systems: list[str]
    derivable_from: list[str]
    expected_sources: list[CalcSourceClass]


class CalcRequirementCatalogRead(BaseModel):
    """Каталог требований калькулятора с его версией."""

    version: str
    discipline: CalcDiscipline
    systems: list[CalcSystemRead]
    requirements: list[CalcRequirementRead]
