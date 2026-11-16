"""Предпросмотр профиля оформления по образцам (ADR-0049, шаг 4): задание, обработчик, принятие.

Движок не нужен: runner подменён заглушкой, которая по CLI-контракту подкоманды `style` пишет в
`--out` `result.json`, `preview.json` и (если подпись есть) `style_profile.json`. Режим заглушки
задаёт файл `mode` рядом со скриптом: `no_signature`, `input_invalid`, `huge`, `bad_result`.
"""

from __future__ import annotations

import copy
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker.style_preview_handler import _runner_failure, execute_cad_style_preview
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadStyleProfileVersion, DocumentRevision, Job, Project, Workspace
from app.services import cad as cad_service
from app.services import jobs as jobs_service
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload, _upload_calibrated, cad_settings
from tests.test_cad_style_profiles import PROFILE, body, samples_source, url

STUB = """
import argparse, json, pathlib, sys

parser = argparse.ArgumentParser()
parser.add_argument("command")
for name in ("input", "samples", "work", "out", "base-profile", "archive",
             "expect-archive-sha256", "max-memory-mb"):
    parser.add_argument("--" + name)
args = parser.parse_args()
here = pathlib.Path(__file__).parent
mode = (here / "mode").read_text().strip() if (here / "mode").exists() else ""
samples = json.loads(pathlib.Path(args.samples).read_text(encoding="utf-8"))
base = args.base_profile
(here / "args.json").write_text(json.dumps({
    "command": args.command,
    "max_memory_mb": args.max_memory_mb,
    "has_pdf": pathlib.Path(args.input).is_file(),
    "samples": samples,
    "base": json.loads(pathlib.Path(base).read_text(encoding="utf-8")) if base else None,
}))
if mode == "input_invalid":
    error = {"code": "input_invalid", "message": "Образцы: страницы 9 нет в PDF"}
    print(json.dumps({"error": error}))
    sys.exit(2)
out = pathlib.Path(args.out)
status = "no_signature" if mode == "no_signature" else "profile"
(out / "result.json").write_text(json.dumps({
    "status": "profile" if mode == "bad_result" else status,
    "engine_version": %(version)r,
    "archive_sha256": %(sha)r,
}))
preview = {"schema": "cad_engine.style_preview.v1",
           "field_sources": {"monolith_fill_gray": "samples"}}
if mode == "huge":
    preview["blob"] = "x" * 300000
(out / "preview.json").write_text(json.dumps(preview))
if status == "profile" and mode != "bad_result":
    profile = %(profile)r
    if mode == "wide_pen":
        profile = dict(profile, door_pen_max_width=6, shaft_labels=["x"] * 60)
    style = {"schema": "cad_engine.style_profile.v1", "id": samples["profile_id"],
             "version": samples["profile_version"], "profile": profile}
    (out / "style_profile.json").write_text(json.dumps(style))
"""

SAMPLES = [
    {"class": "monolith", "x": 0.25, "y": 0.5, "negative": False},
    {"class": "door", "x": 0.5, "y": 0.75, "negative": True},
]


@pytest.fixture
def stub_runner(tmp_path: Path) -> Path:
    root = tmp_path / "tools"
    root.mkdir()
    script = root / "runner.py"
    script.write_text(
        STUB
        % {
            "version": cad_service.ENGINE_VERSION,
            "sha": cad_service.ENGINE_ARCHIVE_SHA256,
            "profile": PROFILE,
        },
        encoding="utf-8",
    )
    (root / "engine.zip").write_bytes(b"zip")
    return script


