"""Ядро преобразования координат.

Чистый модуль: ни базы, ни HTTP, ни состояния. Здесь живёт вся арифметика, из которой
потом получаются метры и квадратные метры, и именно поэтому она отделена — ошибка тут
проявляется как «портал считает не то», и найти её в перемешанном с вводом-выводом коде
почти невозможно.

## Два пространства

```text
нормализованное      x, y ∈ [0, 1] от левого верхнего угла отображённой страницы
                     ↕  умножение на размер страницы
точки PDF            x ∈ [0, display_width_pt], y ∈ [0, display_height_pt]
```

Поворот страницы **уже учтён** в `display_width_pt`/`display_height_pt` (ADR-0016), а
нормализованные координаты legacy-v1 относятся к уже повёрнутой странице (ADR-0008).
Поэтому перевод — умножение, без синусов и матриц. Попытка «доучесть поворот» здесь
повторила бы уже исправленный дефект, когда разметка разворачивалась поперёк чертежа.

## Числа

Внутри — `float`. Это единственный числовой тип, который Python и TypeScript разделяют
побитово: оба IEEE-754 binary64, и одинаковая последовательность операций даёт одинаковый
результат до последнего бита (ADR-0017).

Отсюда правило, которое важнее выбора типа: **порядок операций — часть контракта**. Сумма
длин звеньев накапливается слева направо, площадь обходит вершины по возрастанию индекса.
Переставить слагаемые «для красоты» нельзя: это меняет последние биты и ломает совпадение
с браузером, которое проверяется общими векторами на точное равенство.

Промежуточные значения не округляются. Округление — свойство отображения: длина, округлённая
на середине пути, превращается в накопленную ошибку в сумме по этажу.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from app.errors import DomainError, ErrorCode

__all__ = [
    "NormalizedPoint",
    "PageGeometryValue",
    "PdfDisplayPoint",
    "distance_pdf_points",
    "normalized_to_pdf_display",
    "pdf_display_to_normalized",
    "polygon_area_pdf_points2",
    "polyline_length_pdf_points",
]


@dataclass(frozen=True, slots=True)
class NormalizedPoint:
    """Точка в нормализованном пространстве листа: [0, 1] от левого верхнего угла."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PdfDisplayPoint:
    """Точка в точках PDF отображённой страницы, начало в левом верхнем углу."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PageGeometryValue:
    """Размер отображённой страницы в точках PDF.

    Отдельный тип, а не пара чисел: перепутать ширину с высотой на прямоугольной странице
    слишком легко, а результат такой ошибки — правдоподобное, но неверное число.
    """

    display_width_pt: float
    display_height_pt: float

    @classmethod
    def from_decimal(cls, width: Decimal | float, height: Decimal | float) -> PageGeometryValue:
        """Граница «десятичное → float» (ADR-0017).

        Единственное место, где значение из базы становится числом с плавающей точкой.
        Дальше по коду геометрия — это float, и обратно не превращается.
        """
        value = cls(display_width_pt=float(width), display_height_pt=float(height))
        _require_page(value)
        return value


def _require_finite(value: float, what: str) -> float:
    if not math.isfinite(value):
        raise DomainError(ErrorCode.VALIDATION_FAILED, f"{what}: ожидается конечное число")
    return value


def _require_page(geometry: PageGeometryValue) -> None:
    """Страница обязана быть положительной: на её размер делят."""
    _require_finite(geometry.display_width_pt, "ширина страницы")
    _require_finite(geometry.display_height_pt, "высота страницы")
    if geometry.display_width_pt <= 0 or geometry.display_height_pt <= 0:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Размер страницы должен быть положительным",
        )


def _require_normalized(point: NormalizedPoint) -> None:
    """Границы 0 и 1 допустимы: угол листа — законная точка, а не ошибка ввода."""
    _require_finite(point.x, "x")
    _require_finite(point.y, "y")
    if not (0.0 <= point.x <= 1.0) or not (0.0 <= point.y <= 1.0):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Нормализованная точка вне листа: ({point.x}, {point.y})",
        )


def normalized_to_pdf_display(
    point: NormalizedPoint, geometry: PageGeometryValue
) -> PdfDisplayPoint:
    """Нормализованная точка → точка PDF.

    Умножение и ничего больше: поворот уже в размерах страницы.
    """
    _require_page(geometry)
    _require_normalized(point)
    return PdfDisplayPoint(
        x=point.x * geometry.display_width_pt,
        y=point.y * geometry.display_height_pt,
    )


def pdf_display_to_normalized(
    point: PdfDisplayPoint, geometry: PageGeometryValue
) -> NormalizedPoint:
    """Точка PDF → нормализованная точка.

    Обратное преобразование не зажимает результат в [0, 1]: точка за пределами страницы —
    это ошибка вызывающего, и молча подвинуть её к краю значило бы получить правдоподобную
    геометрию вместо явного отказа.
    """
    _require_page(geometry)
    _require_finite(point.x, "x")
    _require_finite(point.y, "y")
    return NormalizedPoint(
        x=point.x / geometry.display_width_pt,
        y=point.y / geometry.display_height_pt,
    )


def distance_pdf_points(first: PdfDisplayPoint, second: PdfDisplayPoint) -> float:
    """Расстояние между точками в точках PDF.

    `math.hypot`, а не корень из суммы квадратов вручную: он не переполняется на больших
    значениях и корректно округляется. В JavaScript ему соответствует `Math.hypot`.
    """
    _require_finite(first.x, "x")
    _require_finite(first.y, "y")
    _require_finite(second.x, "x")
    _require_finite(second.y, "y")
    return math.hypot(second.x - first.x, second.y - first.y)


def polyline_length_pdf_points(points: list[NormalizedPoint], geometry: PageGeometryValue) -> float:
    """Длина ломаной в точках PDF.

    Считать длину в нормализованном пространстве нельзя: на прямоугольной странице шаг 0,1
    по X и 0,1 по Y — разные расстояния. Поэтому точки сначала переводятся, и только потом
    измеряются.

    Сумма накапливается слева направо. Порядок — часть контракта (ADR-0017).
    """
    if len(points) < 2:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Для длины нужно минимум две точки, передано {len(points)}",
        )

    projected = [normalized_to_pdf_display(point, geometry) for point in points]

    total = 0.0
    for index in range(1, len(projected)):
        total += distance_pdf_points(projected[index - 1], projected[index])
    return total


def polygon_area_pdf_points2(points: list[NormalizedPoint], geometry: PageGeometryValue) -> float:
    """Площадь многоугольника в квадратных точках PDF, формула шнурков.

    Обход вершин по возрастанию индекса с замыканием последней на нулевую; порядок — часть
    контракта. Результат берётся по модулю: направление обхода задаёт знак, а площадь
    отрицательной не бывает.

    Самопересечения не проверяются и не запрещаются: формула шнурков на них даёт разность
    площадей, а не отказ. Политика для таких фигур — вопрос правил подсчёта, а не
    преобразования координат, и решается там (промт 12).
    """
    if len(points) < 3:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Для площади нужно минимум три точки, передано {len(points)}",
        )

    projected = [normalized_to_pdf_display(point, geometry) for point in points]

    total = 0.0
    count = len(projected)
    for index in range(count):
        current = projected[index]
        following = projected[(index + 1) % count]
        total += current.x * following.y - following.x * current.y
    return abs(total) / 2.0
