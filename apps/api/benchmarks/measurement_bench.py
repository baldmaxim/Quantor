"""Замер расчёта величин и сервисного слоя обмера.

Две части. Арифметика считается всегда: она ни от чего не зависит, и её результат — это
и точность, и стоимость расчёта. Сервисный слой требует живой базы и без неё честно
помечается пропущенным: число, полученное «примерно как на стенде», хуже отсутствующего,
потому что выглядит измеренным.

Запуск из `apps/api`:

```bash
node ../../scripts/py.mjs -m benchmarks.measurement_bench --out результат.json
```

Обычно вызывается оркестратором: `pnpm benchmark:measurement`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.base import Base
from app.domain import (
    MAX_MEASUREMENT_BATCH,
    DocumentKind,
    GeometryStatus,
    GeometryType,
    LengthUnit,
    ProcessingStatus,
    VerificationState,
)
from app.models import PageGeometry, ScaleCalibration, Sheet, TakeoffItem, Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import quantity
from app.services import takeoff as takeoff_service
from app.services.geometry.transform import (
    NormalizedPoint,
    PageGeometryValue,
    polygon_area_pdf_points2,
    polyline_length_pdf_points,
)
from benchmarks import dataset as dataset_module
from benchmarks.dataset import BenchCase, Dataset

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET = REPO_ROOT / "benchmarks" / "datasets" / "measurement_v1.json"

# Команды, которыми поднимается стенд. Печатаются в отчёт вместо выдуманных чисел.
STAND_COMMANDS = [
    "pnpm infra:up",
    "pnpm db:migrate",
    "pnpm benchmark:measurement",
]


# --- окружение ---


def _git_commit() -> str | None:
    """Читает текущий коммит из файлов .git, не запуская git.

    Запуск внешней команды ради одной строки добавил бы замеру зависимость от того, что
    установлено на машине.
    """
    head = REPO_ROOT / ".git" / "HEAD"
    if not head.exists():
        return None

    content = head.read_text(encoding="utf-8").strip()
    if not content.startswith("ref: "):
        return content

    ref = REPO_ROOT / ".git" / content[5:]
    if ref.exists():
        return ref.read_text(encoding="utf-8").strip()

    packed = REPO_ROOT / ".git" / "packed-refs"
    if packed.exists():
        needle = content[5:]
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.endswith(f" {needle}"):
                return line.split(" ", 1)[0]
    return None


def environment() -> dict[str, object]:
    """Среда замера. Число без среды несравнимо ни с чем."""
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "git_commit": _git_commit(),
        "timer_resolution_ns": time.get_clock_info("perf_counter").resolution * 1e9,
    }


# --- арифметика ---


@dataclass(frozen=True, slots=True)
class Timing:
    median_ns: float
    min_ns: float
    p95_ns: float
    iterations: int


def _time(action: Callable[[], object], *, iterations: int) -> Timing:
    """Замеряет действие, отбрасывая прогрев.

    Медиана, а не среднее: одна пауза сборщика мусора сдвигает среднее и ничего не говорит
    о типичной стоимости вызова. Минимум показывает нижнюю границу, p95 — хвост.
    """
    for _ in range(min(iterations, 50)):
        action()

    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        action()
        samples.append(float(time.perf_counter_ns() - started))

    samples.sort()
    index = min(len(samples) - 1, int(len(samples) * 0.95))
    return Timing(
        median_ns=statistics.median(samples),
        min_ns=samples[0],
        p95_ns=samples[index],
        iterations=iterations,
    )


def _errors(
    actual: Decimal | None, expected: Decimal | None
) -> tuple[Decimal | None, float | None]:
    """Абсолютная и относительная ошибка. Относительная не определена при нулевом ожидании."""
    if actual is None or expected is None:
        return None, None

    absolute = abs(actual - expected)
    if expected == 0:
        return absolute, None
    return absolute, float(absolute / abs(expected))


def _time_geometry(case: BenchCase, *, iterations: int) -> Timing | None:
    """Замеряет только преобразование координат, без происхождения и Decimal.

    Нужен, чтобы отличать стоимость геометрии от стоимости доказательства: без разделения
    вывод «расчёт медленный на тысяче вершин» не указывал бы, что именно медленное.
    """
    if case.geometry is None:
        return None

    page = PageGeometryValue.from_decimal(
        case.geometry.display_width_pt, case.geometry.display_height_pt
    )
    points = [NormalizedPoint(float(x), float(y)) for x, y in case.measurement.points]
    if case.measurement.geometry_type is GeometryType.COUNT:
        return None
    if case.measurement.geometry_type is GeometryType.POLYGON:
        return _time(lambda: polygon_area_pdf_points2(points, page), iterations=iterations)
    return _time(lambda: polyline_length_pdf_points(points, page), iterations=iterations)


def _run_case(case: BenchCase, *, iterations: int, repeats: int) -> dict[str, object]:
    result = quantity.compute(
        case.measurement, geometry=case.geometry, calibration=case.calibration
    )

    absolute, relative = _errors(result.value, case.expected.value)
    canonical_error, _ = _errors(result.canonical_value, case.expected.canonical_value)

    mismatches: list[str] = []
    if result.state.value != case.expected.state:
        mismatches.append(f"состояние {result.state.value} вместо {case.expected.state}")
    if result.unit.value != case.expected.unit:
        mismatches.append(f"единица {result.unit.value} вместо {case.expected.unit}")
    if result.rule_key != case.expected.rule_key:
        mismatches.append(f"правило {result.rule_key} вместо {case.expected.rule_key}")
    if (result.value is None) != (case.expected.value is None):
        mismatches.append("наличие величины не совпало с ожиданием")
    if (
        absolute is not None
        and case.expected.value is not None
        and not case.tolerance.allows(absolute, case.expected.value)
    ):
        mismatches.append(f"ошибка {absolute} больше допуска")
    if canonical_error is not None and canonical_error != 0 and case.tolerance.absolute == 0:
        mismatches.append(f"каноническое значение разошлось на {canonical_error}")
    if not case.evidence.consistent:
        mismatches.append(f"доказательство калибровки не сходится: {case.evidence.note}")

    # Воспроизводимость: тот же вход обязан давать посимвольно то же число и тот же
    # отпечаток. Сравнение строк, а не чисел, — иначе разница в разрядах осталась бы незаметной.
    signatures: set[tuple[str, str, str]] = set()
    for _ in range(repeats):
        again = quantity.compute(
            case.measurement, geometry=case.geometry, calibration=case.calibration
        )
        signatures.add((again.state.value, str(again.canonical_value), again.input_fingerprint))

    timing = _time(
        lambda: quantity.compute(
            case.measurement, geometry=case.geometry, calibration=case.calibration
        ),
        iterations=iterations,
    )
    geometry_timing = _time_geometry(case, iterations=iterations)

    return {
        "case_id": case.case_id,
        "geometry_type": case.measurement.geometry_type.value,
        "vertices": case.vertex_count,
        "page": case.page_id,
        "calibration": case.calibration_id,
        "expected": {
            "state": case.expected.state,
            "value": str(case.expected.value) if case.expected.value is not None else None,
            "unit": case.expected.unit,
        },
        "actual": {
            "state": result.state.value,
            "value": str(result.value) if result.value is not None else None,
            "unit": result.unit.value,
            "canonical_value": (
                str(result.canonical_value) if result.canonical_value is not None else None
            ),
            "canonical_unit": result.canonical_unit,
            "rule_key": result.rule_key,
            "input_fingerprint": result.input_fingerprint,
        },
        "absolute_error": str(absolute) if absolute is not None else None,
        "relative_error": relative,
        "tolerance": {
            "absolute": str(case.tolerance.absolute),
            "relative": str(case.tolerance.relative),
        },
        "passed": not mismatches,
        "mismatches": mismatches,
        "repeatable": len(signatures) == 1,
        "repeats": repeats,
        "evidence": {
            "checked": case.evidence.checked,
            "consistent": case.evidence.consistent,
            "note": case.evidence.note,
        },
        "timing": {
            "median_ns": timing.median_ns,
            "min_ns": timing.min_ns,
            "p95_ns": timing.p95_ns,
            "iterations": timing.iterations,
            "per_second": (1e9 / timing.median_ns) if timing.median_ns > 0 else None,
            # Сколько из этого — сама геометрия. Остаток уходит на происхождение:
            # отпечаток входа перебирает все вершины и потому растёт вместе с ними.
            "geometry_median_ns": (
                geometry_timing.median_ns if geometry_timing is not None else None
            ),
        },
        "source_note": case.source_note,
    }


def run_math(data: Dataset, *, iterations: int, repeats: int) -> dict[str, object]:
    cases = [_run_case(case, iterations=iterations, repeats=repeats) for case in data.cases]
    failed = [case["case_id"] for case in cases if not case["passed"]]
    unrepeatable = [case["case_id"] for case in cases if not case["repeatable"]]

    return {
        "status": "ok" if not failed and not unrepeatable else "failed",
        "cases": cases,
        "summary": {
            "total": len(cases),
            "passed": len(cases) - len(failed),
            "failed": failed,
            "unrepeatable": unrepeatable,
        },
    }


# --- сервисный слой на живой базе ---


@contextmanager
def _count_queries(engine: AsyncEngine) -> Iterator[list[str]]:
    """Считает SQL-запросы за время блока: N+1 глазами не виден, счётчиком — сразу."""
    statements: list[str] = []

    def before(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def _timed(action: Callable[[], Awaitable[None]], *, iterations: int) -> Timing:
    """Замер асинхронного действия. Прогрев отдельный: первый вызов оплачивает соединение."""
    for _ in range(min(iterations, 3)):
        await action()

    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        await action()
        samples.append(float(time.perf_counter_ns() - started))

    samples.sort()
    index = min(len(samples) - 1, int(len(samples) * 0.95))
    return Timing(
        median_ns=statistics.median(samples),
        min_ns=samples[0],
        p95_ns=samples[index],
        iterations=iterations,
    )


def _bench_database_url() -> tuple[str, str, str]:
    settings = get_settings()
    name = f"{settings.postgres_db}_bench"
    password = settings.postgres_password.get_secret_value()
    prefix = (
        f"postgresql+asyncpg://{settings.postgres_user}:{password}"
        f"@{settings.postgres_host}:{settings.postgres_port}"
    )
    return f"{prefix}/{name}", f"{prefix}/postgres", name


async def _prepare_database() -> AsyncEngine | None:
    """Готовит отдельную базу замера. Возвращает None, если сервера нет."""
    target, maintenance, name = _bench_database_url()

    admin = create_async_engine(maintenance, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            exists = await connection.scalar(
                text("select 1 from pg_database where datname = :name"), {"name": name}
            )
            if not exists:
                await connection.execute(text(f'create database "{name}"'))
    except Exception:
        return None
    finally:
        await admin.dispose()

    engine = create_async_engine(target, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    return engine


@dataclass(frozen=True, slots=True)
class Fixture:
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    sheet: Sheet
    calibration: ScaleCalibration
    item: TakeoffItem


async def _seed(session: AsyncSession) -> Fixture:
    workspace = Workspace(slug="bench", name="Замер")
    session.add(workspace)
    await session.flush()

    project = await projects_service.create_project(
        session, workspace_id=workspace.id, name="Замер обмеров"
    )
    document = await documents_service.create_document(
        session, project=project, display_name="лист.pdf", document_kind=DocumentKind.PDF
    )
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=uuid.uuid4(),
        source_filename="лист.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256="0" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY,
    )
    sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1", rotation=0)
    session.add(sheet)
    await session.flush()

    fingerprint = "c" * 64
    session.add(
        PageGeometry(
            sheet_id=sheet.id,
            display_width_pt=Decimal("1000.0000"),
            display_height_pt=Decimal("1000.0000"),
            pdf_rotation=0,
            media_box=[],
            crop_box=[],
            parser_name="synthetic",
            parser_version="1",
            source_sha256="0" * 64,
            geometry_fingerprint=fingerprint,
            extracted_at=datetime.now(UTC),
        )
    )
    calibration = ScaleCalibration(
        sheet_id=sheet.id,
        point_a_x=Decimal("0"),
        point_a_y=Decimal("0"),
        point_b_x=Decimal("1"),
        point_b_y=Decimal("0"),
        input_value=Decimal("10000"),
        input_unit=LengthUnit.MM,
        known_distance_mm=Decimal("10000"),
        page_distance_pt=Decimal("1000"),
        mm_per_pt=Decimal("10"),
        page_geometry_fingerprint=fingerprint,
        verification_state=VerificationState.UNVERIFIED,
        is_default=True,
    )
    session.add(calibration)
    await session.flush()

    item = await takeoff_service.create_item(
        session, project=project, name="Стены", geometry_type=GeometryType.POLYLINE
    )
    await session.commit()

    return Fixture(
        workspace_id=workspace.id,
        project_id=project.id,
        sheet=sheet,
        calibration=calibration,
        item=item,
    )


async def run_api(*, iterations: int, measurements: int) -> dict[str, object]:
    """Задержки сервисного слоя и число запросов на живой базе."""
    engine = await _prepare_database()
    if engine is None:
        return {
            "status": "skipped",
            "reason": "PostgreSQL недоступен — стенд не поднят.",
            "commands": STAND_COMMANDS,
        }

    factory = async_sessionmaker(engine, expire_on_commit=False)
    metrics: dict[str, object] = {}

    try:
        async with factory() as session:
            fixture = await _seed(session)
            item = fixture.item
            points = [[0.1, 0.1], [0.4, 0.5], [0.7, 0.2]]

            async def create_one() -> None:
                await takeoff_service.create_measurement(
                    session,
                    item=item,
                    sheet=fixture.sheet,
                    points=points,
                    calibration=fixture.calibration,
                )
                await session.commit()

            metrics["create_measurement"] = _timing_payload(
                await _timed(create_one, iterations=iterations)
            )

            # Наполняем лист, чтобы список измерялся не на пустом месте.
            batch = [points for _ in range(MAX_MEASUREMENT_BATCH)]

            async def stored() -> int:
                return await takeoff_service.count_for_item(
                    session,
                    workspace_id=fixture.workspace_id,
                    item_id=item.id,
                    sheet_id=fixture.sheet.id,
                )

            while await stored() < measurements:
                await takeoff_service.create_measurements_batch(
                    session,
                    item=item,
                    sheet=fixture.sheet,
                    batch=batch,
                    calibration=fixture.calibration,
                )
                await session.commit()

            async def create_batch() -> None:
                await takeoff_service.create_measurements_batch(
                    session,
                    item=item,
                    sheet=fixture.sheet,
                    batch=batch,
                    calibration=fixture.calibration,
                )
                await session.rollback()

            metrics["create_batch_200"] = _timing_payload(
                await _timed(create_batch, iterations=max(3, iterations // 10))
            )

            async def list_sheet() -> None:
                await takeoff_service.list_for_sheet(
                    session, workspace_id=fixture.workspace_id, sheet_id=fixture.sheet.id
                )

            metrics["list_for_sheet"] = _timing_payload(
                await _timed(list_sheet, iterations=iterations)
            )

            async def list_items() -> None:
                await takeoff_service.list_items(
                    session, workspace_id=fixture.workspace_id, project_id=fixture.project_id
                )

            metrics["list_items"] = _timing_payload(await _timed(list_items, iterations=iterations))

            rows = await takeoff_service.list_for_sheet(
                session, workspace_id=fixture.workspace_id, sheet_id=fixture.sheet.id
            )
            target = rows[0]

            async def update_one() -> None:
                await takeoff_service.update_geometry(
                    session,
                    measurement=target,
                    points=points,
                    expected_version=target.version,
                )
                await session.commit()

            metrics["update_geometry"] = _timing_payload(
                await _timed(update_one, iterations=iterations)
            )

            # Число запросов не должно расти вместе с числом измерений: список — это один
            # запрос, а не один плюс по одному на строку.
            with _count_queries(engine) as statements:
                await takeoff_service.list_for_sheet(
                    session, workspace_id=fixture.workspace_id, sheet_id=fixture.sheet.id
                )
            list_queries = len(statements)

            with _count_queries(engine) as statements:
                await takeoff_service.list_items(
                    session, workspace_id=fixture.workspace_id, project_id=fixture.project_id
                )
            items_queries = len(statements)

            metrics["queries"] = {
                "list_for_sheet": list_queries,
                "list_items": items_queries,
                "measurements_in_sheet": len(rows),
                "n_plus_one": list_queries > 1 or items_queries > 1,
            }
    finally:
        await engine.dispose()

    return {"status": "ok", "measurements_seeded": measurements, "metrics": metrics}


def _timing_payload(timing: Timing) -> dict[str, object]:
    return {
        "median_ms": timing.median_ns / 1e6,
        "min_ms": timing.min_ns / 1e6,
        "p95_ms": timing.p95_ns / 1e6,
        "iterations": timing.iterations,
    }


# --- запуск ---


def main() -> int:
    parser = argparse.ArgumentParser(description="Замер расчёта величин Stage 2A")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=25)
    parser.add_argument("--measurements", type=int, default=1000)
    parser.add_argument("--skip-api", action="store_true")
    args = parser.parse_args()

    data = dataset_module.load(args.dataset, repo_root=REPO_ROOT)

    api: dict[str, object]
    if args.skip_api:
        api = {
            "status": "skipped",
            "reason": "Раздел выключен ключом --skip-api.",
            "commands": STAND_COMMANDS,
        }
    else:
        api = asyncio.run(
            run_api(iterations=max(5, args.iterations // 10), measurements=args.measurements)
        )

    math = run_math(data, iterations=args.iterations, repeats=args.repeats)

    report: dict[str, object] = {
        "schema": "quantor.benchmark.math.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": environment(),
        "dataset": {
            "id": data.dataset_id,
            "version": data.dataset_version,
            "manifest_version": data.manifest_version,
            "sha256": data.source_sha256,
            "path": Path(data.source_path).relative_to(REPO_ROOT).as_posix(),
            "cases": len(data.cases),
            "note": data.note,
        },
        "sections": {"math": math, "api": api},
    }

    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded + "\n", encoding="utf-8")
    else:
        sys.stdout.write(encoded + "\n")

    # Ненулевой код возврата, если арифметика разошлась с датасетом: замер, который
    # молча печатает провал, ничем не лучше отсутствующего замера.
    return 0 if math["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
