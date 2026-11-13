"""PDF -> CAD в QA-контуре: гейты, изоляция, реальный путь Quantor с отдельным процессом движка.

Тесты без базы проверяют гейты и контракт. Тесты с базой идут через настоящие API загрузки и
постановки, захват задания `claim` по типам выделенного исполнителя и его обработчик, который
запускает runner движка отдельным процессом. Движок нужен вне git:

    QUANTOR_CAD_ENGINE_PYTHON=<интерпретатор окружения движка>
    QUANTOR_CAD_ENGINE_ARCHIVE=<SHA-закреплённый ZIP исходников>

Без них тесты движка пропускаются с причиной, а не зеленеют.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker import handler as cad_handler
from app.cad_worker.handler import execute_cad_pdf_convert
from app.core.config import Settings
from app.core.features import REGISTRY
from app.domain import JobStatus, JobType, LengthUnit
from app.errors import DomainError, ErrorCode
from app.main import create_app
from app.models import Job, PageGeometry, ScaleCalibration, Sheet, Workspace
from app.services import cad as cad_service
from app.services import jobs as jobs_service
from app.services import scale as scale_service
from app.storage.base import StorageUnavailableError
from app.worker import registry
from app.worker.runner import Worker
from tests.conftest import FakeObjectStorage, clean_settings, make_context, oidc_settings

API_DIR = Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]
RUNNER = REPO / "tools" / "cad_engine" / "quantor_cad_runner.py"
PINS = json.loads((REPO / "tools" / "cad_engine" / "pins.json").read_text(encoding="utf-8"))
ENGINE_PYTHON = os.environ.get("QUANTOR_CAD_ENGINE_PYTHON", "")
ENGINE_ARCHIVE = os.environ.get("QUANTOR_CAD_ENGINE_ARCHIVE", "")
BROKEN_PDF = b"%PDF-1.7\n" + b"0" * 512

needs_engine = pytest.mark.skipif(
    not (ENGINE_PYTHON and ENGINE_ARCHIVE and Path(ENGINE_PYTHON).is_file()),
    reason="движок не задан: QUANTOR_CAD_ENGINE_PYTHON и QUANTOR_CAD_ENGINE_ARCHIVE",
)


async def _exec(*argv: str) -> tuple[int, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=API_DIR,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    return process.returncode if process.returncode is not None else -1, output


def cad_settings(work_root: Path, *, flag: bool = True, **extra: Any) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=ENGINE_PYTHON,
        cad_engine_runner=str(RUNNER),
        cad_engine_archive=ENGINE_ARCHIVE,
        cad_work_root=str(work_root),
        cad_total_timeout_seconds=300,
        **extra,
    )


# ------------------------------------------------------------------ без базы


def test_qa_gate_cannot_be_enabled_in_production() -> None:
    with pytest.raises(ValidationError, match="CAD_QA_ENABLED"):
        clean_settings(environment="production", auth_mode="local", cad_qa_enabled=True)


def test_flag_is_off_by_default_and_admin_editable() -> None:
    flag = REGISTRY["cad.export"]
    assert flag.default is False
    assert flag.admin_editable is True
    assert flag.workspace_scoped is True
    assert flag.title == "PDF → CAD (пилот)"


def test_routes_exist_always_and_are_closed_by_the_flag() -> None:
    """ADR-0036: маршруты не зависят от CAD_QA_ENABLED, их закрывает флаг пространства."""
    base = "/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
    for settings in (clean_settings(), clean_settings(environment="production", auth_mode="local")):
        paths = create_app(settings).openapi()["paths"]
        assert base in paths
        assert f"{base}/{{job_id}}/remarks" in paths
        assert f"{base}/{{job_id}}/views/{{page_index}}/{{view}}/preview" in paths
        assert f"{base}/{{job_id}}/artifacts/{{name}}" in paths


async def test_every_cad_route_is_closed_when_the_flag_is_off(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    """Задания, файлы, диагностика, превью и замечания — всё под одним серверным гейтом."""
    from fastapi.routing import APIRoute

    from app.api.v1.cad import router

    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert len(routes) >= 12
    fill = {
        "project_id": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "job_id": str(uuid.uuid4()),
        "page_index": "0",
        "view": "1",
        "name": "report.json",
        "remark_key": "r1",
    }
    async with build_api(make_context(), settings=cad_settings(tmp_path, flag=False)) as api:
        for route in routes:
            path = "/api/v1" + route.path.replace("{name:path}", "{name}").format(**fill)
            for method in route.methods - {"HEAD", "OPTIONS"}:
                response = await api.request(method, path, json={})
                assert response.status_code == 403, (method, path)
                assert response.json()["detail"]["code"] == "FEATURE_DISABLED", (method, path)


async def test_qa_routes_deny_anonymous_request() -> None:
    from httpx import ASGITransport

    from app.core.config import get_settings

    settings = oidc_settings().model_copy(update={"environment": "test"})
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    base = f"/api/v1/projects/{uuid.uuid4()}/revisions/{uuid.uuid4()}/cad"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        for method, path in (
            ("POST", base),
            ("GET", f"{base}/{uuid.uuid4()}"),
            ("GET", f"{base}/{uuid.uuid4()}/artifacts/report.json"),
        ):
            response = await client.request(method, path, json={})
            assert response.status_code == 401, (method, path)


def test_cad_worker_start_does_not_need_the_qa_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без движка исполнитель выходит с понятной ошибкой, а не с «CAD_QA_ENABLED=false»."""
    from app.cad_worker import __main__ as worker_main

    settings = clean_settings(environment="production", auth_mode="local")
    assert settings.cad_qa_enabled is False
    monkeypatch.setattr(worker_main, "get_settings", lambda: settings)
    with pytest.raises(SystemExit) as exit_info:
        worker_main.main()
    message = str(exit_info.value)
    assert exit_info.value.code != 0
    assert ErrorCode.CAD_ENGINE_UNAVAILABLE.value in message and "CAD_QA_ENABLED" not in message


