"""Проверки реестра правил — чистые функции без базы.

Два уровня:

- **содержание** проверяется при каждом сохранении черновика: типы фактов существуют, единицы
  есть в каталоге и совместимы с типами фактов, размерности выходов сходятся, ВОР Заказчика не
  назван основанием, ссылки на старый портал существуют;
- **утверждение** требует основания по типу правила: норматив — документа с редакцией и пунктом,
  правило производителя — документа производителя той же линейки, инженерное — методики,
  тендерное допущение — решения ответственного лица и описанного влияния на результат. Код
  старого портала основанием не бывает, а по каждой его известной опасности проверяющий
  записывает итог и комментарий; подтверждённая и не устранённая опасность утверждение
  блокирует.

«Разрешено в расчёте» вычисляется из статуса и дат действия — пользователь его не задаёт.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date
from typing import Final

from app.contracts.calc.enums import (
    CalcHazardOutcome,
    CalcLegacyAction,
    CalcRuleInputKind,
    CalcRuleSourceKind,
    CalcRuleStatus,
    CalcRuleType,
    CalcValueKind,
)
from app.contracts.calc.fact_types import fact_type_def
from app.contracts.calc.rules import (
    TENDER_NOTICE,
    CalcDecisionSource,
    CalcEngineeringSource,
    CalcLegacySource,
    CalcManufacturerSource,
    CalcNormativeSource,
    CalcOtherSource,
    CalcRuleApprove,
    CalcRuleContent,
    CalcRuleSource,
)
from app.contracts.calc.units import UnitError, compatible, unit_def
from app.services.calc.rules.dimensions import DimensionError, check
from app.services.calc.rules.legacy import LegacyCatalog

_NUMERIC: Final = frozenset({CalcValueKind.NUMBER, CalcValueKind.COUNT, CalcValueKind.RANGE})
# ВОР Заказчика — объект сверки: ни количество, ни диаметр из него не становятся правилом.
_CUSTOMER_VOR: Final = re.compile(
    r"(?<![А-Яа-яA-Za-z])ВОР(?![А-Яа-яA-Za-z])|ведомост\w*\s+объ[её]м", re.I
)


def content_sha256(content: CalcRuleContent) -> str:
    """Отпечаток содержания версии: по нему запуск докажет, какой редакцией пользовался."""
    canonical = json.dumps(
        content.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calculation_eligible(status: CalcRuleStatus, content: CalcRuleContent, on: date) -> bool:
    """Может ли версия участвовать в новом расчёте. Только утверждённая и действующая на дату."""
    if status is not CalcRuleStatus.APPROVED:
        return False
    if content.valid_from is not None and on < content.valid_from:
        return False
    return content.valid_to is None or on <= content.valid_to


def notice(rule_type: CalcRuleType) -> str | None:
    return TENDER_NOTICE if rule_type is CalcRuleType.TENDER_ASSUMPTION else None


def source_label(source: CalcRuleSource) -> str:
    """Источник одной строкой для списков."""
    match source:
        case CalcNormativeSource():
            return f"{source.designation}, {source.clause} ({source.edition})"
        case CalcManufacturerSource():
            return f"{source.manufacturer} {source.product_line}: {source.document_title}"
        case CalcEngineeringSource():
            return f"методика: {source.title}"
        case CalcDecisionSource():
            return f"решение: {source.decided_by}, {source.decided_at.isoformat()}"
        case CalcLegacySource():
            return "старый портал: " + ", ".join(source.legacy_ids)
        case CalcOtherSource():
            return source.description[:120]


def _basis_texts(content: CalcRuleContent) -> Iterable[str]:
    """Тексты, в которых записано основание: источники, происхождение констант, влияние."""
    for source in content.sources:
        for value in source.model_dump(mode="json").values():
            if isinstance(value, str):
                yield value
    for parameter in content.parameters:
        yield parameter.description
    if content.impact is not None:
        yield content.impact


def _unit_problem(unit: str | None, where: str) -> str | None:
    if unit is None:
        return None
    try:
        unit_def(unit)
    except UnitError:
        return f"{where}: неизвестная единица «{unit}»"
    return None


def content_problems(content: CalcRuleContent, legacy: LegacyCatalog) -> list[str]:
    """Ошибки содержания версии. Пустой список — черновик можно сохранить."""
    problems: list[str] = []
    units: dict[str, str | None] = {}
    numeric: set[str] = set()

    for item in content.inputs:
        units[item.name] = item.unit
        if (problem := _unit_problem(item.unit, f"вход «{item.name}»")) is not None:
            problems.append(problem)
            continue
        if item.kind is CalcRuleInputKind.QUANTITY:
            numeric.add(item.name)
            continue
        definition = fact_type_def(item.fact_type or "")
        if definition is None:
            problems.append(f"вход «{item.name}»: неизвестный тип факта «{item.fact_type}»")
            continue
        if definition.value_kind not in _NUMERIC:
            if item.unit is not None:
                problems.append(f"вход «{item.name}»: у факта «{definition.key}» нет единицы")
            continue
        numeric.add(item.name)
        if (
            item.unit is None
            or definition.unit is None
            or not compatible(item.unit, definition.unit)
        ):
            problems.append(
                f"вход «{item.name}»: единица «{item.unit}» не совместима с «{definition.unit}» "
                f"факта «{definition.key}»"
            )

    for group, title in ((content.parameters, "параметр"), (content.outputs, "выход")):
        for element in group:
            units[element.name] = element.unit
            numeric.add(element.name)
            if (problem := _unit_problem(element.unit, f"{title} «{element.name}»")) is not None:
                problems.append(problem)

    outputs = {item.name for item in content.outputs}
    for dimension_check in content.dimension_checks:
        if dimension_check.output not in outputs:
            problems.append(
                f"проверка размерности ссылается не на выход: «{dimension_check.output}»"
            )
            continue
        for term in dimension_check.terms:
            for factor in term.factors:
                if factor.name in units and factor.name not in numeric:
                    problems.append(f"множитель «{factor.name}» не числовой")
        try:
            problems.extend(check(dimension_check, units))
        except DimensionError as error:
            problems.append(str(error))

    if any(_CUSTOMER_VOR.search(text) for text in _basis_texts(content)):
        problems.append(
            "ВОР Заказчика не может быть основанием правила, константы или резерва: "
            "он объект сверки"
        )
    for source in content.sources:
        if isinstance(source, CalcLegacySource):
            missing = [item for item in source.legacy_ids if legacy.get(item) is None]
            if missing:
                problems.append("нет в каталоге старого портала: " + ", ".join(missing))
            outside = [
                entry.legacy_id
                for item in source.legacy_ids
                if (entry := legacy.get(item)) is not None
                and CalcLegacyAction.OUT_OF_SCOPE in entry.actions
            ]
            if outside:
                problems.append(
                    "правила старого портала вне расчётного контура (цены, НДС, импорт счетов): "
                    + ", ".join(outside)
                )
    return problems


def _kinds(content: CalcRuleContent) -> set[CalcRuleSourceKind]:
    return {CalcRuleSourceKind(source.kind) for source in content.sources}


def approval_problems(
    content: CalcRuleContent, payload: CalcRuleApprove, legacy: LegacyCatalog
) -> list[str]:
    """Чего не хватает для утверждения. Пустой список — версию можно утвердить."""
    problems = list(content_problems(content, legacy))
    kinds = _kinds(content)
    if content.implementation_key is None:
        problems.append("не указана детерминированная реализация (implementation_key)")
    if not kinds - {CalcRuleSourceKind.LEGACY_CODE}:
        problems.append("нет основания: код старого портала — происхождение, а не основание")

    match content.rule_type:
        case CalcRuleType.NORMATIVE:
            if CalcRuleSourceKind.NORMATIVE_DOCUMENT not in kinds:
                problems.append(
                    "нормативное правило без нормативного документа: обозначение, редакция, "
                    "пункт и дата обязательны — «по СП» не источник"
                )
        case CalcRuleType.MANUFACTURER:
            documents = [s for s in content.sources if isinstance(s, CalcManufacturerSource)]
            scope = content.applicability
            if not documents:
                problems.append("правило производителя без документа производителя")
            elif scope.manufacturer is None or scope.product_line is None:
                problems.append("в области применения не указаны производитель и линейка")
            elif not any(
                doc.manufacturer.casefold() == scope.manufacturer.casefold()
                and doc.product_line.casefold() == scope.product_line.casefold()
                for doc in documents
            ):
                problems.append(
                    "документ другого производителя или линейки: правило не переносится"
                )
        case CalcRuleType.ENGINEERING:
            if CalcRuleSourceKind.ENGINEERING_METHOD not in kinds:
                problems.append(
                    "инженерное правило без методики: неизвестное происхождение остаётся в "
                    "карантине старых правил"
                )
            if not content.applicability.limitations:
                problems.append("у инженерного правила не названы ограничения")
        case CalcRuleType.TENDER_ASSUMPTION:
            if not kinds & {
                CalcRuleSourceKind.OWNER_DECISION,
                CalcRuleSourceKind.REVIEWER_DECISION,
            }:
                problems.append("тендерное допущение без решения ответственного лица")
            if content.impact is None:
                problems.append("у тендерного допущения не описано влияние на результат")
            if not content.applicability.limitations:
                problems.append("у тендерного допущения не названы ограничения")
        case CalcRuleType.PHYSICS | CalcRuleType.GEOMETRY:
            pass

    problems.extend(_legacy_problems(content, payload, legacy))
    return problems


def legacy_ids(content: CalcRuleContent) -> list[str]:
    """Правила старого портала, от которых версия происходит, в порядке упоминания."""
    found: list[str] = []
    for source in content.sources:
        if isinstance(source, CalcLegacySource):
            found.extend(item for item in source.legacy_ids if item not in found)
    return found


def _legacy_problems(
    content: CalcRuleContent, payload: CalcRuleApprove, legacy: LegacyCatalog
) -> list[str]:
    """Каждое правило старого портала разобрано, по каждой его опасности есть итог."""
    referenced = legacy_ids(content)
    reviews = {item.legacy_id: item for item in payload.legacy_review}
    problems: list[str] = []
    for legacy_id in referenced:
        entry = legacy.get(legacy_id)
        review = reviews.get(legacy_id)
        if entry is None:
            continue
        if review is None:
            problems.append(f"{legacy_id}: нет разбора правила старого портала")
            continue
        outcomes = {item.hazard: item.outcome for item in review.hazards}
        missed = [hazard.value for hazard in entry.hazards if hazard not in outcomes]
        if missed:
            problems.append(f"{legacy_id}: нет решения по опасностям: {', '.join(missed)}")
        confirmed = [
            hazard.value
            for hazard, outcome in outcomes.items()
            if outcome is CalcHazardOutcome.REJECTED
        ]
        if confirmed:
            problems.append(
                f"{legacy_id}: опасность подтверждена и не устранена ({', '.join(confirmed)}) — "
                "версию не утверждают, а отклоняют или исправляют новой версией"
            )
    extra = sorted(set(reviews) - set(referenced))
    if extra:
        problems.append("разбор правил, на которые версия не ссылается: " + ", ".join(extra))
    return problems