def worker_settings(runner: Path, tmp_path: Path, *, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_engine_runner=str(runner),
        cad_engine_archive=str(runner.parent / "engine.zip"),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


def previews_url(project_id: str, document_id: str, tail: str = "") -> str:
    return url(project_id, document_id, f"/previews{tail}")


def preview_body(revision_id: str, **changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "revision_id": revision_id,
        "page_index": 0,
        "samples": copy.deepcopy(SAMPLES),
    }
    result.update(changes)
    return result


async def setup(
    api: AsyncClient, session: AsyncSession, *, calibrated: bool = False
) -> tuple[str, str, str]:
    if calibrated:
        project_id, revision_id = await _upload_calibrated(api, session, BROKEN_PDF)
    else:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
    document_id = await session.scalar(
        select(DocumentRevision.document_id).where(DocumentRevision.id == uuid.UUID(revision_id))
    )
    assert document_id is not None
    return project_id, str(document_id), revision_id


async def queue(api: AsyncClient, project_id: str, document_id: str, revision_id: str) -> str:
    response = await api.post(previews_url(project_id, document_id), json=preview_body(revision_id))
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


async def run_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session,
        worker_id="cad-style-test",
        job_types=[t.value for t in HANDLERS],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_style_preview
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


async def make_job(session: AsyncSession, job_id: str) -> Job:
    job = await session.get(Job, uuid.UUID(job_id), populate_existing=True)
    assert job is not None
    return job


def accept_body(job_id: str, expected: int | None = None, **changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"job_id": job_id, "expected_current_version": expected}
    result.update(changes)
    return result


# ------------------------------------------------------------------ без базы


def test_routes_and_job_type_are_registered() -> None:
    paths = create_app(clean_settings(environment="test")).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/documents/{document_id}/cad/style-profile"
    assert "post" in paths[f"{base}/previews"]
    assert "get" in paths[f"{base}/previews/{{job_id}}"]
    assert "post" in paths[f"{base}/versions/from-preview"]
    assert JobType.CAD_STYLE_PREVIEW in HANDLERS


# ------------------------------------------------------------------ постановка


async def test_schedule_puts_samples_scale_none_and_base_into_the_payload(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        job = await make_job(db_session, job_id)
        assert job.job_type is JobType.CAD_STYLE_PREVIEW and job.status is JobStatus.QUEUED
        payload = job.payload
        assert payload["document_id"] == document_id and payload["revision_id"] == revision_id
        assert payload["page_index"] == 0 and payload["samples"] == SAMPLES
        # Калибровки и успешного преобразования нет: масштаб честно неизвестен, не подставляется.
        assert payload["mm_per_pt"] is None and payload["scale_source"] == "none"
        assert payload["base_version"] is None
        assert payload["engine_version"] == cad_service.ENGINE_VERSION
        # Тот же вход - то же задание.
        assert await queue(api, project_id, document_id, revision_id) == job_id

        created = await api.post(url(project_id, document_id, "/versions"), json=body())
        assert created.status_code == 201
        newer = await queue(api, project_id, document_id, revision_id)
        assert newer != job_id
        assert (await make_job(db_session, newer)).payload["base_version"] == 1


async def test_schedule_takes_the_scale_from_the_sheet_calibration(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, document_id, revision_id = await setup(api, db_session, calibrated=True)
        job_id = await queue(api, project_id, document_id, revision_id)
        payload = (await make_job(db_session, job_id)).payload
        assert payload["scale_source"] == "calibration"
        assert payload["mm_per_pt"] == pytest.approx(35.2778, abs=1e-3)


async def seed_convert(
    session: AsyncSession,
    storage: FakeObjectStorage,
    *,
    project_id: str,
    revision_id: str,
    views: dict[int, tuple[str, float]],
    scales: dict[str, Any] | None = None,
    report_only_views: tuple[int, ...] = (),
) -> None:
    """Успешное преобразование листа 0: виды со статусом масштаба и их `scale.json`."""
    project = uuid.UUID(project_id)
    owner = await session.get(Project, project)
    assert owner is not None
    job = await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_PDF_CONVERT,
        workspace_id=owner.workspace_id,
        project_id=project,
        payload={
            "revision_id": revision_id,
            "params": {"pages": [0], "scales": scales or {"0": {"auto": True}}},
        },
    )
    artifacts: list[dict[str, Any]] = []
    pages_views: list[dict[str, Any]] = []
    for view, (status, factor) in views.items():
        name = f"{cad_service.view_folder(0, view)}/scale.json"
        key = cad_service.artifact_storage_key(uuid.UUID(revision_id), job.id, 1, name)
        data = json.dumps(
            {"status": status, "source": "dimension_chains", "mm_per_pdf_point_fitted": factor}
        ).encode()
        await storage.put_bytes(key, data, content_type="application/json")
        artifacts.append({"name": name, "key": key, "sha256": "0" * 64, "size": len(data)})
        pages_views.append(
            {"view": view, "scale_status": status, "scale_source": "dimension_chains"}
        )
    pages_views += [
        {"view": v, "scale_status": "dimension_checks_passed", "scale_source": "dimension_chains"}
        for v in report_only_views
    ]
    job.status = JobStatus.SUCCEEDED
    job.attempt = 1
    job.payload = {
        **job.payload,
        "cad_result": {
            "attempt": 1,
            "result_status": "completed_requires_review",
            "pages": [{"index": 0, "views": pages_views}],
            "artifacts": artifacts,
        },
    }
    await session.commit()


async def test_schedule_takes_a_checked_auto_scale_and_refuses_unchecked_or_ambiguous(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    passed = "dimension_checks_passed"
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        # Надпись «М 1:100» и непроверенный масштаб основанием не служат.
        project_id, document_id, revision_id = await setup(api, db_session)
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={1: ("printed_scale_only", 70.0)},
        )
        job = await make_job(db_session, await queue(api, project_id, document_id, revision_id))
        assert job.payload["scale_source"] == "none" and job.payload["mm_per_pt"] is None

        project_id, document_id, revision_id = await setup(api, db_session)
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={1: (passed, 70.1), 2: ("needs_review", 12.0)},
        )
        job = await make_job(db_session, await queue(api, project_id, document_id, revision_id))
        assert job.payload["scale_source"] == "cad_auto" and job.payload["mm_per_pt"] == 70.1

        # Виды листа с разным масштабом: выбирать один из них молча нельзя.
        project_id, document_id, revision_id = await setup(api, db_session)
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={1: (passed, 70.1), 2: (passed, 35.0)},
        )
        job = await make_job(db_session, await queue(api, project_id, document_id, revision_id))
        assert job.payload["scale_source"] == "none" and job.payload["mm_per_pt"] is None