def test_engine_is_not_imported_by_api_or_workers() -> None:
    code = (
        "import sys, app.main, app.cad_worker, app.cad_worker.__main__, app.worker.__main__;"
        "print(sorted(m for m in ('fitz','pymupdf','shapely','ezdxf','numpy','PIL') "
        "if m in sys.modules))"
    )
    code_, output = asyncio.run(_exec(sys.executable, "-c", code))
    assert code_ == 0 and output.decode().strip() == "[]"


def test_pins_agree_with_service() -> None:
    assert PINS["engine"]["archive_sha256"] == cad_service.ENGINE_ARCHIVE_SHA256
    assert PINS["engine"]["version"] == cad_service.ENGINE_VERSION


def test_main_worker_never_claims_cad_and_cad_worker_claims_only_cad() -> None:
    assert JobType.CAD_PDF_CONVERT.value not in registry.supported_types()
    worker = Worker(clean_settings(), HANDLERS)
    assert sorted(worker._supported_types()) == sorted(
        [
            JobType.CAD_PDF_CONVERT.value,
            JobType.CAD_MEP_ROUTE.value,
            JobType.CAD_WALLS.value,
            JobType.CAD_FLOOR3D_DXF.value,
            JobType.CAD_ZONES.value,
            JobType.CAD_SECTIONS.value,
            JobType.CAD_EOM_ROUTE.value,
        ]
    )


def _scales(*indexes: int, factor: float = 70.5556) -> dict[int, cad_service.PageScale]:
    return {i: cad_service.PageScale(mm_per_pt=factor, calibration_id=f"cal-{i}") for i in indexes}


