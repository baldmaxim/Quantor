"""Автомасштаб CAD по размерным цепочкам (ADR-0045): постановка, обработчик, конвейер листов.

Движок не нужен: `_run_while_owned` подменён заглушкой, которая пишет `out/` по контракту runner
(отчёт, манифест, файлы видов). Масштаб страницы без калибровки принимается только при
`dimension_checks_passed` по размерным цепочкам; всё прочее — `CAD_AUTO_SCALE_UNCONFIRMED`.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker import handler as convert_handler
from app.cad_worker.handler import execute_cad_pdf_convert
from app.core.config import Settings
from app.domain import JobStatus
from app.errors import MESSAGES, ErrorCode
from app.models import Job, ScaleCalibration, Sheet
from app.services import cad as cad_service
from app.services import jobs as jobs_service
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload, cad_settings, calibrate

DXF = b"0\nEOF\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base(project_id: str, revision_id: str) -> str:
    return f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"


async def _calibration_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(ScaleCalibration)) or 0)


# ------------------------------------------------------------------ постановка


async def test_auto_scale_is_required_for_uncalibrated_pages(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        base = _base(project_id, revision_id)

        refused = await api.post(base, json={"pages": [0]})
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "CAD_CALIBRATION_REQUIRED"
        explicit = await api.post(base, json={"pages": [0], "auto_scale": False})
        assert explicit.status_code == 409

        created = await api.post(base, json={"pages": [0], "auto_scale": True})
        assert created.status_code == 202, created.text
        job = await db_session.get(Job, uuid.UUID(created.json()["job_id"]))
        assert job is not None
        params = job.payload["params"]
        assert params["schema"] == cad_service.PARAMS_SCHEMA and params["pages"] == [0]
        assert params["scales"] == {"0": {"auto": True}}
        assert job.payload["params_sha256"] == cad_service.params_sha256(params)
        assert job.payload["engine_version"] == cad_service.ENGINE_VERSION
        # Калибровка при автомасштабе не создаётся: обмер и площади требуют калибровки человека.
        assert await _calibration_count(db_session) == 0

        again = await api.post(base, json={"pages": [0], "auto_scale": True})
        assert again.json()["job_id"] == str(job.id)


async def test_calibrated_page_keeps_the_human_scale_with_auto_scale(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        base = _base(project_id, revision_id)
        first = (await calibrate(db_session, revision_id, pages=(0,)))[0]
        only_calibrated = await api.post(base, json={"pages": [0]})
        assert only_calibrated.status_code == 202

        mixed = await api.post(base, json={"pages": [3, 0], "auto_scale": True})
        assert mixed.status_code == 202, mixed.text
        job = await db_session.get(Job, uuid.UUID(mixed.json()["job_id"]))
        assert job is not None
        scales = job.payload["params"]["scales"]
        assert scales["3"] == {"auto": True}
        assert set(scales["0"]) == {"mm_per_pt", "calibration_id"}
        assert scales["0"]["calibration_id"] == str(first.id)
        # Тот же лист с калибровкой не зависит от флага: задание то же, что и без него.
        same = await api.post(base, json={"pages": [0], "auto_scale": True})
        assert same.json()["job_id"] == only_calibrated.json()["job_id"]
        assert same.json()["job_id"] != mixed.json()["job_id"]


# ------------------------------------------------------------------ обработчик


def _view(status: str | None, source: str | None, *, dxf: bool) -> dict[str, Any]:
    folder = "views/p001_v01"
    row: dict[str, Any] = {
        "view": 1,
        "status": "needs_review",
        "scale_status": status,
        "scale_source": source,
        "scale_deviation": None,
    }
    if dxf:
        row["dxf"] = {"file": f"{folder}/plan_candidates.dxf", "entities": 5}
    return row


def _engine_report(pages: list[dict[str, Any]], *, with_dxf: bool) -> Any:
    """Заглушка движка: пишет `out/` для одной страницы (каталог вида p001_v01)."""

    async def fake_engine(
        session: AsyncSession,
        job: Job,
        owner: str | None,
        attempt: int,
        argv: list[str],
        **_: Any,
    ) -> tuple[int, bytes]:
        out = Path(argv[argv.index("--out") + 1])
        files = {"views/p001_v01/scale.json": b"{}"}
        if with_dxf:
            files["views/p001_v01/plan_candidates.dxf"] = DXF
            files["views/p001_v01/preview.json"] = b"{}"
        rows = []
        for name, data in files.items():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(data)
            rows.append({"name": name, "sha256": _sha(data), "size": len(data)})
        report = {
            "status": cad_service.RESULT_WITH_CAD if with_dxf else cad_service.RESULT_NO_CAD,
            "disabled": ["finishes", "schedules"],
            "pages": pages,
        }
        report_bytes = json.dumps(report).encode()
        (out / "report.json").write_bytes(report_bytes)
        rows.append(
            {"name": "report.json", "sha256": _sha(report_bytes), "size": len(report_bytes)}
        )
        manifest = {
            "files": rows,
            "engine": {
                "archive_sha256": cad_service.ENGINE_ARCHIVE_SHA256,
                "version": cad_service.ENGINE_VERSION,
            },
            "input": {"sha256": _sha(BROKEN_PDF)},
            "params_sha256": job.payload["params_sha256"],
        }
        (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return 0, b""

    return fake_engine


def _handler_settings(tmp_path: Path) -> Settings:
    return cad_settings(tmp_path / "work").model_copy(
        update={
            "cad_engine_python": sys.executable,
            "cad_engine_runner": sys.executable,
            "cad_engine_archive": sys.executable,
        }
    )


async def _run_convert(
    session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    pages: list[dict[str, Any]],
    *,
    with_dxf: bool,
) -> Job:
    async def nothing(*_: Any, **__: Any) -> list[Job]:
        return []

    monkeypatch.setattr(
        convert_handler, "_run_while_owned", _engine_report(pages, with_dxf=with_dxf)
    )
    monkeypatch.setattr(convert_handler.cad_walls, "enqueue_after_convert", nothing)
    monkeypatch.setattr(convert_handler.cad_zones_auto, "enqueue_after_convert", nothing)
    job = await jobs_service.claim(
        session, worker_id="cad-test", job_types=[t.value for t in HANDLERS], lease_seconds=600
    )
    await session.commit()
    assert job is not None
    job = await execute_cad_pdf_convert(session, job, storage, settings)
    await session.commit()
    return job


def _page(index: int, view: dict[str, Any]) -> dict[str, Any]:
    return {"index": index, "legacy_pdf_page": index + 1, "views": [view]}


@pytest.mark.parametrize(
    ("status", "source"),
    [
        ("needs_review", "dimension_chains"),
        ("printed_scale_only", "dimension_chains"),
        ("failed", "dimension_chains"),
        ("unknown", "dimension_chains"),
        ("dimension_checks_passed", "printed_scale_only"),
        ("dimension_checks_passed", None),
        (None, None),
    ],
)
async def test_unconfirmed_auto_scale_fails_the_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str | None,
    source: str | None,
) -> None:
    settings = _handler_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        created = await api.post(
            _base(project_id, revision_id), json={"pages": [0], "auto_scale": True}
        )
        assert created.status_code == 202
        job = await _run_convert(
            db_session,
            fake_storage,
            settings,
            monkeypatch,
            [_page(0, _view(status, source, dxf=False))],
            with_dxf=False,
        )
        assert job.status is JobStatus.FAILED
        assert job.error_code == ErrorCode.CAD_AUTO_SCALE_UNCONFIRMED.value
        assert job.error_message == MESSAGES[ErrorCode.CAD_AUTO_SCALE_UNCONFIRMED]
        assert "откалибруйте лист вручную" in (job.error_message or "")
        result = job.payload["cad_result"]
        assert result["unconfirmed_pages"] == [0] and result["result_status"] == "failed"
        assert not [key for key in fake_storage.objects if "/cad/" in key]

        shown = (await api.get(f"{_base(project_id, revision_id)}/{job.id}")).json()
        assert shown["error_code"] == "CAD_AUTO_SCALE_UNCONFIRMED"
        assert shown["retryable"] is False
        assert "Откалибруйте лист вручную" in shown["retry_blocked_reason"]


async def test_confirmed_auto_scale_succeeds_and_keeps_the_source(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _handler_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        await api.post(_base(project_id, revision_id), json={"pages": [0], "auto_scale": True})
        job = await _run_convert(
            db_session,
            fake_storage,
            settings,
            monkeypatch,
            [_page(0, _view("dimension_checks_passed", "dimension_chains", dxf=True))],
            with_dxf=True,
        )
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        [view] = job.payload["cad_result"]["pages"][0]["views"]
        assert view["scale_status"] == "dimension_checks_passed"
        assert view["scale_source"] == "dimension_chains"
        assert await _calibration_count(db_session) == 0


async def test_calibrated_page_is_not_judged_by_the_auto_rule(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Калиброванный лист проверяется как раньше: масштаб оператора, а не автомасштаб."""
    settings = _handler_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        await calibrate(db_session, revision_id, pages=(0,))
        await api.post(_base(project_id, revision_id), json={"pages": [0], "auto_scale": True})
        job = await _run_convert(
            db_session,
            fake_storage,
            settings,
            monkeypatch,
            [_page(0, _view("needs_review", "operator_calibration", dxf=True))],
            with_dxf=True,
        )
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)