async def test_auto_scale_follows_the_conversion_gate_only(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    passed = "dimension_checks_passed"
    human = {"0": {"mm_per_pt": 70.0, "calibration_id": "gone"}}
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        # Лист шёл с калибровкой человека, её потом сняли: автомасштаба у него нет.
        project_id, document_id, revision_id = await setup(api, db_session)
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={1: (passed, 70.1)},
            scales=human,
        )
        job = await make_job(db_session, await queue(api, project_id, document_id, revision_id))
        assert job.payload["scale_source"] == "none" and job.payload["mm_per_pt"] is None

        # Старое автопреобразование не перебирается, если последнее было с калибровкой человека.
        project_id, document_id, revision_id = await setup(api, db_session)
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={1: (passed, 70.1)},
        )
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={1: (passed, 70.1)},
            scales=human,
        )
        job = await make_job(db_session, await queue(api, project_id, document_id, revision_id))
        assert job.payload["scale_source"] == "none"

        # Номер вида вне пределов папок артефактов - нет масштаба, а не 500.
        project_id, document_id, revision_id = await setup(api, db_session)
        await seed_convert(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            views={},
            report_only_views=(100,),
        )
        job = await make_job(db_session, await queue(api, project_id, document_id, revision_id))
        assert job.payload["scale_source"] == "none"