def test_request_validation() -> None:
    with pytest.raises(DomainError) as finishes:
        cad_service.validate_request([0], finishes=True, schedules=False)
    assert finishes.value.code is ErrorCode.CAD_PARAMS_INVALID
    for bad in ([], [0, 0], [-1]):
        with pytest.raises(DomainError) as invalid:
            cad_service.validate_request(bad, finishes=False, schedules=False)
        assert invalid.value.code is ErrorCode.CAD_PARAMS_INVALID
    with pytest.raises(DomainError) as limit:
        cad_service.validate_request(list(range(51)), finishes=False, schedules=False)
    assert limit.value.code is ErrorCode.CAD_INPUT_LIMIT_EXCEEDED
    with pytest.raises(ValueError, match="артефакта"):
        cad_service.artifact_storage_key(uuid.uuid4(), uuid.uuid4(), 1, "../x.dxf")


def test_params_v2_carry_operator_scales_and_the_idempotency_key_follows_them() -> None:
    params = cad_service.build_params([2, 0], _scales(0, 2), clean_settings())
    assert params["schema"] == "quantor.cad_engine.params.v2"
    assert params["page_selection"] == "operator"
    assert params["pages"] == [0, 2]
    assert params["scales"] == {
        "0": {"mm_per_pt": 70.5556, "calibration_id": "cal-0"},
        "2": {"mm_per_pt": 70.5556, "calibration_id": "cal-2"},
    }
    assert params["finishes"] is False and params["schedules"] is False
    revision = uuid.uuid4()
    key = cad_service.idempotency_key(revision, params)
    assert len(key) <= 128 and cad_service.ENGINE_VERSION in key
    assert key == cad_service.idempotency_key(
        revision, cad_service.build_params([0, 2], _scales(0, 2), clean_settings())
    )
    # Новая калибровка (другой id или коэффициент) — другое задание.
    other = _scales(0, 2)
    other[2] = cad_service.PageScale(mm_per_pt=70.5556, calibration_id="cal-new")
    assert key != cad_service.idempotency_key(
        revision, cad_service.build_params([0, 2], other, clean_settings())
    )
    assert key != cad_service.idempotency_key(
        revision, cad_service.build_params([0, 2], _scales(0, 2, factor=35.2778), clean_settings())
    )
    with pytest.raises(DomainError):
        cad_service.build_params([0, 1], _scales(0), clean_settings())


# Страница A3 альбомная: 1190.55 x 841.89 pt. Масштаб 1:200 -> 200 * 25.4 / 72 = 70.5556 мм/pt.
A3_WIDTH = Decimal("1190.5500")
A3_HEIGHT = Decimal("841.8900")
MM_PER_PT_1_TO_200 = 200 * 25.4 / 72
# Синтетические PDF движка (smoke.make_pdf) нарисованы в масштабе 1:100: scale = 100 * 25.4 / 72
# = 35.2778 мм/pt. Отрезок 0.1..0.6 ширины A3 (595.275 pt) равен 20999.9792 мм — калибровка,
# совпадающая с размерными цепочками чертежа. 41999.9583 мм (1:200) для них — заведомо неверна.
SYNTHETIC_KNOWN_MM = "20999.9792"
WRONG_KNOWN_MM = "41999.9583"


def test_mm_per_pt_formula_for_one_to_two_hundred() -> None:
    """Калибровка уже в мм на pt канонической геометрии: пересчёта в движок не требуется."""
    geometry = PageGeometry(
        sheet_id=uuid.uuid4(),
        display_width_pt=A3_WIDTH,
        display_height_pt=A3_HEIGHT,
        pdf_rotation=0,
        media_box=[],
        crop_box=[],
        parser_name="pypdf",
        parser_version="6.18.0",
        source_sha256="d" * 64,
        geometry_fingerprint="c" * 64,
        extracted_at=datetime.now(UTC),
    )
    # Отрезок в половину ширины листа: 595.275 pt -> 595.275 * 70.5556 = 41999.96 мм.
    distance_pt, factor = scale_service.compute_factor(
        geometry=geometry,
        point_a=(Decimal("0.1"), Decimal("0.5")),
        point_b=(Decimal("0.6"), Decimal("0.5")),
        known_distance_mm=Decimal("41999.9583"),
    )
    assert float(distance_pt) == pytest.approx(595.275)
    assert float(factor) == pytest.approx(MM_PER_PT_1_TO_200, rel=1e-6)
    assert round(float(factor), 4) == 70.5556
    scale = cad_service.page_scale_of(
        ScaleCalibration(id=uuid.uuid4(), mm_per_pt=factor, sheet_id=uuid.uuid4())
    )
    assert scale.mm_per_pt == pytest.approx(70.5556, abs=1e-4)


