"""Замер валидатора многоугольника и правила `area_with_holes.v1` (промт 05, ADR-0026).

Две части:

- **точность** — аналитические случаи: площадь с отверстиями сверяется с ответом, посчитанным
  в уме; недействительный контур обязан дать `invalid_geometry` и пустую величину, а не 0 м²;
- **стоимость** — время валидатора и полного `compute` на фигурах от шестиугольника до
  контура на 10 000 вершин с 200 отверстиями и злонамеренной «гребёнки».

Только синтетика: частные чертежи сюда не попадают.

```bash
node ../../scripts/py.mjs -m benchmarks.geometry_bench --out результат.json
```
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.domain import (
    GeometryIssueCode,
    GeometryType,
    MeasurementSource,
    QuantityState,
    VerificationState,
)
from app.models import Measurement, PageGeometry, ScaleCalibration
from app.services import quantity
from app.services.geometry.validity import validate_polygon

Ring = list[tuple[float, float]]

# Лист 1000×1000 pt при 10 мм/pt — 10×10 м: доля страницы переводится в метры в уме.
PAGE_SIDE = Decimal("1000.0000")
MM_PER_PT = Decimal("10.000000000000")
TOLERANCE_M2 = Decimal("1e-9")


def _geometry() -> PageGeometry:
    return PageGeometry(
        sheet_id=uuid.uuid4(),
        display_width_pt=PAGE_SIDE,
        display_height_pt=PAGE_SIDE,
        pdf_rotation=0,
        media_box=[],
        crop_box=[],
        parser_name="bench",
        parser_version="0",
        source_sha256="b" * 64,
        geometry_fingerprint="a" * 64,
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
        page_geometry_fingerprint="a" * 64,
        verification_state=VerificationState.UNVERIFIED,
    )


def _measurement(outer: Ring, holes: list[Ring]) -> Measurement:
    return Measurement(
        id=uuid.uuid4(),
        takeoff_item_id=uuid.uuid4(),
        sheet_id=uuid.uuid4(),
        geometry_type=GeometryType.POLYGON,
        points=[[x, y] for x, y in outer],
        holes=[[[x, y] for x, y in ring] for ring in holes],
        source=MeasurementSource.MANUAL,
        version=1,
    )


def _rect(x0: float, y0: float, x1: float, y1: float) -> Ring:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _circle(count: int, cx: float = 0.5, cy: float = 0.5, radius: float = 0.4) -> Ring:
    return [
        (
            cx + radius * math.cos(2 * math.pi * k / count),
            cy + radius * math.sin(2 * math.pi * k / count),
        )
        for k in range(count)
    ]


def _hole_grid(count: int, vertices: int) -> list[Ring]:
    """Отверстия-кружки сеткой внутри круга радиуса 0,4: не касаются ни контура, ни друг друга."""
    side = math.ceil(math.sqrt(count))
    step = 0.5 / side
    holes: list[Ring] = []
    for index in range(count):
        row, column = divmod(index, side)
        cx = 0.25 + step * (column + 0.5)
        cy = 0.25 + step * (row + 0.5)
        holes.append(_circle(vertices, cx, cy, step * 0.3))
    return holes


def _comb(teeth: int) -> Ring:
    ring: Ring = [(0.02, 0.02)]
    for index in range(teeth):
        left = 0.05 + 0.9 * index / teeth
        right = left + 0.9 / (2 * teeth)
        ring += [(left, 0.95), (left + 1e-9, 0.1), (right, 0.1), (right - 1e-9, 0.95)]
    ring.append((0.98, 0.02))
    return ring


# ------------------------------------------------------------------------------ точность


@dataclass(frozen=True, slots=True)
class AccuracyCase:
    name: str
    outer: Ring
    holes: list[Ring]
    expected_state: QuantityState
    expected_rule: str
    expected_m2: Decimal | None = None
    expected_issue: GeometryIssueCode | None = None


ACCURACY_CASES: list[AccuracyCase] = [
    AccuracyCase(
        "квадрат 8×8 без отверстий",
        _rect(0.1, 0.1, 0.9, 0.9),
        [],
        QuantityState.READY,
        "area.v1",
        Decimal("64"),
    ),
    AccuracyCase(
        "квадрат 8×8 − 2×2",
        _rect(0.1, 0.1, 0.9, 0.9),
        [_rect(0.2, 0.2, 0.4, 0.4)],
        QuantityState.READY,
        "area_with_holes.v1",
        Decimal("60"),
    ),
    AccuracyCase(
        "квадрат 8×8 − 2×2 − треугольник 4,5",
        _rect(0.1, 0.1, 0.9, 0.9),
        [_rect(0.2, 0.2, 0.4, 0.4), [(0.5, 0.5), (0.8, 0.5), (0.8, 0.8)]],
        QuantityState.READY,
        "area_with_holes.v1",
        Decimal("55.5"),
    ),
    AccuracyCase(
        "плита 9×6 − четыре отверстия 1×1",
        _rect(0.05, 0.2, 0.95, 0.8),
        [_rect(0.1 + 0.2 * k, 0.4, 0.2 + 0.2 * k, 0.5) for k in range(4)],
        QuantityState.READY,
        "area_with_holes.v1",
        Decimal("50"),
    ),
    AccuracyCase(
        "бантик",
        [(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)],
        [],
        QuantityState.INVALID_GEOMETRY,
        "area.v1",
        expected_issue=GeometryIssueCode.SELF_INTERSECTION,
    ),
    AccuracyCase(
        "повтор вершины",
        [(0.1, 0.1), (0.9, 0.1), (0.9, 0.1), (0.9, 0.9)],
        [],
        QuantityState.INVALID_GEOMETRY,
        "area.v1",
        expected_issue=GeometryIssueCode.DUPLICATE_VERTEX,
    ),
    AccuracyCase(
        "вырожденный в линию",
        [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)],
        [],
        QuantityState.INVALID_GEOMETRY,
        "area.v1",
        expected_issue=GeometryIssueCode.DEGENERATE_RING,
    ),
    AccuracyCase(
        "отверстие снаружи",
        _rect(0.1, 0.1, 0.5, 0.5),
        [_rect(0.6, 0.6, 0.7, 0.7)],
        QuantityState.INVALID_GEOMETRY,
        "area_with_holes.v1",
        expected_issue=GeometryIssueCode.HOLE_OUTSIDE_OUTER,
    ),
    AccuracyCase(
        "отверстие касается контура",
        _rect(0.1, 0.1, 0.9, 0.9),
        [_rect(0.1, 0.4, 0.3, 0.6)],
        QuantityState.INVALID_GEOMETRY,
        "area_with_holes.v1",
        expected_issue=GeometryIssueCode.RING_INTERSECTION,
    ),
    AccuracyCase(
        "отверстие в отверстии",
        _rect(0.1, 0.1, 0.9, 0.9),
        [_rect(0.3, 0.3, 0.7, 0.7), _rect(0.4, 0.4, 0.6, 0.6)],
        QuantityState.INVALID_GEOMETRY,
        "area_with_holes.v1",
        expected_issue=GeometryIssueCode.HOLE_INSIDE_HOLE,
    ),
]


@dataclass(frozen=True, slots=True)
class AccuracyRow:
    name: str
    state: str
    rule_key: str
    value_m2: str | None
    expected_m2: str | None
    geometry_issue: str | None
    passed: bool


def run_accuracy() -> list[AccuracyRow]:
    geometry, calibration = _geometry(), _calibration()
    rows: list[AccuracyRow] = []
    for case in ACCURACY_CASES:
        result = quantity.compute(
            _measurement(case.outer, case.holes), geometry=geometry, calibration=calibration
        )
        passed = result.state is case.expected_state and result.rule_key == case.expected_rule
        if case.expected_m2 is not None:
            passed = (
                passed
                and result.value is not None
                and abs(result.value - case.expected_m2) < TOLERANCE_M2
            )
        else:
            # Недействительный контур: величины нет вовсе — ни числа, ни нуля.
            passed = passed and result.value is None and result.canonical_value is None
            passed = passed and result.geometry_issue is case.expected_issue
        rows.append(
            AccuracyRow(
                name=case.name,
                state=result.state.value,
                rule_key=result.rule_key,
                value_m2=str(result.value) if result.value is not None else None,
                expected_m2=str(case.expected_m2) if case.expected_m2 is not None else None,
                geometry_issue=result.geometry_issue.value if result.geometry_issue else None,
                passed=passed,
            )
        )
    return rows


# ------------------------------------------------------------------------------ стоимость


@dataclass(frozen=True, slots=True)
class CostRow:
    name: str
    vertices: int
    holes: int
    outcome: str
    validate_median_ms: float
    validate_p95_ms: float
    compute_median_ms: float


def _validator(outer: Ring, holes: list[Ring]) -> Callable[[], object]:
    return lambda: validate_polygon(outer, holes)


def _computation(
    measurement: Measurement, geometry: PageGeometry, calibration: ScaleCalibration
) -> Callable[[], object]:
    return lambda: quantity.compute(measurement, geometry=geometry, calibration=calibration)


def _timings(action: Callable[[], object], repeats: int) -> list[float]:
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def run_cost(repeats: int) -> list[CostRow]:
    cases: list[tuple[str, Ring, list[Ring], int]] = [
        ("шестиугольник", _circle(6), [], repeats * 20),
        ("круг 100", _circle(100), [], repeats * 4),
        ("круг 1 000", _circle(1000), [], repeats),
        ("круг 10 000", _circle(10_000), [], max(3, repeats // 4)),
        ("круг 1 000 + 50 отверстий × 20", _circle(1000), _hole_grid(50, 20), repeats),
        ("круг 10 000 + 200 отверстий × 50", _circle(10_000), _hole_grid(200, 50), 3),
        ("гребёнка 2 500 зубьев", _comb(2500), [], 3),
    ]
    geometry, calibration = _geometry(), _calibration()
    rows: list[CostRow] = []
    for name, outer, holes, count in cases:
        issue = validate_polygon(outer, holes)
        validate = _timings(_validator(outer, holes), count)
        compute = _timings(_computation(_measurement(outer, holes), geometry, calibration), count)
        rows.append(
            CostRow(
                name=name,
                vertices=len(outer) + sum(len(ring) for ring in holes),
                holes=len(holes),
                outcome=issue.code.value if issue is not None else "valid",
                validate_median_ms=round(statistics.median(validate), 4),
                validate_p95_ms=round(_p95(validate), 4),
                compute_median_ms=round(statistics.median(compute), 4),
            )
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Замер валидатора многоугольника (Stage 2B)")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=40)
    args = parser.parse_args()

    accuracy = run_accuracy()
    cost = run_cost(args.repeats)
    report = {
        "benchmark": "geometry_validity.v1",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "accuracy": [asdict(row) for row in accuracy],
        "accuracy_passed": sum(row.passed for row in accuracy),
        "accuracy_total": len(accuracy),
        "cost": [asdict(row) for row in cost],
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
    else:
        sys.stdout.write(encoded + "\n")
    return 0 if all(row.passed for row in accuracy) else 1


if __name__ == "__main__":
    raise SystemExit(main())