async def test_manual_write_cannot_forge_the_preview_origin(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        forged = samples_source(revision_id, preview_job_id=str(uuid.uuid4()))
        response = await api.post(
            url(project_id, document_id, "/versions"), json=body(source=forged)
        )
        assert response.status_code == 422
        assert (
            await db_session.scalar(select(func.count()).select_from(CadStyleProfileVersion))
        ) == 0


def test_code_four_is_a_timeout_only_by_the_runner_error_code() -> None:
    timeout = json.dumps({"error": {"code": "timeout", "message": "время"}}).encode()
    limit = json.dumps({"error": {"code": "limit_exceeded", "message": "предел"}}).encode()
    assert _runner_failure(4, timeout).code.value == "JOB_TIMEOUT"
    assert _runner_failure(4, limit).code.value == "CAD_INPUT_LIMIT_EXCEEDED"
    assert _runner_failure(4, b"").code.value == "CAD_INPUT_LIMIT_EXCEEDED"
    assert _runner_failure(2, limit).code.value == "CAD_INPUT_INVALID"


async def test_schedule_validates_revision_and_samples(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        _, _, foreign_revision = await setup(api, db_session)
        target = previews_url(project_id, document_id)
        # Ревизия другого тома.
        response = await api.post(target, json=preview_body(foreign_revision))
        assert response.status_code == 422
        # Несуществующая ревизия - тот же отказ: ревизия обязана быть ревизией этого тома.
        unknown = await api.post(target, json=preview_body(str(uuid.uuid4())))
        assert unknown.status_code == 422
        bad_inputs: list[dict[str, Any]] = [
            {"samples": []},
            {"samples": SAMPLES * 101},
            {"samples": [{"class": "wall", "x": 0.1, "y": 0.1, "negative": False}]},
            {"samples": [{"class": "door", "x": 1.5, "y": 0.1, "negative": False}]},
            {"page_index": -1},
        ]
        for bad in bad_inputs:
            assert (
                await api.post(target, json=preview_body(revision_id, **bad))
            ).status_code == 422, bad
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.job_type == JobType.CAD_STYLE_PREVIEW)
            )
        ) == 0


# ------------------------------------------------------------------ обработчик и чтение результата


async def test_handler_profile_result_reaches_the_read_api(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session, calibrated=True)
        job_id = await queue(api, project_id, document_id, revision_id)
        queued = (await api.get(previews_url(project_id, document_id, f"/{job_id}"))).json()
        assert queued["status"] == "queued" and queued["result"] is None

        job = await run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"
        seen = json.loads((stub_runner.parent / "args.json").read_text(encoding="utf-8"))
        assert seen["command"] == "style" and seen["has_pdf"] is True and seen["base"] is None
        assert seen["max_memory_mb"] == str(settings.cad_max_memory_mb)
        samples = seen["samples"]
        assert samples["schema"] == "cad_engine.style_samples.v1"
        assert samples["profile_id"] == f"d-{uuid.UUID(document_id).hex}"
        assert samples["profile_version"] == 1 and samples["page_index"] == 0
        assert samples["samples"] == SAMPLES
        assert samples["mm_per_pt"] == pytest.approx(35.2778, abs=1e-3)

        read = (await api.get(previews_url(project_id, document_id, f"/{job_id}"))).json()
        assert read["status"] == "succeeded" and read["error_code"] is None
        result = read["result"]
        assert result["result_status"] == "profile" and result["profile"] == PROFILE
        assert result["preview"]["field_sources"] == {"monolith_fill_gray": "samples"}
        assert result["base_version"] is None and result["scale_source"] == "calibration"
        assert result["engine_version"] == cad_service.ENGINE_VERSION
        assert result["revision_id"] == revision_id and result["page_index"] == 0