async def calibrate(
    session: AsyncSession,
    revision_id: str,
    *,
    pages: tuple[int, ...] = (0,),
    known_mm: str = "41999.9583",
    make_default: bool = True,
) -> dict[int, ScaleCalibration]:
    """Листы ревизии с геометрией A3 и действующей калибровкой 1:200 (как это делает человек)."""
    result: dict[int, ScaleCalibration] = {}
    for index in pages:
        sheet = (
            await session.execute(
                select(Sheet).where(
                    Sheet.revision_id == uuid.UUID(revision_id), Sheet.page_index == index
                )
            )
        ).scalar_one_or_none()
        if sheet is None:
            sheet = Sheet(revision_id=uuid.UUID(revision_id), page_index=index, rotation=0)
            session.add(sheet)
            await session.flush()
            session.add(
                PageGeometry(
                    sheet_id=sheet.id,
                    display_width_pt=A3_WIDTH,
                    display_height_pt=A3_HEIGHT,
                    pdf_rotation=0,
                    media_box=["0", "0", str(A3_WIDTH), str(A3_HEIGHT)],
                    crop_box=["0", "0", str(A3_WIDTH), str(A3_HEIGHT)],
                    parser_name="pypdf",
                    parser_version="6.18.0",
                    source_sha256="d" * 64,
                    geometry_fingerprint="c" * 64,
                    extracted_at=datetime.now(UTC),
                )
            )
            await session.flush()
        result[index] = await scale_service.create_manual(
            session,
            sheet=sheet,
            point_a=(Decimal("0.1"), Decimal("0.5")),
            point_b=(Decimal("0.6"), Decimal("0.5")),
            input_value=Decimal(known_mm),
            input_unit=LengthUnit.MM,
            created_by=None,
            make_default=make_default,
        )
    await session.commit()
    return result


