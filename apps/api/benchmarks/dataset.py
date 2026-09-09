"""Чтение версионированного датасета замера.

Манифест описывает случай целиком: страницу, доказательство калибровки, геометрию
измерения, ожидаемую величину, единицу и допуск. Ожидание в манифесте — внешнее знание
(аналитика или размерная надпись на чертеже), а не вывод программы: датасет, заполненный
собственным результатом, доказывает воспроизводимость и ничего не говорит о правильности.

Страница задаётся либо размерами, либо ссылкой на настоящий PDF. Во втором случае геометрию
читает тот же провайдер, что и рабочий конвейер, — иначе замер проверял бы не то, что
работает в проде.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.domain import (
    GeometryType,
    LengthUnit,
    MeasurementSource,
    ScaleSource,
    VerificationState,
)
from app.models import Measurement, PageGeometry, ScaleCalibration
from app.services import scale as scale_service
from app.services.geometry.extract import fingerprint
from app.services.geometry.provider import PypdfGeometryProvider

# --- разбор манифеста ---
#
# Узкие помощники вместо прямого обращения к результату json.loads: битый манифест обязан
# падать с внятным сообщением о поле, а не превращаться в непонятную ошибку арифметики.


class ManifestError(ValueError):
    """Манифест не соответствует формату."""


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ManifestError(f"{where}: ожидался объект, получено {type(value).__name__}")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestError(f"{where}: ожидался список, получено {type(value).__name__}")
    return list(value)


def _text(source: dict[str, object], key: str, where: str) -> str:
    value = source.get(key)
    if not isinstance(value, str):
        raise ManifestError(f"{where}.{key}: ожидалась строка")
    return value


def _optional_text(source: dict[str, object], key: str, where: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(f"{where}.{key}: ожидалась строка или null")
    return value


def _integer(source: dict[str, object], key: str, where: str) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestError(f"{where}.{key}: ожидалось целое")
    return value


def _decimal(source: dict[str, object], key: str, where: str) -> Decimal:
    value = _text(source, key, where)
    return Decimal(value)


def _optional_decimal(source: dict[str, object], key: str, where: str) -> Decimal | None:
    value = _optional_text(source, key, where)
    return None if value is None else Decimal(value)


def _pair(value: object, where: str) -> tuple[Decimal, Decimal]:
    items = _sequence(value, where)
    if len(items) != 2:
        raise ManifestError(f"{where}: ожидались две координаты")
    first, second = items
    if not isinstance(first, str) or not isinstance(second, str):
        raise ManifestError(
            f"{where}: координаты записываются строками — двоичная дробь"
            " в JSON зависела бы от того, кто её печатал"
        )
    return Decimal(first), Decimal(second)


# --- структуры ---


@dataclass(frozen=True, slots=True)
class Tolerance:
    """Допуск случая. Ноль означает требование точного совпадения."""

    absolute: Decimal
    relative: Decimal

    def allows(self, error: Decimal, expected: Decimal) -> bool:
        return error <= max(self.absolute, self.relative * abs(expected))


@dataclass(frozen=True, slots=True)
class Expectation:
    state: str
    value: Decimal | None
    unit: str
    canonical_value: Decimal | None
    canonical_unit: str
    rule_key: str


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    """Согласованность доказательства калибровки внутри самого манифеста.

    Коэффициент обязан следовать из известного размера и расстояния на странице. Датасет,
    в котором эти три числа не сходятся, описывает не тот случай, который думает автор.
    """

    checked: bool
    consistent: bool
    note: str


@dataclass(frozen=True, slots=True)
class BenchCase:
    case_id: str
    geometry: PageGeometry | None
    calibration: ScaleCalibration | None
    measurement: Measurement
    expected: Expectation
    tolerance: Tolerance
    source_note: str
    vertex_count: int
    page_id: str | None
    calibration_id: str | None
    evidence: EvidenceCheck


@dataclass(frozen=True, slots=True)
class Dataset:
    manifest_version: int
    dataset_id: str
    dataset_version: str
    note: str
    source_path: str
    source_sha256: str
    cases: list[BenchCase]


# --- построение объектов домена ---


def _geometry_from_dimensions(raw: dict[str, object], where: str) -> PageGeometry:
    return PageGeometry(
        sheet_id=uuid.uuid4(),
        display_width_pt=_decimal(raw, "display_width_pt", where),
        display_height_pt=_decimal(raw, "display_height_pt", where),
        pdf_rotation=_integer(raw, "pdf_rotation", where),
        media_box=[],
        crop_box=[],
        parser_name="synthetic",
        parser_version="1",
        source_sha256="0" * 64,
        geometry_fingerprint=_text(raw, "geometry_fingerprint", where),
        extracted_at=datetime.now(UTC),
    )


def _geometry_from_pdf(raw: dict[str, object], where: str, repo_root: Path) -> PageGeometry:
    """Читает страницу настоящего PDF тем же провайдером, что и рабочий конвейер."""
    ref = _mapping(raw["sheet_ref"], f"{where}.sheet_ref")
    relative = _text(ref, "pdf_path", f"{where}.sheet_ref")
    path = Path(relative)
    if not path.is_absolute():
        path = repo_root / relative
    if not path.exists():
        raise ManifestError(f"{where}.sheet_ref.pdf_path: файл не найден: {path}")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    declared = _optional_text(ref, "source_sha256", f"{where}.sheet_ref")
    if declared is not None and declared != digest:
        raise ManifestError(
            f"{where}.sheet_ref: файл не тот, что описан в датасете."
            " Чертёж, подменённый под тем же именем, обязан быть замечен"
        )

    provider = PypdfGeometryProvider()
    pages = provider.read(path)
    index = _integer(ref, "page_index", f"{where}.sheet_ref")
    if index >= len(pages):
        raise ManifestError(f"{where}.sheet_ref.page_index: в файле {len(pages)} страниц")

    page = pages[index]
    return PageGeometry(
        sheet_id=uuid.uuid4(),
        display_width_pt=page.display_width_pt,
        display_height_pt=page.display_height_pt,
        pdf_rotation=page.rotation,
        media_box=page.media_box,
        crop_box=page.crop_box,
        parser_name=provider.name,
        parser_version=provider.version,
        source_sha256=digest,
        geometry_fingerprint=fingerprint(page, provider),
        extracted_at=datetime.now(UTC),
    )


def _calibration(
    raw: dict[str, object], where: str, geometry: PageGeometry | None
) -> tuple[ScaleCalibration, EvidenceCheck]:
    point_a = _pair(raw["point_a"], f"{where}.point_a")
    point_b = _pair(raw["point_b"], f"{where}.point_b")
    known_mm = _decimal(raw, "known_distance_mm", where)
    distance_pt = _optional_decimal(raw, "page_distance_pt", where)
    factor = _optional_decimal(raw, "mm_per_pt", where)

    # Расстояние и коэффициент считает сервер, если в манифесте их нет: это ровно тот путь,
    # которым калибровка появляется в проде.
    if (distance_pt is None or factor is None) and geometry is not None:
        distance_pt, factor = scale_service.compute_factor(
            geometry=geometry, point_a=point_a, point_b=point_b, known_distance_mm=known_mm
        )

    if distance_pt is None or factor is None:
        raise ManifestError(f"{where}: коэффициент неоткуда взять — нет ни числа, ни страницы")

    evidence = _check_evidence(known_mm, distance_pt, factor)

    calibration = ScaleCalibration(
        id=uuid.uuid4(),
        sheet_id=uuid.uuid4(),
        point_a_x=point_a[0],
        point_a_y=point_a[1],
        point_b_x=point_b[0],
        point_b_y=point_b[1],
        input_value=_decimal(raw, "input_value", where),
        input_unit=LengthUnit(_text(raw, "input_unit", where)),
        known_distance_mm=known_mm,
        page_distance_pt=distance_pt,
        mm_per_pt=factor,
        page_geometry_fingerprint=(
            geometry.geometry_fingerprint if geometry is not None else "0" * 64
        ),
        source=ScaleSource(_text(raw, "source", where)),
        verification_state=VerificationState(_text(raw, "verification_state", where)),
    )
    return calibration, evidence


def _check_evidence(known_mm: Decimal, distance_pt: Decimal, factor: Decimal) -> EvidenceCheck:
    """Сверяет три числа доказательства между собой."""
    if distance_pt == 0:
        return EvidenceCheck(True, False, "расстояние на странице равно нулю")

    # Сравнение по произведению, а не по частному: деление добавило бы собственную
    # погрешность округления к проверке, которая её и ищет.
    consistent = factor * distance_pt == known_mm
    if consistent:
        return EvidenceCheck(True, True, "коэффициент следует из известного размера")

    return EvidenceCheck(
        True,
        False,
        f"коэффициент {factor} × {distance_pt} pt даёт {factor * distance_pt} мм"
        f" вместо заявленных {known_mm} мм",
    )


def _points(raw: dict[str, object], where: str) -> list[list[float]]:
    generator = raw.get("generator")
    if generator is not None:
        return _generated_points(_mapping(generator, f"{where}.generator"), f"{where}.generator")

    items = _sequence(raw["points"], f"{where}.points")
    return [[float(x), float(y)] for x, y in (_pair(item, f"{where}.points") for item in items)]


def _generated_points(raw: dict[str, object], where: str) -> list[list[float]]:
    """Разворачивает крупную геометрию, которую нет смысла хранить поточечно."""
    kind = _text(raw, "kind", where)
    if kind != "horizontal_scan":
        raise ManifestError(f"{where}.kind: неизвестный генератор {kind}")

    vertices = _integer(raw, "vertices", where)
    if vertices < 2:
        raise ManifestError(f"{where}.vertices: нужно хотя бы две вершины")

    y = float(_decimal(raw, "y", where))
    steps = vertices - 1
    return [[index / steps, y] for index in range(vertices)]


def _expectation(raw: dict[str, object], where: str) -> Expectation:
    return Expectation(
        state=_text(raw, "state", where),
        value=_optional_decimal(raw, "value", where),
        unit=_text(raw, "unit", where),
        canonical_value=_optional_decimal(raw, "canonical_value", where),
        canonical_unit=_text(raw, "canonical_unit", where),
        rule_key=_text(raw, "rule_key", where),
    )


def load(path: Path, *, repo_root: Path) -> Dataset:
    """Читает манифест и собирает готовые к расчёту случаи."""
    payload = path.read_bytes()
    root = _mapping(json.loads(payload.decode("utf-8")), "манифест")

    pages = _mapping(root.get("pages", {}), "pages")
    calibrations = _mapping(root.get("calibrations", {}), "calibrations")

    geometries: dict[str, PageGeometry] = {}
    for page_key, value in pages.items():
        page_where = f"pages.{page_key}"
        page_raw = _mapping(value, page_where)
        geometries[page_key] = (
            _geometry_from_pdf(page_raw, page_where, repo_root)
            if "sheet_ref" in page_raw
            else _geometry_from_dimensions(page_raw, page_where)
        )

    cases: list[BenchCase] = []
    for item in _sequence(root["cases"], "cases"):
        raw = _mapping(item, "cases[]")
        case_id = _text(raw, "case_id", "cases[]")
        where = f"cases.{case_id}"

        page_id = _optional_text(raw, "page", where)
        if page_id is not None and page_id not in geometries:
            raise ManifestError(f"{where}.page: страница {page_id} не описана в манифесте")
        geometry = geometries[page_id] if page_id is not None else None

        calibration_id = _optional_text(raw, "calibration", where)
        if calibration_id is not None and calibration_id not in calibrations:
            raise ManifestError(
                f"{where}.calibration: калибровка {calibration_id} не описана в манифесте"
            )
        calibration: ScaleCalibration | None = None
        evidence = EvidenceCheck(False, True, "калибровка не используется")
        if calibration_id is not None:
            calibration, evidence = _calibration(
                _mapping(calibrations[calibration_id], f"calibrations.{calibration_id}"),
                f"calibrations.{calibration_id}",
                geometry,
            )

        points = _points(raw, where)
        measurement = Measurement(
            id=uuid.uuid4(),
            takeoff_item_id=uuid.uuid4(),
            sheet_id=uuid.uuid4(),
            geometry_type=GeometryType(_text(raw, "geometry_type", where)),
            points=points,
            source=MeasurementSource.MANUAL,
            scale_calibration_id=calibration.id if calibration is not None else None,
            version=1,
        )

        cases.append(
            BenchCase(
                case_id=case_id,
                geometry=geometry,
                calibration=calibration,
                measurement=measurement,
                expected=_expectation(_mapping(raw["expected"], f"{where}.expected"), where),
                tolerance=_tolerance(_mapping(raw["tolerance"], f"{where}.tolerance"), where),
                source_note=_text(raw, "source_note", where),
                vertex_count=len(points),
                page_id=page_id,
                calibration_id=calibration_id,
                evidence=evidence,
            )
        )

    return Dataset(
        manifest_version=_integer(root, "manifest_version", "манифест"),
        dataset_id=_text(root, "dataset_id", "манифест"),
        dataset_version=_text(root, "dataset_version", "манифест"),
        note=_text(root, "note", "манифест"),
        source_path=str(path),
        # Отпечаток самого датасета: сравнивать замеры, снятые на разных наборах случаев,
        # бессмысленно, и это должно быть видно из отчёта.
        source_sha256=hashlib.sha256(payload).hexdigest(),
        cases=cases,
    )


def _tolerance(raw: dict[str, object], where: str) -> Tolerance:
    return Tolerance(
        absolute=_decimal(raw, "absolute", where),
        relative=_decimal(raw, "relative", where),
    )
