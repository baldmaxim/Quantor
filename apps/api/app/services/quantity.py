"""Детерминированный расчёт величины: count / length / area.

Первый настоящий QTO-расчёт в проекте. Правило имеет ключ и версию, и результат обязан
воспроизводиться: то же измерение с той же геометрией и той же калибровкой даёт то же
число сегодня, завтра и после перезапуска.

```text
count.v1   COUNT   → 1 шт, калибровка не нужна
length.v1  LINE, POLYLINE → нормализованные → точки PDF → мм → м
area.v1    POLYGON        → нормализованные → точки PDF² → мм² → м²
```

## Чего здесь не происходит

- расчёт **никогда** не идёт в нормализованном пространстве: на прямоугольной странице
  0,1 по X и 0,1 по Y — разные расстояния (ADR-0018);
- масштаб не выводится из размера страницы и не угадывается;
- `Sheet.width_px` не участвует: это пиксели растра распознавалки (ADR-0016);
- коэффициент от клиента не принимается;
- промежуточные значения не округляются — округление это последний слой (ADR-0017).

Без калибровки длина и площадь **недоступны**, а не равны нулю. Ноль — это утверждение
о величине, и ложное.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from app.domain import GeometryType, QuantityUnit
from app.errors import DomainError, ErrorCode
from app.models import Measurement, PageGeometry, ScaleCalibration
from app.services.geometry.transform import (
    NormalizedPoint,
    PageGeometryValue,
    polygon_area_pdf_points2,
    polyline_length_pdf_points,
)

# Ключи правил. Версия в ключе, а не рядом: величина, посчитанная правилом v1, обязана
# оставаться объяснимой после появления v2.
RULE_COUNT: Final = "count.v1"
RULE_LENGTH: Final = "length.v1"
RULE_AREA: Final = "area.v1"

RULE_BY_GEOMETRY: Final[dict[GeometryType, str]] = {
    GeometryType.COUNT: RULE_COUNT,
    GeometryType.LINE: RULE_LENGTH,
    GeometryType.POLYLINE: RULE_LENGTH,
    GeometryType.POLYGON: RULE_AREA,
}

# Канонические единицы хранения результата. Внутренний канон — миллиметр (ADR-0018);
# метры появляются только в показе.
MM_PER_M: Final = Decimal("1000")
MM2_PER_M2: Final = Decimal("1000000")


class QuantityState(StrEnum):
    """Состояние величины.

    `unavailable` — не ошибка и не ноль: геометрия есть, а основания для перевода в метры
    нет. Показать вместо этого ноль значило бы соврать в смете.
    """

    READY = "ready"
    UNAVAILABLE_NO_SCALE = "unavailable_no_scale"
    UNAVAILABLE_NO_GEOMETRY = "unavailable_no_geometry"


@dataclass(frozen=True, slots=True)
class QuantityResult:
    """Величина вместе со всем, что нужно, чтобы её воспроизвести.

    Цепочка происхождения замкнута: измерение → лист → геометрия с отпечатком → калибровка
    → правило с версией. Величину, которую нельзя объяснить этой цепочкой, показывать
    нельзя (ADR-0008).
    """

    measurement_id: str
    state: QuantityState

    # Показ: метры и квадратные метры.
    value: Decimal | None
    unit: QuantityUnit

    # Канон: миллиметры. Хранится рядом, потому что перевод в метры — это отображение,
    # а не расчёт, и обратный пересчёт из округлённых метров уже не даст исходного.
    canonical_value: Decimal | None
    canonical_unit: str

    rule_key: str
    rule_version: str

    page_geometry_fingerprint: str | None
    scale_calibration_id: str | None
    # Отпечаток входа: геометрия плюс коэффициент. Два одинаковых отпечатка обязаны
    # давать одно число — на этом и держится воспроизводимость.
    input_fingerprint: str
    verification_state: str


def rule_for(geometry_type: GeometryType) -> str:
    return RULE_BY_GEOMETRY[geometry_type]


def _version_of(rule_key: str) -> str:
    return rule_key.rsplit(".", 1)[-1]


def _points(measurement: Measurement) -> list[NormalizedPoint]:
    return [NormalizedPoint(float(x), float(y)) for x, y in measurement.points]


def _fingerprint(
    measurement: Measurement,
    geometry: PageGeometry | None,
    calibration: ScaleCalibration | None,
    rule_key: str,
) -> str:
    """Отпечаток входа расчёта.

    Включает всё, от чего зависит число: геометрию, размер страницы, коэффициент и правило.
    Изменилось что угодно из этого — отпечаток другой, и величина обязана это показывать,
    а не выглядеть той же самой.
    """
    parts = [
        rule_key,
        measurement.geometry_type.value,
        ";".join(f"{x!r},{y!r}" for x, y in measurement.points),
        geometry.geometry_fingerprint if geometry is not None else "-",
        str(calibration.mm_per_pt) if calibration is not None else "-",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def compute(
    measurement: Measurement,
    *,
    geometry: PageGeometry | None,
    calibration: ScaleCalibration | None,
) -> QuantityResult:
    """Считает величину измерения.

    Ничего не читает из базы и ничего не пишет: вход передан целиком. Отсюда и
    воспроизводимость — функция не зависит ни от порядка запросов, ни от состояния сессии.
    """
    rule_key = rule_for(measurement.geometry_type)
    version = _version_of(rule_key)
    fingerprint = _fingerprint(measurement, geometry, calibration, rule_key)
    unit = _unit_for(measurement.geometry_type)

    def unavailable(state: QuantityState) -> QuantityResult:
        return QuantityResult(
            measurement_id=str(measurement.id),
            state=state,
            value=None,
            unit=unit,
            canonical_value=None,
            canonical_unit=_canonical_unit_for(measurement.geometry_type),
            rule_key=rule_key,
            rule_version=version,
            page_geometry_fingerprint=(
                geometry.geometry_fingerprint if geometry is not None else None
            ),
            scale_calibration_id=(str(calibration.id) if calibration is not None else None),
            input_fingerprint=fingerprint,
            verification_state=(
                calibration.verification_state.value if calibration is not None else "unverified"
            ),
        )

    # Счёт не требует ни масштаба, ни геометрии страницы: штука есть штука.
    if measurement.geometry_type is GeometryType.COUNT:
        return QuantityResult(
            measurement_id=str(measurement.id),
            state=QuantityState.READY,
            value=Decimal(1),
            unit=QuantityUnit.PCS,
            canonical_value=Decimal(1),
            canonical_unit="pcs",
            rule_key=rule_key,
            rule_version=version,
            page_geometry_fingerprint=(
                geometry.geometry_fingerprint if geometry is not None else None
            ),
            scale_calibration_id=None,
            input_fingerprint=fingerprint,
            verification_state="unverified",
        )

    if geometry is None:
        return unavailable(QuantityState.UNAVAILABLE_NO_GEOMETRY)
    if calibration is None:
        return unavailable(QuantityState.UNAVAILABLE_NO_SCALE)

    page = PageGeometryValue.from_decimal(geometry.display_width_pt, geometry.display_height_pt)
    points = _points(measurement)
    factor = calibration.mm_per_pt

    if measurement.geometry_type is GeometryType.POLYGON:
        # Площадь: сначала в точках PDF в квадрате, затем коэффициент в квадрате.
        area_pt2 = polygon_area_pdf_points2(points, page)
        canonical = _to_decimal(area_pt2) * factor * factor
        display = canonical / MM2_PER_M2
        canonical_unit = "mm2"
    else:
        length_pt = polyline_length_pdf_points(points, page)
        canonical = _to_decimal(length_pt) * factor
        display = canonical / MM_PER_M
        canonical_unit = "mm"

    return QuantityResult(
        measurement_id=str(measurement.id),
        state=QuantityState.READY,
        value=display,
        unit=unit,
        canonical_value=canonical,
        canonical_unit=canonical_unit,
        rule_key=rule_key,
        rule_version=version,
        page_geometry_fingerprint=geometry.geometry_fingerprint,
        scale_calibration_id=str(calibration.id),
        input_fingerprint=fingerprint,
        verification_state=calibration.verification_state.value,
    )


def _to_decimal(value: float) -> Decimal:
    """Граница «float → Decimal» после геометрии (ADR-0017).

    `repr` даёт кратчайшую запись, читающуюся обратно в тот же double, поэтому переход
    не теряет и не выдумывает разрядов.
    """
    return Decimal(repr(value))


def _unit_for(geometry_type: GeometryType) -> QuantityUnit:
    if geometry_type is GeometryType.COUNT:
        return QuantityUnit.PCS
    if geometry_type is GeometryType.POLYGON:
        return QuantityUnit.M2
    return QuantityUnit.M


def _canonical_unit_for(geometry_type: GeometryType) -> str:
    if geometry_type is GeometryType.COUNT:
        return "pcs"
    if geometry_type is GeometryType.POLYGON:
        return "mm2"
    return "mm"


@dataclass(frozen=True, slots=True)
class QuantityTotal:
    """Итог по строке обмера в явно указанной области.

    Область обязательна: сложить измерения двух ревизий одного документа значило бы
    посчитать одни и те же двери дважды (ADR-0019).
    """

    takeoff_item_id: str
    unit: QuantityUnit
    canonical_unit: str
    value: Decimal
    canonical_value: Decimal
    rule_key: str
    measurement_count: int
    # Сколько измерений не попало в итог: у них нет масштаба или геометрии. Прятать их
    # нельзя — итог по половине измерений выглядит как полный.
    unavailable_count: int


def total(item_id: str, results: list[QuantityResult]) -> QuantityTotal:
    """Складывает совместимые величины.

    Складываются только готовые: недоступные учитываются отдельным счётчиком, а не
    молчаливо считаются нулями. Итог, в котором половина измерений «стоила ноль»,
    невозможно ни заметить, ни объяснить.
    """
    if not results:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Нечего суммировать")

    units = {result.unit for result in results}
    if len(units) > 1:
        # Штуки с метрами не складываются. Это ловится и типом строки, но здесь дешевле
        # отказать явно, чем получить бессмысленное число.
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Несовместимые единицы в одной строке: {sorted(unit.value for unit in units)}",
        )

    ready = [result for result in results if result.state is QuantityState.READY]
    canonical = sum(
        (result.canonical_value for result in ready if result.canonical_value is not None),
        Decimal(0),
    )

    first = results[0]
    divisor = (
        Decimal(1)
        if first.canonical_unit == "pcs"
        else MM2_PER_M2
        if first.canonical_unit == "mm2"
        else MM_PER_M
    )

    return QuantityTotal(
        takeoff_item_id=item_id,
        unit=first.unit,
        canonical_unit=first.canonical_unit,
        value=canonical / divisor,
        canonical_value=canonical,
        rule_key=first.rule_key,
        measurement_count=len(ready),
        unavailable_count=len(results) - len(ready),
    )