async def test_one_unconfirmed_auto_page_fails_a_mixed_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _handler_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        await calibrate(db_session, revision_id, pages=(0,))
        await api.post(_base(project_id, revision_id), json={"pages": [0, 3], "auto_scale": True})
        job = await _run_convert(
            db_session,
            fake_storage,
            settings,
            monkeypatch,
            [
                _page(0, _view("passed", "operator_calibration", dxf=True)),
                _page(3, _view("needs_review", "dimension_chains", dxf=False)),
            ],
            with_dxf=True,
        )
        assert job.status is JobStatus.FAILED
        assert job.error_code == "CAD_AUTO_SCALE_UNCONFIRMED"
        assert job.payload["cad_result"]["unconfirmed_pages"] == [3]


# ------------------------------------------------------------------ конвейер листов


async def _add_sheet(session: AsyncSession, revision_id: str, index: int, label: str) -> None:
    session.add(
        Sheet(revision_id=uuid.UUID(revision_id), page_index=index, page_label=label, rotation=0)
    )
    await session.commit()


async def test_pipeline_lists_plan_sheets_without_work_and_reports_the_scale_source(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        base = _base(project_id, revision_id)
        labels = {
            0: "План 1 этажа",
            1: "Генплан",
            2: "Разрез 1-1",
            3: "Планы этажей",
            4: "Схема планировочной организации",
            5: "Фрагмент плана",
        }
        for index, label in labels.items():
            if index != 1:
                await _add_sheet(db_session, revision_id, index, label)
        # Лист 1 (не план) калиброван, лист 2 (не план) без работы и калибровки.
        await calibrate(db_session, revision_id, pages=(1,))
        await db_session.execute(
            update(Sheet)
            .where(Sheet.revision_id == uuid.UUID(revision_id), Sheet.page_index == 1)
            .values(page_label=labels[1])
        )
        await db_session.commit()
        assert (await api.post(base, json={"pages": [0], "auto_scale": True})).status_code == 202
        assert (await api.post(base, json={"pages": [1]})).status_code == 202

        response = await api.get(f"{base}/pipeline")
        assert response.status_code == 200, response.text
        sheets = {row["page_index"]: row for row in response.json()["sheets"]}
        # Не-план без работы и без калибровки (лист 2) и «планировочная организация» (4) не входят.
        assert sorted(sheets) == [0, 1, 3, 5]
        assert (sheets[0]["title"], sheets[0]["is_plan"]) == ("План 1 этажа", True)
        assert sheets[0]["scale_source"] == "auto" and sheets[0]["convert"] is not None
        assert sheets[0]["calibrated"] is False
        assert (sheets[1]["title"], sheets[1]["is_plan"]) == ("Генплан", False)
        assert sheets[1]["scale_source"] == "calibration" and sheets[1]["calibrated"] is True
        for index in (3, 5):
            assert sheets[index]["is_plan"] is True
            assert sheets[index]["convert"] is None and sheets[index]["views"] == []
            assert sheets[index]["calibrated"] is False and sheets[index]["scale_source"] is None