async def test_pages_are_required_and_calibration_is_taken_from_the_server(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        for body in ({}, {"pages": []}, {"pages": [0, 0]}, {"pages": list(range(51))}):
            assert (await api.post(base, json=body)).status_code == 422, body
        # Клиент масштаб не передаёт.
        sneaky = await api.post(base, json={"pages": [0], "scales": {"0": {"mm_per_pt": 1}}})
        assert sneaky.status_code == 422

        # Нет листа или калибровки: 409 со списком страниц.
        refused = await api.post(base, json={"pages": [0, 3]})
        assert refused.status_code == 409
        detail = refused.json()["detail"]
        assert detail["code"] == "CAD_CALIBRATION_REQUIRED"
        assert detail["issue"] == {"pages": "0,3"}
        assert (await api.get(base)).json()["items"] == []

        # Лист есть, калибровки нет — всё равно отказ для этой страницы.
        await calibrate(db_session, revision_id, pages=(0,), make_default=False)
        still = await api.post(base, json={"pages": [0]})
        assert still.status_code == 409 and still.json()["detail"]["issue"] == {"pages": "0"}

        first = (await calibrate(db_session, revision_id, pages=(0, 3)))[0]
        created = await api.post(base, json={"pages": [3, 0]})
        assert created.status_code == 202, created.text
        job_id = created.json()["job_id"]
        job = await db_session.get(Job, uuid.UUID(job_id))
        assert job is not None
        params = job.payload["params"]
        assert params["schema"] == cad_service.PARAMS_SCHEMA
        assert params["page_selection"] == "operator" and params["pages"] == [0, 3]
        assert set(params["scales"]) == {"0", "3"}
        assert params["scales"]["0"]["calibration_id"] == str(first.id)
        assert params["scales"]["0"]["mm_per_pt"] == pytest.approx(MM_PER_PT_1_TO_200, rel=1e-6)
        assert job.payload["params_sha256"] == cad_service.params_sha256(params)
        assert "scales" not in (await api.get(f"{base}/{job_id}")).json()

        # Тот же набор — то же задание; новая действующая калибровка — новое.
        again = await api.post(base, json={"pages": [0, 3]})
        assert again.json()["job_id"] == job_id
        await calibrate(db_session, revision_id, pages=(0,), known_mm="42500")
        newer = await api.post(base, json={"pages": [0, 3]})
        assert newer.status_code == 202 and newer.json()["job_id"] != job_id


# ------------------------------------------------------------------ движок отдельно


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    if not (ENGINE_PYTHON and ENGINE_ARCHIVE):
        pytest.skip("движок не задан")
    root = tmp_path_factory.mktemp("cad-fixtures")
    result: dict[str, bytes] = {}
    for kind in ("calibrated", "scale_only", "fill_only"):
        target = root / f"{kind}.pdf"
        status, output = asyncio.run(
            _exec(
                ENGINE_PYTHON,
                "-I",
                str(RUNNER),
                "fixture",
                "--archive",
                ENGINE_ARCHIVE,
                "--kind",
                kind,
                "--out",
                str(target),
            )
        )
        assert status == 0, output
        result[kind] = target.read_bytes()
    return result


# ------------------------------------------------------------------ реальный путь Quantor


class FlakyStorage(FakeObjectStorage):
    """Хранилище, недоступное на первое чтение: проверка повторяемого отказа."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_reads = 0

    async def iter_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        if self.fail_reads:
            self.fail_reads -= 1
            raise StorageUnavailableError(key)
        async for chunk in super().iter_stream(key, chunk_size=chunk_size):
            yield chunk


@pytest.fixture
def flaky_storage() -> FlakyStorage:
    return FlakyStorage()


@pytest.fixture
def fake_storage(flaky_storage: FlakyStorage) -> FakeObjectStorage:
    return flaky_storage


async def _upload(api: AsyncClient, data: bytes, name: str = "План.pdf") -> tuple[str, str]:
    project = await api.post("/api/v1/projects", json={"name": f"CAD {uuid.uuid4().hex[:6]}"})
    project_id = str(project.json()["id"])
    response = await api.post(
        f"/api/v1/projects/{project_id}/uploads",
        files={"file": (name, data, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return project_id, str(response.json()["revision"]["id"])


async def _upload_calibrated(
    api: AsyncClient,
    session: AsyncSession,
    data: bytes,
    name: str = "План.pdf",
    *,
    known_mm: str = SYNTHETIC_KNOWN_MM,
) -> tuple[str, str]:
    """Загрузка PDF и калибровка его первого листа: без неё CAD задание не ставит.

    По умолчанию — верная калибровка синтетического PDF движка (1:100).
    """
    project_id, revision_id = await _upload(api, data, name)
    await calibrate(session, revision_id, known_mm=known_mm)
    return project_id, revision_id


async def _run_cad_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    """Один цикл выделенного исполнителя: захват только своих типов, затем его обработчик."""
    job = await jobs_service.claim(
        session,
        worker_id="cad-test",
        job_types=[t.value for t in HANDLERS],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_pdf_convert
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


def _cad_keys(storage: FakeObjectStorage) -> list[str]:
    return sorted(key for key in storage.objects if "/cad/" in key)


@needs_engine
async def test_calibrated_pdf_yields_dxf_for_review_and_repeat_is_idempotent(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path / "work")
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, fixtures["calibrated"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        created = await api.post(base, json={"pages": [0]})
        assert created.status_code == 202, created.text
        job_id = created.json()["job_id"]
        assert created.json()["status"] == "queued"

        not_ready = await api.get(f"{base}/{job_id}/artifacts/report.json")
        assert not_ready.status_code == 409
        assert not_ready.json()["detail"]["code"] == "CAD_RESULT_NOT_READY"

        # Повтор постановки — то же задание (ключ: ревизия, версия движка, SHA параметров).
        again = await api.post(base, json={"pages": [0]})
        assert again.json()["job_id"] == job_id

        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)

        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["result_status"] == "completed_requires_review"
        assert read["review_required"] is True
        [page] = read["pages"]
        assert (page["index"], page["legacy_pdf_page"]) == (0, 1)
        assert isinstance(page["intake_selected"], bool)
        [view] = page["views"]
        assert view["view"] == 1 and view["status"] == "needs_review"
        assert view["scale_status"] in ("passed", "needs_review")
        assert view["dxf"] == "views/p001_v01/plan_candidates.dxf"
        assert view["dxf_entities"] and view["failure_code"] is None
        names = {row["name"] for row in read["artifacts"]}
        assert {"report.json", "manifest.json", "views/p001_v01/plan_candidates.dxf"} <= names
        assert not any("key" in row for row in read["artifacts"])

        dxf = await api.get(f"{base}/{job_id}/artifacts/views/p001_v01/plan_candidates.dxf")
        assert dxf.status_code == 200
        assert dxf.headers["x-quantor-review-required"] == "true"
        assert hashlib.sha256(dxf.content).hexdigest() == dxf.headers["x-content-sha256"]
        assert b"AC1032" in dxf.content

        manifest = (await api.get(f"{base}/{job_id}/artifacts/manifest.json")).json()
        listed = {row["name"]: row["sha256"] for row in manifest["files"]}
        assert (
            listed["views/p001_v01/plan_candidates.dxf"] == hashlib.sha256(dxf.content).hexdigest()
        )
        assert manifest["engine"]["archive_sha256"] == cad_service.ENGINE_ARCHIVE_SHA256
        report = (await api.get(f"{base}/{job_id}/artifacts/report.json")).json()
        assert report["disabled"] == ["finishes", "schedules"]
        assert report["requested_pages"] == [{"index": 0, "legacy_pdf_page": 1}]

        unknown = await api.get(f"{base}/{job_id}/artifacts/views/p001_v01/other.dxf")
        assert unknown.status_code == 404
        encoded_traversal = await api.get(
            f"{base}/{job_id}/artifacts/views/p001_v01/%2e%2e/%2e%2e/report.json"
        )
        assert encoded_traversal.status_code == 404

        # Повтор после успеха — то же завершённое задание, новый прогон движка не ставится.
        final = await api.post(base, json={"pages": [0]})
        assert final.json()["job_id"] == job_id and final.json()["status"] == "succeeded"

    assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"


@needs_engine
async def test_calibration_without_dimension_chains_gives_dxf_marked_for_review(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    """ADR-0036 п.4–5: размерных цепочек нет, калибровка человека — DXF «требует проверки»."""
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, fixtures["scale_only"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED
        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["result_status"] == "completed_requires_review"
        assert read["review_required"] is True
        [view] = read["pages"][0]["views"]
        assert view["scale_status"] == "needs_review"
        assert view["scale_source"] == "operator_calibration"
        assert view["dxf"] == "views/p001_v01/plan_candidates.dxf" and view["failure_code"] is None
        assert any(row["name"].endswith(".dxf") for row in read["artifacts"])
        assert any(key.endswith(".dxf") for key in _cad_keys(flaky_storage))
        scale = (await api.get(f"{base}/{job_id}/artifacts/views/p001_v01/scale.json")).json()
        assert scale["status"] == "needs_review" and scale["source"] == "operator_calibration"
        assert scale["reason"] == "Калибровка не подтверждена размерами"


@needs_engine
async def test_wrong_calibration_gives_no_dxf_and_calibration_mismatch(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    """Калибровка расходится с размерными цепочками более чем на 5 % — DXF нет, причина видна."""
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(
            api, db_session, fixtures["calibrated"], known_mm=WRONG_KNOWN_MM
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED
        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["result_status"] == "no_cad_review_required"
        [view] = read["pages"][0]["views"]
        assert view["scale_status"] == "failed" and view["scale_source"] == "operator_calibration"
        assert view["failure_code"] == "calibration_mismatch"
        assert view["failure_reason"] and "калибровк" in view["failure_reason"].lower()
        assert view["dxf"] is None
        assert not any(row["name"].endswith(".dxf") for row in read["artifacts"])
        assert not any(key.endswith(".dxf") for key in _cad_keys(flaky_storage))


@needs_engine
async def test_broken_pdf_fails_without_cad_and_is_not_retryable(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == ErrorCode.CAD_INPUT_INVALID.value
        assert _cad_keys(flaky_storage) == []
        with pytest.raises(DomainError) as refused:
            await jobs_service.retry(db_session, job=job)
        assert refused.value.code is ErrorCode.JOB_NOT_RETRYABLE
        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["artifacts"] == [] and read["result_status"] == "failed"


@needs_engine
async def test_fill_only_limitation_fails_closed_and_is_reported(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, fixtures["fill_only"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == ErrorCode.CAD_ENGINE_FAILED.value
        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["known_limitation"] == "pdfcontext_empty_black_stroke_index"
        assert _cad_keys(flaky_storage) == []


@needs_engine
async def test_storage_outage_is_retried_as_the_same_job_in_a_new_attempt(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, fixtures["calibrated"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        flaky_storage.fail_reads = 1
        first = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert first.error_code == ErrorCode.STORAGE_UNAVAILABLE.value
        assert _cad_keys(flaky_storage) == []
        await jobs_service.retry(db_session, job=first)
        await db_session.commit()
        second = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert second.status is JobStatus.SUCCEEDED and second.attempt == 2
        assert cad_service.result_of(second)["attempt"] == 2
        assert _cad_keys(flaky_storage)
        assert all(f"/cad/{job_id}/attempt-2/" in key for key in _cad_keys(flaky_storage))


@needs_engine
async def test_foreign_workspace_sees_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    second_workspace: Workspace,
    fixtures: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, fixtures["calibrated"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED
        _, other_revision = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        wrong_revision = f"/api/v1/projects/{project_id}/revisions/{other_revision}/cad"
        assert (await api.get(f"{wrong_revision}/{job_id}")).status_code == 404

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        for path in (
            f"{base}/{job_id}",
            f"{base}/{job_id}/artifacts/report.json",
            f"{base}/{job_id}/artifacts/views/p001_v01/plan_candidates.dxf",
            f"/api/v1/jobs/{job_id}",
        ):
            assert (await foreign.get(path)).status_code == 404, path
        assert (await foreign.post(base, json={"pages": [0]})).status_code == 404


async def test_flag_off_closes_the_routes(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path, flag=False)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        response = await api.post(f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_runner_timeout_terminates_descendants(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib, subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)"
    )
    with pytest.raises(cad_handler.CadError) as error:
        await cad_handler._run([sys.executable, "-c", script, str(pid_file)], 2.0)
    assert error.value.code == ErrorCode.JOB_TIMEOUT
    child = Path("/proc") / pid_file.read_text() / "stat"
    for _ in range(50):
        if not child.exists() or child.read_text().split(") ", 1)[1][0] == "Z":
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("CAD subprocess survived the runner timeout")


@needs_engine
async def test_reassigned_attempt_cannot_publish_its_outputs(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky_storage: FlakyStorage,
    fixtures: dict[str, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_upload = cad_handler._upload

    async def reassign_after_upload(*args: Any, **kwargs: Any) -> Any:
        files = await original_upload(*args, **kwargs)
        job = args[1]
        await db_session.execute(
            update(Job).where(Job.id == job.id).values(worker_id="replacement", attempt=2)
        )
        await db_session.commit()
        return files

    monkeypatch.setattr(cad_handler, "_upload", reassign_after_upload)
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, fixtures["calibrated"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        job = await _run_cad_worker(db_session, flaky_storage, settings, job_id)
        assert (job.status, job.worker_id, job.attempt) == (JobStatus.RUNNING, "replacement", 2)
        assert _cad_keys(flaky_storage) == []
        result = await api.get(f"{base}/{job_id}/artifacts/report.json")
        assert result.status_code == 409
