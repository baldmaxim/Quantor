"""Контракт будущей области подсчёта объёмов.

Здесь только типы и правила. Таблиц для них на Stage 1 нет и быть не должно: пока нет
реальных расчётов, любая схема окажется неверной, а мигрировать пустые таблицы бессмысленно.

Главное, что фиксируется, — разделение трёх понятий (ADR-0008):

```text
Region       что увидела распознавалка — свидетельство
Measurement  геометрия, созданная для подсчёта — намерение человека или ИИ
Quantity     детерминированно вычисленная величина с указанием правила
```

Смешать их — самая дорогая ошибка в таком продукте: тогда исправление разметки молча меняет
посчитанный объём, и защитить результат перед заказчиком становится нечем.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GeometryType(StrEnum):
    """Что именно измеряют."""

    COUNT = "count"
    LINE = "line"
    POLYLINE = "polyline"
    POLYGON = "polygon"


class MeasurementSource(StrEnum):
    """Кто создал геометрию. Влияет на порядок проверки, а не на саму величину."""

    MANUAL = "manual"
    AI = "ai"
    IMPORTED = "imported"


class ScaleSource(StrEnum):
    """Откуда взялся масштаб чертежа."""

    MANUAL = "manual"
    DETECTED_DIMENSION = "detected_dimension"
    IMPORTED = "imported"


class VerificationState(StrEnum):
    """Состояние проверки величины человеком."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISPUTED = "disputed"


@dataclass(frozen=True, slots=True)
class ScaleCalibration:
    """Масштаб листа.

    Определять масштаб автоматически портал сейчас не умеет, и интерфейс честно пишет
    «Не задан». Тип объявлен заранее, чтобы измерения сразу проектировались с оглядкой
    на калибровку, а не пересчитывались потом.
    """

    sheet_id: str
    # Сколько единиц реального мира приходится на единицу нормализованных координат.
    units_per_normalized: float
    unit: str
    source: ScaleSource
    confidence: float | None = None
    # Точки, по которым построена калибровка: без них проверить масштаб невозможно.
    validation_points: tuple[tuple[float, float], ...] = ()
    verified: bool = False


@dataclass(frozen=True, slots=True)
class Measurement:
    """Геометрия, созданная для подсчёта.

    Хранится в том же нормализованном пространстве, что и Region, но это другая сущность:
    Region нельзя превратить в Measurement, из него можно только создать новый объект.
    """

    sheet_id: str
    geometry_type: GeometryType
    points: tuple[tuple[float, float], ...]
    source: MeasurementSource
    # Ссылка на область-свидетельство, если геометрия построена по ней.
    evidence_region_id: str | None = None
    scale_calibration_id: str | None = None
    confidence: float | None = None
    group_id: str | None = None


@dataclass(frozen=True, slots=True)
class QuantityItem:
    """Вычисленная величина.

    Считается детерминированным сервисом по правилу с версией. Модель величину не считает
    никогда: результат обязан воспроизводиться при повторном расчёте.
    """

    category: str
    value: float
    unit: str
    rule_version: str
    measurement_ids: tuple[str, ...]
    evidence_region_ids: tuple[str, ...] = ()
    verification: VerificationState = VerificationState.UNVERIFIED


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    """Замечание проверки: расхождение, которое человек должен посмотреть."""

    quantity_id: str
    code: str
    message: str
    severity: str = "warning"
