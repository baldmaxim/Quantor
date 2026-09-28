"""Разделы паспорта из запусков: исходные данные, расчёт, сверки, структура. Чистые функции."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from app.contracts.calc.engine import CalcRunRead, CalcSnapshotItem
from app.contracts.calc.enums import CalcBlockCode, CalcCompleteness, CalcReadinessStatus
from app.contracts.calc.fact_types import fact_type_def
from app.contracts.calc.passport import (
    CalcAmount,
    CalcExpectedQuantityBody,
    CalcPassportCheck,
    CalcPassportConflict,
    CalcPassportElement,
    CalcPassportFact,
    CalcPassportMissing,
    CalcPassportResult,
)
from app.contracts.calc.readiness import CalcReadinessRowRead, CalcSystemReadinessRead
from app.contracts.calc.synthesis import CalcSystemGraph
from app.contracts.calc.units import UNITS
from app.contracts.calc.values import (
    CalcBooleanValue,
    CalcCountValue,
    CalcEnumValue,
    CalcFactValue,
    CalcNumberValue,
    CalcRangeValue,
    CalcTextValue,
)
from app.services.calc.engine.numbers import parse_exact, ru_number

FACT_ISSUES: Final[Mapping[str, tuple[str, ...]]] = {
    "building.floors_above_ground": ("step:structure_floors",),
    "floor.apartments_count": ("step:structure_floors",),
    "floor.height": ("step:structure_vertical",),
    "floor.elevation": ("step:structure_vertical",),
    "system.risers_count": ("risers.count",),
    "system.zones_count": ("zones",),
    "system.main_length": ("main.route",),
    "system.main_diameter": ("fact:system.main_diameter",),
    "system.riser_diameter": ("fact:system.riser_diameter",),
    "system.inlets_count": ("source",),
    "system.hot_water_source": ("source",),
    "system.outlets_count": ("source",),
    "system.pump_station_present": ("pump_station",),
    "building.fixtures_count": ("drain_points",),
    "floor.bathrooms_count": ("drain_points",),
    "floor.kitchens_count": ("drain_points",),
    "system.function": ("semantics",),
    "floor.shafts_count": ("risers.placement",),
}
_LAYERS: Final = {"structure": "B", "demand": "A", "quantity": "D", "tender": "T", "check": "C"}
_CONFLICTS: Final = frozenset({CalcBlockCode.FACT_CONFLICT, CalcBlockCode.FACT_DECISION_STALE})


def value_text(value: CalcFactValue) -> str:
    """Значение факта для человека: «3,3 м», «24 эт.», «ИТП», «да»."""
    match value:
        case CalcNumberValue():
            return f"{ru_number(parse_exact(value.value))} {_unit(value.unit)}".rstrip()
        case CalcCountValue():
            return f"{value.value} {_unit(value.unit)}".rstrip()
        case CalcRangeValue():
            return f"{value.low or '…'}–{value.high or '…'} {_unit(value.unit)}".rstrip()
        case CalcBooleanValue():
            return "да" if value.value else "нет"
        case CalcEnumValue() | CalcTextValue():
            return value.value


def _unit(code: str | None) -> str:
    return "" if code is None or code not in UNITS else UNITS[code].title


def fact_title(item: CalcSnapshotItem) -> str:
    definition = fact_type_def(item.fact_type)
    title = item.fact_type if definition is None else definition.title
    subject = item.subject
    where = ", ".join(
        part
        for part in (
            f"корп. {subject.building}" if subject.building else None,
            f"секц. {subject.section}" if subject.section else None,
            f"эт. {subject.floor}" if subject.floor else None,
            subject.qualifier,
        )
        if part
    )
    return f"{title} ({where})" if where else title


def used_facts(snapshots: Iterable[Sequence[CalcSnapshotItem]]) -> list[CalcPassportFact]:
    seen: dict[str, CalcPassportFact] = {}
    for items in snapshots:
        for item in items:
            seen.setdefault(
                item.fact_key,
                CalcPassportFact(
                    fact_key=item.fact_key,
                    title=fact_title(item),
                    value=value_text(item.value),
                    source=item.source_class.value,
                    method=item.method.value,
                ),
            )
    return [seen[key] for key in sorted(seen)]


def blocks_of(
    keys: Iterable[str], rows: Sequence[CalcExpectedQuantityBody]
) -> tuple[list[str], list[str]]:
    """Какие позиции не определены из-за этих ключей и какие определены несмотря на них."""
    wanted = set(keys)
    blocked = [row.title for row in rows if wanted & set(row.blocked_by)]
    determined = [
        row.title
        for row in rows
        if not wanted & set(row.blocked_by) and row.completeness is not CalcCompleteness.BLOCKED
    ]
    return list(dict.fromkeys(blocked)), list(dict.fromkeys(determined))


def missing(
    system: CalcSystemReadinessRead | None, rows: Sequence[CalcExpectedQuantityBody]
) -> list[CalcPassportMissing]:
    found: list[CalcPassportMissing] = []
    for row in [] if system is None else system.rows:
        if row.status in (CalcReadinessStatus.FOUND, CalcReadinessStatus.DERIVABLE):
            continue
        blocks, not_blocks = blocks_of(FACT_ISSUES.get(row.fact_type, ()), rows)
        found.append(
            CalcPassportMissing(
                requirement_id=row.requirement_id,
                title=row.title,
                level=row.level,
                status=row.status,
                reason=row.reason,
                blocks=blocks,
                not_blocks=not_blocks if blocks else [],
            )
        )
    return found


def conflicts(
    system: CalcSystemReadinessRead | None, calculation: CalcRunRead | None
) -> list[CalcPassportConflict]:
    found: dict[str, CalcPassportConflict] = {}
    rows: list[CalcReadinessRowRead] = [] if system is None else system.rows
    for row in rows:
        if row.status is CalcReadinessStatus.CONFLICTED:
            for value in row.values:
                found.setdefault(
                    value.fact_key,
                    CalcPassportConflict(fact_key=value.fact_key, message=row.reason or row.title),
                )
    for reason in [] if calculation is None else calculation.blocking_reasons:
        if reason.code in _CONFLICTS and reason.fact_key is not None:
            found.setdefault(
                reason.fact_key,
                CalcPassportConflict(fact_key=reason.fact_key, message=reason.message),
            )
    return [found[key] for key in sorted(found)]


def calculation(run: CalcRunRead | None) -> list[CalcPassportResult]:
    if run is None:
        return []
    steps = {step.step_key: step for step in run.steps}
    return [
        CalcPassportResult(
            key=result.result_key,
            title=result.title,
            layer=_LAYERS.get(result.result_key.split(".", 1)[0], "B"),
            amount=CalcAmount(value=result.value),
            unit=result.unit,
            explanation=steps[result.step_key].explanation if result.step_key in steps else "",
        )
        for result in run.results
    ]


def _result_text(run: CalcRunRead | None, key: str) -> str | None:
    if run is None:
        return None
    found = next((item for item in run.results if item.result_key == key), None)
    return None if found is None else ru_number(parse_exact(found.value))


def checks(
    run: CalcRunRead | None, system: CalcSystemReadinessRead | None, scoped_to_section: bool
) -> list[CalcPassportCheck]:
    """Документальное значение и контроль — раздельно, расхождение видно, замены нет."""
    found: list[CalcPassportCheck] = []
    snapshot = [] if run is None else run.snapshot.items
    documented = next(
        (item for item in snapshot if item.fact_type == "building.apartments_total"), None
    )
    computed = _result_text(run, "structure.apartments_total")
    discrepancy = _result_text(run, "check.apartments_discrepancy")
    found.append(
        CalcPassportCheck(
            title="Итог квартир: документ и квартирография этажей",
            document_value=None if documented is None else value_text(documented.value),
            check_value=computed,
            discrepancy=discrepancy,
            status="не выполнена: нет итога документа или квартирографии"
            if discrepancy is None
            else "итог корпуса против квартирографии секции — сравнение справочное"
            if scoped_to_section
            else "совпадает"
            if discrepancy == "0"
            else "расхождение — документальное значение не заменено",
        )
    )
    for row in [] if system is None else system.rows:
        if row.fact_type.startswith("system.flow_") and row.values:
            value = row.values[0].value
            found.append(
                CalcPassportCheck(
                    title=f"{row.title}: документ и контрольный расчёт",
                    document_value=None if value is None else value_text(value),
                    check_value=None,
                    discrepancy=None,
                    status="контрольный расчёт не выполнен: методика "
                    "vk.water.demand.flow_check не реализована и не утверждена",
                )
            )
    return found


def structure(graph: CalcSystemGraph | None) -> list[CalcPassportElement]:
    if graph is None:
        return []
    items: list[CalcPassportElement] = []
    for node in graph.nodes:
        cardinality = node.cardinality
        count = (
            str(cardinality.min)
            if cardinality.min == cardinality.max
            else f"{cardinality.min}–{cardinality.max} — не выбрано"
        )
        if node.multiplicity > 1:
            count += f" ×{node.multiplicity}"
        items.append(
            CalcPassportElement(
                element_id=node.id, title=node.title, provenance=node.provenance, count=count
            )
        )
    return items