async def test_handler_no_signature_is_a_result_without_a_profile(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    (stub_runner.parent / "mode").write_text("no_signature", encoding="utf-8")
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        job = await run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED
        result = (await api.get(previews_url(project_id, document_id, f"/{job_id}"))).json()[
            "result"
        ]
        assert result["result_status"] == "no_signature" and result["profile"] is None
        assert result["mm_per_pt"] is None and result["scale_source"] == "none"
        seen = json.loads((stub_runner.parent / "args.json").read_text(encoding="utf-8"))
        assert "mm_per_pt" not in seen["samples"]
        # Принимать нечего.
        accepted = await api.post(
            url(project_id, document_id, "/versions/from-preview"), json=accept_body(job_id)
        )
        assert accepted.status_code == 409
        assert accepted.json()["detail"]["code"] == "CAD_STYLE_PREVIEW_NOT_READY"


async def test_handler_passes_the_current_version_as_the_base_profile(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        created = await api.post(url(project_id, document_id, "/versions"), json=body())
        job_id = await queue(api, project_id, document_id, revision_id)
        assert (await run_worker(db_session, fake_storage, settings, job_id)).status is (
            JobStatus.SUCCEEDED
        )
        seen = json.loads((stub_runner.parent / "args.json").read_text(encoding="utf-8"))
        assert seen["base"] == created.json()["style"]
        result = (await api.get(previews_url(project_id, document_id, f"/{job_id}"))).json()[
            "result"
        ]
        assert result["base_version"] == 1


async def test_runner_input_error_fails_the_job_with_the_input_code(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    (stub_runner.parent / "mode").write_text("input_invalid", encoding="utf-8")
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        job = await run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == "CAD_INPUT_INVALID" and "страницы 9" in (job.error_message or "")
        read = (await api.get(previews_url(project_id, document_id, f"/{job_id}"))).json()
        assert read["status"] == "failed" and read["result"] is None
        assert read["error_code"] == "CAD_INPUT_INVALID"
        assert not any((tmp_path / "work").rglob("*"))


@pytest.mark.parametrize("mode", ["huge", "bad_result"])
async def test_output_outside_the_contract_fails_the_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
    mode: str,
) -> None:
    (stub_runner.parent / "mode").write_text(mode, encoding="utf-8")
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        job = await run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_ENGINE_FAILED"


# ------------------------------------------------------------------ границы арендатора и тома


async def test_foreign_workspace_other_document_and_other_type_are_not_found(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        _, other_document, _ = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        # Тот же проект, другой том.
        assert (
            await api.get(previews_url(project_id, other_document, f"/{job_id}"))
        ).status_code == 404
        assert (
            await api.get(previews_url(project_id, document_id, f"/{uuid.uuid4()}"))
        ).status_code == 404
        # Задание другого типа (преобразование) предпросмотром не читается.
        convert = await jobs_service.enqueue(
            db_session,
            job_type=JobType.CAD_PDF_CONVERT,
            workspace_id=(await make_job(db_session, job_id)).workspace_id,
            project_id=uuid.UUID(project_id),
            payload={"revision_id": revision_id, "document_id": document_id},
        )
        await db_session.commit()
        assert (
            await api.get(previews_url(project_id, document_id, f"/{convert.id}"))
        ).status_code == 404
        accepted = await api.post(
            url(project_id, document_id, "/versions/from-preview"), json=accept_body(job_id)
        )
        assert accepted.status_code == 409  # задание своё, но не выполнено
        other = await api.post(
            url(project_id, other_document, "/versions/from-preview"), json=accept_body(job_id)
        )
        assert other.status_code == 404
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (
            await foreign.get(previews_url(project_id, document_id, f"/{job_id}"))
        ).status_code == 404
        posted = await foreign.post(
            previews_url(project_id, document_id), json=preview_body(revision_id)
        )
        assert posted.status_code == 404
        accepted = await foreign.post(
            url(project_id, document_id, "/versions/from-preview"), json=accept_body(job_id)
        )
        assert accepted.status_code == 404


async def test_preview_routes_are_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    fake = str(uuid.uuid4())
    async with build_api(make_context(), settings=cad_settings(tmp_path, flag=False)) as api:
        for method, tail, payload in (
            ("post", "/previews", preview_body(fake)),
            ("get", f"/previews/{fake}", None),
            ("post", "/versions/from-preview", accept_body(fake)),
        ):
            response = await api.request(method, url(fake, fake, tail), json=payload)
            assert response.status_code == 403, (method, tail)
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", (method, tail)


# ------------------------------------------------------------------ принятие


async def test_accept_creates_the_version_from_the_job_result_not_from_the_client(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        target = url(project_id, document_id, "/versions/from-preview")
        # Задание ещё в очереди.
        early = await api.post(target, json=accept_body(job_id))
        assert early.status_code == 409
        assert early.json()["detail"]["code"] == "CAD_STYLE_PREVIEW_NOT_READY"

        await run_worker(db_session, fake_storage, settings, job_id)
        # Клиентских полей профиля тело не принимает.
        smuggled = await api.post(target, json=accept_body(job_id, profile=PROFILE))
        assert smuggled.status_code == 422

        accepted = await api.post(target, json=accept_body(job_id, title="По образцам"))
        assert accepted.status_code == 201, accepted.text
        version = accepted.json()
        assert version["version"] == 1 and version["title"] == "По образцам"
        assert version["style"]["profile"] == PROFILE
        assert version["style"]["id"] == f"d-{uuid.UUID(document_id).hex}"
        assert version["style"]["version"] == 1
        # Масштаб листа был неизвестен: честный null в происхождении, ключ на месте.
        assert version["source"] == {
            "kind": "samples",
            "revision_id": revision_id,
            "page_index": 0,
            "samples": SAMPLES,
            "mm_per_pt": None,
            "preview_job_id": job_id,
        }
        row = (await db_session.scalars(select(CadStyleProfileVersion))).one()
        assert row.sha256 == version["sha256"]
        read = (await api.get(url(project_id, document_id))).json()
        assert read["current"]["version"] == 1

        # Тот же предпросмотр повторно: профиль с тех пор изменился, он устарел.
        again = await api.post(target, json=accept_body(job_id, 1))
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "CAD_STYLE_PROFILE_VERSION_CONFLICT"
        assert (
            await db_session.scalar(select(func.count()).select_from(CadStyleProfileVersion))
        ) == 1


async def test_accept_refuses_a_stale_preview_and_a_wrong_expected_version(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        target = url(project_id, document_id, "/versions/from-preview")
        job_id = await queue(api, project_id, document_id, revision_id)
        await run_worker(db_session, fake_storage, settings, job_id)
        # Пока человек смотрел предпросмотр, версию завёл кто-то другой.
        assert (
            await api.post(url(project_id, document_id, "/versions"), json=body())
        ).status_code == 201
        for expected in (None, 1):
            stale = await api.post(target, json=accept_body(job_id, expected))
            assert stale.status_code == 409, expected
            assert stale.json()["detail"]["code"] == "CAD_STYLE_PROFILE_VERSION_CONFLICT"
            assert stale.json()["detail"]["issue"] == {"current_version": 1}

        # Новый предпросмотр поверх версии 1: ожидание версии обязано совпасть.
        fresh = await queue(api, project_id, document_id, revision_id)
        await run_worker(db_session, fake_storage, settings, fresh)
        wrong = await api.post(target, json=accept_body(fresh, None))
        assert wrong.status_code == 409
        ok = await api.post(target, json=accept_body(fresh, 1))
        assert ok.status_code == 201 and ok.json()["version"] == 2
        assert ok.json()["style"]["version"] == 2
        assert ok.json()["source"]["preview_job_id"] == fresh


async def test_out_of_limits_profile_is_reported_and_cannot_be_accepted(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    (stub_runner.parent / "mode").write_text("wide_pen", encoding="utf-8")
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        job = await run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED
        result = (await api.get(previews_url(project_id, document_id, f"/{job_id}"))).json()[
            "result"
        ]
        assert result["result_status"] == "profile_out_of_limits" and result["profile"] is None
        assert result["preview"]["field_sources"] == {"monolith_fill_gray": "samples"}
        reasons = result["reasons"]
        assert any(row.startswith("door_pen_max_width: ") for row in reasons)
        assert any(row.startswith("shaft_labels: ") for row in reasons)
        # Входные значения в причины не попадают.
        assert not any("6" in row or "x" in row.split(": ")[-1] for row in reasons)
        response = await api.post(
            url(project_id, document_id, "/versions/from-preview"), json=accept_body(job_id)
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CAD_STYLE_PREVIEW_NOT_READY"


async def test_accept_runs_the_result_body_through_the_strict_contract(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    stub_runner: Path,
    tmp_path: Path,
) -> None:
    settings = worker_settings(stub_runner, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session)
        job_id = await queue(api, project_id, document_id, revision_id)
        job = await run_worker(db_session, fake_storage, settings, job_id)
        assert cad_service.result_of(job)["result_status"] == "profile"
        # Результат подменён уже после исполнителя: принять его нельзя, и это не 500.
        result = copy.deepcopy(cad_service.result_of(job))
        result["profile"] = {**result["profile"], "extra_field": 1}
        job.payload = {**job.payload, "cad_result": result}
        await db_session.commit()
        response = await api.post(
            url(project_id, document_id, "/versions/from-preview"), json=accept_body(job_id)
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CAD_STYLE_PREVIEW_NOT_READY"
        assert (
            await db_session.scalar(select(func.count()).select_from(CadStyleProfileVersion))
        ) == 0


# ------------------------------------------------------------------ преобразование с профилем


async def test_convert_carries_the_current_profile_and_without_one_stays_as_before(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, document_id, revision_id = await setup(api, db_session, calibrated=True)
        convert_url = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"

        plain = await api.post(convert_url, json={"pages": [0]})
        assert plain.status_code == 202, plain.text
        assert plain.json()["style_profile"] is None
        before = await make_job(db_session, plain.json()["job_id"])
        scales = await cad_service.resolve_scales(
            db_session,
            revision=(await _revision(db_session, revision_id)),
            pages=[0],
        )
        expected = cad_service.build_params([0], scales, settings)
        # Без профиля параметры побайтно прежние и ключа профиля в них нет.
        assert before.payload["params"] == expected
        assert "style_profile" not in before.payload["params"]
        assert "style_profile" not in before.payload
        assert before.payload["params_sha256"] == cad_service.params_sha256(expected)
        assert cad_service.params_bytes(before.payload["params"]) == cad_service.params_bytes(
            expected
        )

        created = (await api.post(url(project_id, document_id, "/versions"), json=body())).json()
        with_profile = await api.post(convert_url, json={"pages": [0]})
        assert with_profile.status_code == 202
        assert with_profile.json()["job_id"] != plain.json()["job_id"]
        assert with_profile.json()["style_profile"] == {
            "version": 1,
            "sha256": created["sha256"],
        }
        job = await make_job(db_session, with_profile.json()["job_id"])
        assert job.payload["params"]["style_profile"] == created["style"]
        assert job.payload["style_profile"] == {"version": 1, "sha256": created["sha256"]}
        assert {k: v for k, v in job.payload["params"].items() if k != "style_profile"} == expected
        assert job.payload["params_sha256"] == cad_service.params_sha256(job.payload["params"])
        assert job.payload["params_sha256"] != before.payload["params_sha256"]

        # Следующая версия профиля - другие параметры и другое задание.
        second = (
            await api.post(
                url(project_id, document_id, "/versions"), json=body(expected_current_version=1)
            )
        ).json()
        newest = await api.post(convert_url, json={"pages": [0]})
        assert newest.json()["style_profile"]["version"] == 2
        assert newest.json()["job_id"] not in (
            with_profile.json()["job_id"],
            plain.json()["job_id"],
        )
        assert second["version"] == 2


async def _revision(session: AsyncSession, revision_id: str) -> Any:
    revision = await session.get(DocumentRevision, uuid.UUID(revision_id))
    assert revision is not None
    return revision
