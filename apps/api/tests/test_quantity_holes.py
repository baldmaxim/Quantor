"""Площадь с отверстиями и недействительный контур в движке величин (промт 05, ADR-0026).

Страница 1000×1000 pt при 10 мм/pt — лист 10×10 м: доли страницы переводятся в метры в уме,
и ожидания аналитические, а не снятые с вывода.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.domain import (
    GeometryIssueCode,
    GeometryType,
    MeasurementSource,
    QuantityState,
    VerificationState,
)
from app.models import Measurement, PageGeometry, ScaleCalibration
from app.services import quantity

FINGERPRINT = "a" * 64
MM_PER_PT = Decimal("10.000000000000")
OUTER = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]  # 8×8 м = 64 м²
HOLE_A = [[0.2, 0.2], [0.4, 0.2], [0.4, 0.4], [0.2, 0.4]]  # 2×2 м = 4 м²
HOLE_B = [[0.5, 0.5], [0.8, 0.5], [0.8, 0.8]]  # треугольник 3×3/2 = 4,5 м²


def _geometry() -> PageGeometry:
    return PageGeometry(
        sheet_id=uuid.uuid4(),
        display_width_pt=Decimal("1000.0000"),
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


def _calibration() -> ScaleCalibration:
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
        mm_per_pt=MM_PER_PT,
        page_geometry_fingerprint=FINGERPRINT,
        verification_state=VerificationState.UNVERIFIED,
    )


def _polygon(
    points: list[list[float]], holes: list[list[list[float]]] | None = None
) -> Measurement:
    return Measurement(
        id=uuid.uuid4(),
        takeoff_item_id=uuid.uuid4(),
        sheet_id=uuid.uuid4(),
        geometry_type=GeometryType.POLYGON,
        points=points,
        holes=holes if holes is not None else [],
        source=MeasurementSource.MANUAL,
        version=1,
    )


def _ready(measurement: Measurement) -> quantity.QuantityResult:
    return quantity.compute(measurement, geometry=_geometry(), calibration=_calibration())


class TestAreaWithoutHoles:
    def test_rule_and_fingerprint_are_unchanged(self) -> None:
        # Отпечаток прежней формулы, собранный здесь вручную: появление отверстий не должно
        # сдвинуть ни одно уже выданное число и ни один отпечаток.
        calibration = _calibration()
        result = quantity.compute(_polygon(OUTER), geometry=_geometry(), calibration=calibration)
        legacy = "|".join(
            [
                "area.v1",
                "polygon",
                ";".join(f"{x!r},{y!r}" for x, y in OUTER),
                FINGERPRINT,
                str(calibration.mm_per_pt),
            ]
        )

        assert result.rule_key == "area.v1"
        assert result.input_fingerprint == hashlib.sha256(legacy.encode("utf-8")).hexdigest()
        assert result.value == Decimal("64")
        assert result.geometry_issue is None


class TestAreaWithHoles:
    def test_outer_minus_one_hole(self) -> None:
        result = _ready(_polygon(OUTER, [HOLE_A]))

        assert result.state is QuantityState.READY
        assert result.rule_key == "area_with_holes.v1"
        assert result.rule_version == "v1"
        assert result.value is not None
        assert abs(result.value - Decimal("60")) < Decimal("1e-9")

    def test_outer_minus_several_holes(self) -> None:
        result = _ready(_polygon(OUTER, [HOLE_A, HOLE_B]))

        assert result.value is not None
        assert abs(result.value - Decimal("55.5")) < Decimal("1e-9")

    def test_hole_winding_does_not_matter(self) -> None:
        forward = _ready(_polygon(OUTER, [HOLE_A]))
        reversed_hole = _ready(_polygon(OUTER, [list(reversed(HOLE_A))]))

        assert forward.value == reversed_hole.value

    def test_holes_change_the_fingerprint_and_order_is_part_of_it(self) -> None:
        plain = _ready(_polygon(OUTER))
        ab = _ready(_polygon(OUTER, [HOLE_A, HOLE_B]))
        ba = _ready(_polygon(OUTER, [HOLE_B, HOLE_A]))

        assert plain.input_fingerprint != ab.input_fingerprint
        assert ab.input_fingerprint != ba.input_fingerprint

    def test_repeatable(self) -> None:
        measurement = _polygon(OUTER, [HOLE_A, HOLE_B])
        geometry, calibration = _geometry(), _calibration()

        first = quantity.compute(measurement, geometry=geometry, calibration=calibration)
        second = quantity.compute(measurement, geometry=geometry, calibration=calibration)

        assert first == second


class TestInvalidGeometry:
    def test_bow_tie_has_no_area_never_zero(self) -> None:
        result = _ready(_polygon([[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]))

        assert result.state is QuantityState.INVALID_GEOMETRY
        assert result.value is None
        assert result.canonical_value is None
        assert result.geometry_issue is GeometryIssueCode.SELF_INTERSECTION

    def test_invalid_wins_over_missing_scale(self) -> None:
        # Калибровка такую фигуру не исправит: причина — контур, а не масштаб.
        result = quantity.compute(
            _polygon(OUTER, [[[0.95, 0.95], [0.99, 0.95], [0.99, 0.99]]]),
            geometry=None,
            calibration=None,
        )

        assert result.state is QuantityState.INVALID_GEOMETRY
        assert result.geometry_issue is GeometryIssueCode.HOLE_OUTSIDE_OUTER

    def test_totals_count_invalid_separately_and_name_every_rule(self) -> None:
        item = uuid.uuid4()
        rows = [
            _polygon(OUTER),
            _polygon(OUTER, [HOLE_A]),
            _polygon([[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]),
        ]
        for row in rows:
            row.takeoff_item_id = item
        results = [_ready(row) for row in rows]

        total = quantity.total(str(item), results)

        assert total.measurement_count == 2
        assert total.unavailable_count == 1
        assert total.invalid_count == 1
        assert total.rule_key == "area.v1+area_with_holes.v1"
        assert abs(total.value - Decimal("124")) < Decimal("1e-9")
