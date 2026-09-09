"""Ядро преобразования координат (ADR-0016, ADR-0017).

Общие векторы `tests/fixtures/coordinate_vectors.json` читают и эти тесты, и тесты
просмотрщика в `apps/web`. Сравнение точное, без допуска: допуск скрыл бы расхождение
двух реализаций — ровно то, ради чего векторы и заведены.

Ожидаемые значения в файле подобраны аналитически, а не сняты с реализации. Тест,
сверяющийся с собственным выводом, доказывает воспроизводимость, но не правильность.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.errors import DomainError, ErrorCode
from app.services.geometry.transform import (
    NormalizedPoint,
    PageGeometryValue,
    PdfDisplayPoint,
    distance_pdf_points,
    normalized_to_pdf_display,
    pdf_display_to_normalized,
    polygon_area_pdf_points2,
    polyline_length_pdf_points,
)

VECTORS_PATH = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "coordinate_vectors.json"
)


def _vectors() -> dict[str, Any]:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


VECTORS = _vectors()
PAGES = {name: PageGeometryValue(**value) for name, value in VECTORS["pages"].items()}


def _points(raw: list[list[float]]) -> list[NormalizedPoint]:
    return [NormalizedPoint(x=item[0], y=item[1]) for item in raw]


def _case_id(case: dict[str, Any]) -> str:
    return case["name"]


class TestSharedVectors:
    """Те же входы и те же ожидания, что у тестов просмотрщика."""

    def test_fixture_is_reachable(self) -> None:
        """Файл общий: если он переехал, молча разойтись реализациям нельзя."""
        assert VECTORS_PATH.exists(), f"нет файла общих векторов: {VECTORS_PATH}"
        assert VECTORS["version"] == 1

    @pytest.mark.parametrize("case", VECTORS["to_pdf"], ids=_case_id)
    def test_normalized_to_pdf(self, case: dict[str, Any]) -> None:
        point = NormalizedPoint(x=case["point"][0], y=case["point"][1])

        result = normalized_to_pdf_display(point, PAGES[case["page"]])

        assert [result.x, result.y] == case["expected"]

    @pytest.mark.parametrize("case", VECTORS["roundtrip"], ids=lambda c: f"{c['page']}{c['point']}")
    def test_roundtrip_returns_the_same_point(self, case: dict[str, Any]) -> None:
        """Туда и обратно — то же самое число, а не «примерно»."""
        geometry = PAGES[case["page"]]
        source = NormalizedPoint(x=case["point"][0], y=case["point"][1])

        back = pdf_display_to_normalized(normalized_to_pdf_display(source, geometry), geometry)

        assert (back.x, back.y) == (source.x, source.y)

    @pytest.mark.parametrize("case", VECTORS["length"], ids=_case_id)
    def test_polyline_length(self, case: dict[str, Any]) -> None:
        result = polyline_length_pdf_points(_points(case["points"]), PAGES[case["page"]])

        assert result == case["expected_pt"]

    @pytest.mark.parametrize("case", VECTORS["area"], ids=_case_id)
    def test_polygon_area(self, case: dict[str, Any]) -> None:
        result = polygon_area_pdf_points2(_points(case["points"]), PAGES[case["page"]])

        assert result == case["expected_pt2"]


class TestRectangularPageTrap:
    """Главная ловушка этапа: считать длину в нормализованном пространстве нельзя."""

    def test_equal_normalized_steps_are_different_distances(self) -> None:
        """0,1 по X и 0,1 по Y — разные расстояния, если стороны листа разные.

        Это и есть причина, по которой старый `units_per_normalized` был неверен.
        """
        page = PageGeometryValue(display_width_pt=3000.0, display_height_pt=4000.0)

        horizontal = polyline_length_pdf_points(
            [NormalizedPoint(0.0, 0.0), NormalizedPoint(0.1, 0.0)], page
        )
        vertical = polyline_length_pdf_points(
            [NormalizedPoint(0.0, 0.0), NormalizedPoint(0.0, 0.1)], page
        )

        assert horizontal == 300.0
        assert vertical == 400.0
        assert horizontal != vertical


class TestBoundary:
    """Граница «десятичное → float» (ADR-0017)."""

    def test_decimal_geometry_becomes_float(self) -> None:
        page = PageGeometryValue.from_decimal(Decimal("595.2760"), Decimal("841.8900"))

        assert isinstance(page.display_width_pt, float)
        assert page.display_width_pt == 595.276
        assert page.display_height_pt == 841.89

    def test_zero_sized_page_is_refused_at_the_boundary(self) -> None:
        """На размер страницы делят: ноль обязан отказать здесь, а не дать бесконечность."""
        with pytest.raises(DomainError) as error:
            PageGeometryValue.from_decimal(Decimal("0"), Decimal("100"))

        assert error.value.code is ErrorCode.VALIDATION_FAILED


class TestValidation:
    """Неверный вход — явный отказ, а не правдоподобное число."""

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_coordinate_is_refused(self, value: float) -> None:
        page = PageGeometryValue(display_width_pt=1000.0, display_height_pt=1000.0)

        with pytest.raises(DomainError):
            normalized_to_pdf_display(NormalizedPoint(value, 0.5), page)

    @pytest.mark.parametrize("point", [(-0.001, 0.5), (1.001, 0.5), (0.5, -1.0), (0.5, 2.0)])
    def test_point_outside_the_sheet_is_refused(self, point: tuple[float, float]) -> None:
        page = PageGeometryValue(display_width_pt=1000.0, display_height_pt=1000.0)

        with pytest.raises(DomainError):
            normalized_to_pdf_display(NormalizedPoint(*point), page)

    @pytest.mark.parametrize("edge", [(0.0, 0.0), (1.0, 1.0), (0.0, 1.0), (1.0, 0.0)])
    def test_sheet_corners_are_allowed(self, edge: tuple[float, float]) -> None:
        """Угол листа — законная точка. Отвергать её значило бы запретить обмер по краю."""
        page = PageGeometryValue(display_width_pt=1000.0, display_height_pt=1000.0)

        result = normalized_to_pdf_display(NormalizedPoint(*edge), page)

        assert result.x in (0.0, 1000.0)

    @pytest.mark.parametrize("count", [0, 1])
    def test_length_needs_two_points(self, count: int) -> None:
        page = PageGeometryValue(display_width_pt=1000.0, display_height_pt=1000.0)
        points = [NormalizedPoint(0.1, 0.1)] * count

        with pytest.raises(DomainError):
            polyline_length_pdf_points(points, page)

    @pytest.mark.parametrize("count", [0, 1, 2])
    def test_area_needs_three_points(self, count: int) -> None:
        page = PageGeometryValue(display_width_pt=1000.0, display_height_pt=1000.0)
        points = [NormalizedPoint(0.1, 0.1)] * count

        with pytest.raises(DomainError):
            polygon_area_pdf_points2(points, page)

    def test_negative_page_is_refused(self) -> None:
        page = PageGeometryValue(display_width_pt=-1.0, display_height_pt=100.0)

        with pytest.raises(DomainError):
            normalized_to_pdf_display(NormalizedPoint(0.5, 0.5), page)

    def test_reverse_transform_does_not_clamp(self) -> None:
        """Точка за пределами страницы остаётся за пределами: подвинуть её молча нельзя."""
        page = PageGeometryValue(display_width_pt=1000.0, display_height_pt=1000.0)

        result = pdf_display_to_normalized(PdfDisplayPoint(1500.0, -200.0), page)

        assert result.x == 1.5
        assert result.y == -0.2


class TestDistance:
    def test_distance_is_symmetric(self) -> None:
        first = PdfDisplayPoint(10.0, 20.0)
        second = PdfDisplayPoint(310.0, 420.0)

        assert distance_pdf_points(first, second) == distance_pdf_points(second, first)

    def test_distance_of_a_point_to_itself_is_zero(self) -> None:
        point = PdfDisplayPoint(123.456, 789.012)

        assert distance_pdf_points(point, point) == 0.0

    def test_large_coordinates_do_not_overflow(self) -> None:
        """`hypot` работает там, где корень из суммы квадратов уже переполняется.

        Наивная формула на этих числах даёт `OverflowError`: 3e200 в квадрате выходит за
        предел double. Значение сверяется с тем же, что даёт `Math.hypot` в JavaScript, —
        побитово тем же, и это лучшее подтверждение ADR-0017, чем любое рассуждение.
        """
        import math

        with pytest.raises(OverflowError):
            math.sqrt(3e200**2 + 4e200**2)

        first = PdfDisplayPoint(0.0, 0.0)
        second = PdfDisplayPoint(3e200, 4e200)

        # Не ровно 5e200: ни один из аргументов точно не представим в double.
        assert distance_pdf_points(first, second) == 4.9999999999999995e200
