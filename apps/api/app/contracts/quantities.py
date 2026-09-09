"""Контракт будущей области подсчёта объёмов.

Здесь только типы и правила. Таблиц для них на Stage 1 нет и быть не должно: пока нет
реальных расчётов, любая схема окажется неверной, а мигрировать пустые таблицы бессмысленно.

Перечисления отсюда переехали в `app/domain.py`: они перестали быть заготовкой и стали
рабочими типами. `ScaleCalibration` отменён — старый `units_per_normalized` был математически
неверен на прямоугольной странице, и его заменила настоящая модель (ADR-0018).

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

from app.domain import GeometryType, MeasurementSource, VerificationState


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
