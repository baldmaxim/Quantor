"""Детерминированный расчёт величины (промт 12).

Ожидаемые числа подобраны аналитически: страница 1000×1000 pt при коэффициенте 10 мм/pt
означает лист 10×10 метров, и все ответы получаются круглыми. Тест, сверяющийся с
собственным выводом, доказывает воспроизводимость, но не правильность.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain import GeometryType, MeasurementSource, QuantityUnit, VerificationState
from app.errors import DomainError
from app.models import Measurement, PageGeometry, ScaleCalibration
from app.services import quantity

# Квадратная страница 1000×1000 pt. Коэффициент 10 мм/pt делает её листом 10×10 метров:
# доли страницы переводятся в метры в уме, и ошибку в ожидании заметно сразу.
PAGE_SIDE = Decimal("1000.0000")
MM_PER_PT = Decimal("10.000000000000")
FINGERPRINT = "a" * 64


def _geometry(side: Decimal = PAGE_SIDE) -> PageGeometry:
    return PageGeometry(
        sheet_id=uuid.uuid4(),
        display_width_pt=side,
        display_height_pt=side,
        pdf_rotation=0,
        media_box=[],
        crop_box=[],
        parser_name="pypdf",
        parser_version="6.18.0",
        source_sha256="b" * 64,
        geometry_fingerprint=FINGERPRINT,
        extracted_at=datetime.now(UTC),
    )


def _calibration(factor: Decimal = MM_PER_PT) -> ScaleCalibration:
    return ScaleCalibration(
        id=uuid.uuid4(),
        sheet_id=uuid.uuid4(),
        point_a_x=Decimal("0"),
        point_a_y=Decimal("0"),
        point_b_x=Decimal("1"),
        point_b_y=Decimal("0"),
        input_value=Decimal("10000"),
        input_unit="mm",
        known_distance_mm=Decimal("10000"),
        page_distance_pt=Decimal("1000"),
        mm_per_pt=factor,
        page_geometry_fingerprint=FINGERPRINT,
        verification_state=VerificationState.UNVERIFIED,
    )


def _measurement(
    geometry_type: GeometryType,
    points: list[list[float]],
    *,
    calibration_id: uuid.UUID | None = None,
) -> Measurement:
    return Measurement(
        id=uuid.uuid4(),
        takeoff_item_id=uuid.uuid4(),
        sheet_id=uuid.uuid4(),
        geometry_type=geometry_type,
        points=points,
        source=MeasurementSource.MANUAL,
        scale_calibration_id=calibration_id,
        version=1,
    )


class TestCount:
    def test_count_is_one_piece(self) -> None:
        result = quantity.compute(
            _measurement(GeometryType.COUNT, [[0.5, 0.5]]), geometry=None, calibration=None
        )

        assert result.state is quantity.QuantityState.READY
        assert result.value == Decimal(1)
        assert result.unit is QuantityUnit.PCS
        assert result.rule_key == "count.v1"

    def test_count_works_without_scale(self) -> None:
        """Штука есть штука: масштаб ей не нужен и не запрашивается."""
        result = quantity.compute(
            _measurement(GeometryType.COUNT, [[0.1, 0.1]]),
            geometry=_geometry(),
            calibration=None,
        )

        assert result.state is quantity.QuantityState.READY
        assert result.scale_calibration_id is None


class TestLength:
    def test_horizontal_line_across_the_sheet(self) -> None:
        """Вся ширина листа 1000 pt при 10 мм/pt — ровно 10 метров."""
        result = quantity.compute(
            _measurement(GeometryType.LINE, [[0.0, 0.5], [1.0, 0.5]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert result.value == Decimal(10)
        assert result.canonical_value == Decimal(10000)
        assert result.canonical_unit == "mm"
        assert result.unit is QuantityUnit.M
        assert result.rule_key == "length.v1"

    def test_vertical_line_gives_the_same(self) -> None:
        """На квадратной странице вертикаль равна горизонтали. Проверка симметрии."""
        result = quantity.compute(
            _measurement(GeometryType.LINE, [[0.5, 0.0], [0.5, 1.0]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert result.value == Decimal(10)

    def test_diagonal_three_four_five(self) -> None:
        """Катеты 300 и 400 pt дают гипотенузу ровно 500 pt, то есть 5 метров."""
        result = quantity.compute(
            _measurement(GeometryType.LINE, [[0.0, 0.0], [0.3, 0.4]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert result.value == Decimal(5)

    def test_polyline_sums_its_segments(self) -> None:
        result = quantity.compute(
            _measurement(
                GeometryType.POLYLINE,
                [[0.0, 0.0], [0.3, 0.0], [0.3, 0.4], [0.0, 0.4]],
            ),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        # 300 + 400 + 300 = 1000 pt = 10 метров.
        assert result.value == Decimal(10)

    def test_rectangular_page_does_not_break_length(self) -> None:
        """Главная ловушка этапа: на прямоугольной странице оси не равнозначны.

        Отрезок в половину ширины и отрезок в половину высоты дают разные длины —
        и это правильно, потому что физически они разные.
        """
        page = PageGeometry(
            sheet_id=uuid.uuid4(),
            display_width_pt=Decimal("2000.0000"),
            display_height_pt=Decimal("1000.0000"),
            pdf_rotation=0,
            media_box=[],
            crop_box=[],
            parser_name="pypdf",
            parser_version="6.18.0",
            source_sha256="b" * 64,
            geometry_fingerprint=FINGERPRINT,
            extracted_at=datetime.now(UTC),
        )
        calibration = _calibration()

        horizontal = quantity.compute(
            _measurement(GeometryType.LINE, [[0.0, 0.5], [0.5, 0.5]]),
            geometry=page,
            calibration=calibration,
        )
        vertical = quantity.compute(
            _measurement(GeometryType.LINE, [[0.5, 0.0], [0.5, 0.5]]),
            geometry=page,
            calibration=calibration,
        )

        assert horizontal.value == Decimal(10)
        assert vertical.value == Decimal(5)


class TestArea:
    def test_full_sheet(self) -> None:
        """Лист 1000×1000 pt при 10 мм/pt — 10×10 метров, то есть 100 м²."""
        result = quantity.compute(
            _measurement(GeometryType.POLYGON, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert result.value == Decimal(100)
        assert result.canonical_value == Decimal(100_000_000)
        assert result.canonical_unit == "mm2"
        assert result.unit is QuantityUnit.M2
        assert result.rule_key == "area.v1"

    def test_quarter_sheet(self) -> None:
        result = quantity.compute(
            _measurement(GeometryType.POLYGON, [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert result.value == Decimal(25)

    def test_triangle_is_half_the_rectangle(self) -> None:
        result = quantity.compute(
            _measurement(GeometryType.POLYGON, [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert result.value == Decimal(50)

    def test_winding_direction_does_not_change_the_area(self) -> None:
        """Направление обхода задаёт знак, а площадь отрицательной не бывает."""
        clockwise = quantity.compute(
            _measurement(GeometryType.POLYGON, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )
        counter = quantity.compute(
            _measurement(GeometryType.POLYGON, [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0]]),
            geometry=_geometry(),
            calibration=_calibration(),
        )

        assert clockwise.value == counter.value


class TestUnavailable:
    def test_length_without_scale_is_unavailable_not_zero(self) -> None:
        """Ноль — это утверждение о величине, и ложное."""
        result = quantity.compute(
            _measurement(GeometryType.LINE, [[0.0, 0.0], [1.0, 0.0]]),
            geometry=_geometry(),
            calibration=None,
        )

        assert result.state is quantity.QuantityState.UNAVAILABLE_NO_SCALE
        assert result.value is None
        assert result.canonical_value is None
        # Правило всё равно названо: известно, чем считали бы.
        assert result.rule_key == "length.v1"

    def test_area_without_geometry_is_unavailable(self) -> None:
        result = quantity.compute(
            _measurement(GeometryType.POLYGON, [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]),
            geometry=None,
            calibration=_calibration(),
        )

        assert result.state is quantity.QuantityState.UNAVAILABLE_NO_GEOMETRY
        assert result.value is None


class TestProvenance:
    def test_result_carries_its_whole_chain(self) -> None:
        """Величину, которую нельзя объяснить цепочкой, показывать нельзя (ADR-0008)."""
        calibration = _calibration()
        result = quantity.compute(
            _measurement(
                GeometryType.LINE, [[0.0, 0.0], [1.0, 0.0]], calibration_id=calibration.id
            ),
            geometry=_geometry(),
            calibration=calibration,
        )

        assert result.measurement_id
        assert result.page_geometry_fingerprint == FINGERPRINT
        assert result.scale_calibration_id == str(calibration.id)
        assert result.rule_key == "length.v1"
        assert result.rule_version == "v1"
        assert len(result.input_fingerprint) == 64

    def test_same_input_gives_the_same_result(self) -> None:
        """Воспроизводимость: то же измерение даёт то же число и тот же отпечаток."""
        measurement = _measurement(GeometryType.LINE, [[0.1, 0.2], [0.7, 0.9]])
        geometry = _geometry()
        calibration = _calibration()

        first = quantity.compute(measurement, geometry=geometry, calibration=calibration)
        second = quantity.compute(measurement, geometry=geometry, calibration=calibration)

        assert first.value == second.value
        assert first.input_fingerprint == second.input_fingerprint

    def test_different_calibration_changes_the_fingerprint(self) -> None:
        """Другая калибровка — другая величина, и это обязано быть заметно."""
        measurement = _measurement(GeometryType.LINE, [[0.0, 0.0], [1.0, 0.0]])
        geometry = _geometry()

        first = quantity.compute(
            measurement, geometry=geometry, calibration=_calibration(Decimal("10"))
        )
        second = quantity.compute(
            measurement, geometry=geometry, calibration=_calibration(Decimal("20"))
        )

        assert first.value == Decimal(10)
        assert second.value == Decimal(20)
        assert first.input_fingerprint != second.input_fingerprint

    def test_moved_vertex_changes_the_fingerprint(self) -> None:
        geometry = _geometry()
        calibration = _calibration()

        first = quantity.compute(
            _measurement(GeometryType.LINE, [[0.0, 0.0], [1.0, 0.0]]),
            geometry=geometry,
            calibration=calibration,
        )
        second = quantity.compute(
            _measurement(GeometryType.LINE, [[0.0, 0.0], [0.5, 0.0]]),
            geometry=geometry,
            calibration=calibration,
        )

        assert first.input_fingerprint != second.input_fingerprint


class TestTotals:
    def test_sums_ready_results(self) -> None:
        geometry = _geometry()
        calibration = _calibration()
        results = [
            quantity.compute(
                _measurement(GeometryType.LINE, [[0.0, 0.0], [0.5, 0.0]]),
                geometry=geometry,
                calibration=calibration,
            ),
            quantity.compute(
                _measurement(GeometryType.LINE, [[0.0, 0.5], [0.3, 0.5]]),
                geometry=geometry,
                calibration=calibration,
            ),
        ]

        summary = quantity.total("item", results)

        # 5 + 3 метра.
        assert summary.value == Decimal(8)
        assert summary.measurement_count == 2
        assert summary.unavailable_count == 0

    def test_unavailable_are_counted_not_zeroed(self) -> None:
        """Итог, в котором половина измерений «стоила ноль», невозможно объяснить."""
        geometry = _geometry()
        results = [
            quantity.compute(
                _measurement(GeometryType.LINE, [[0.0, 0.0], [0.5, 0.0]]),
                geometry=geometry,
                calibration=_calibration(),
            ),
            quantity.compute(
                _measurement(GeometryType.LINE, [[0.0, 0.5], [0.3, 0.5]]),
                geometry=geometry,
                calibration=None,
            ),
        ]

        summary = quantity.total("item", results)

        assert summary.value == Decimal(5)
        assert summary.measurement_count == 1
        assert summary.unavailable_count == 1

    def test_incompatible_units_are_refused(self) -> None:
        """Штуки с метрами не складываются."""
        geometry = _geometry()
        results = [
            quantity.compute(
                _measurement(GeometryType.COUNT, [[0.5, 0.5]]), geometry=geometry, calibration=None
            ),
            quantity.compute(
                _measurement(GeometryType.LINE, [[0.0, 0.0], [0.5, 0.0]]),
                geometry=geometry,
                calibration=_calibration(),
            ),
        ]

        with pytest.raises(DomainError):
            quantity.total("item", results)

    def test_empty_total_is_refused(self) -> None:
        with pytest.raises(DomainError):
            quantity.total("item", [])

    def test_counts_add_up_as_pieces(self) -> None:
        results = [
            quantity.compute(
                _measurement(GeometryType.COUNT, [[0.1 * index, 0.5]]),
                geometry=_geometry(),
                calibration=None,
            )
            for index in range(7)
        ]

        summary = quantity.total("item", results)

        assert summary.value == Decimal(7)
        assert summary.unit is QuantityUnit.PCS


def test_rule_keys_are_stable() -> None:
    """Ключи правил — часть контракта: величина, посчитанная v1, обязана остаться объяснимой."""
    assert quantity.rule_for(GeometryType.COUNT) == "count.v1"
    assert quantity.rule_for(GeometryType.LINE) == "length.v1"
    assert quantity.rule_for(GeometryType.POLYLINE) == "length.v1"
    assert quantity.rule_for(GeometryType.POLYGON) == "area.v1"


def test_engine_never_reads_the_raster_sheet() -> None:
    """Растровые размеры в расчёте не участвуют — это пиксели распознавалки (ADR-0016).

    Проверяется не текст файла, а фактические обращения: движок не импортирует `Sheet`
    и не читает у него ничего. Поиск подстроки нашёл бы упоминание в комментарии и
    доказывал бы только наличие комментария.
    """
    import ast
    from pathlib import Path

    tree = ast.parse(Path(quantity.__file__).read_text(encoding="utf-8"))

    imported: set[str] = set()
    attributes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        if isinstance(node, ast.Attribute):
            attributes.add(node.attr)

    assert "Sheet" not in imported, "движок не должен знать про растровый лист"
    assert "width_px" not in attributes
    assert "height_px" not in attributes
    # А вот каноническая геометрия и калибровка читаются — это и есть источник величины.
    assert "display_width_pt" in attributes
    assert "mm_per_pt" in attributes
