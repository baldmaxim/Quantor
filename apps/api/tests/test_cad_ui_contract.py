"""PDF -> CAD, интерфейс QA-контура: ход попыток, история, повтор, диагностика вида, просмотр.

Дополняет `test_cad_qa.py` (базовый патч). Тесты без базы проверяют разбор снимка runner,
порядок событий, политику повтора и вывод причин HOLD. Тесты с движком идут через настоящие
API загрузки и постановки и выделенный исполнитель с runner в отдельном процессе.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus
from app.main import create_app
from app.models import Job, Workspace
from app.openapi_export import export
from app.services import cad as cad_service
from app.services import cad_progress, cad_views
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_qa import (
    BROKEN_PDF,
    ENGINE_ARCHIVE,
    ENGINE_PYTHON,
    RUNNER,
    WRONG_KNOWN_MM,
    FlakyStorage,
    _exec,
    _run_cad_worker,
    _upload,
    _upload_calibrated,
    cad_settings,
    needs_engine,
)

AT = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
STAGES = list(cad_progress.STAGE_KEYS)


@pytest.fixture(scope="module")
def pdfs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    """Синтетические PDF штатным генератором архива движка (как в test_cad_qa)."""
    if not (ENGINE_PYTHON and ENGINE_ARCHIVE):
        pytest.skip("движок не задан")
    root = tmp_path_factory.mktemp("cad-ui-fixtures")
    result: dict[str, bytes] = {}
    for kind in ("calibrated", "scale_only", "fill_only"):
        target = root / f"{kind}.pdf"
        argv = (ENGINE_PYTHON, "-I", str(RUNNER), "fixture", "--archive", ENGINE_ARCHIVE)
        status, output = asyncio.run(_exec(*argv, "--kind", kind, "--out", str(target)))
        assert status == 0, output
        result[kind] = target.read_bytes()
    return result


@pytest.fixture
def flaky() -> FlakyStorage:
    return FlakyStorage()


@pytest.fixture
def fake_storage(flaky: FlakyStorage) -> FakeObjectStorage:
    """Подменяет хранилище API тем же объектом, которым пользуется исполнитель в тесте."""
    return flaky


def _snapshot(seq: int, phase: str, views: list[dict[str, Any]] | None = None) -> bytes:
    return json.dumps(
        {
            "schema": cad_progress.PROGRESS_SCHEMA,
            "seq": seq,
            "phase": phase,
            "phase_detail": "деталь",
            "pages": {"total": 2, "planned": [0], "requested": [0]},
            "engine": None,
            "views": views or [],
            "error": None,
        }
    ).encode()


def _view(stages: list[dict[str, Any]], status: str = "running") -> dict[str, Any]:
    return {
        "index": 0,
        "legacy_pdf_page": 1,
        "view": 1,
        "status": status,
        "stage": "Масштаб",
        "ready": False,
        "stages": stages,
    }


# ------------------------------------------------------------------ без базы


def test_snapshot_is_validated_and_bounded() -> None:
    assert cad_progress.parse_snapshot(b"not json") is None
    assert cad_progress.parse_snapshot(b'{"schema": "other", "seq": 1, "phase": "verify"}') is None
    assert cad_progress.parse_snapshot(_snapshot(1, "made_up_phase")) is None
    # Вид с рассогласованной нумерацией страниц (index + 1 != legacy) отбрасывается.
    bad = _view([{"key": "source", "status": "done"}]) | {"legacy_pdf_page": 5}
    parsed = cad_progress.parse_snapshot(_snapshot(1, "worker", [bad]))
    assert parsed is not None and parsed["views"] == []
    # Неизвестный этап и неизвестный статус не проходят как есть.
    odd = _view([{"key": "finishes", "status": "done"}, {"key": "scale", "status": "hacked"}])
    parsed = cad_progress.parse_snapshot(_snapshot(2, "worker", [odd]))
    assert parsed is not None
    assert [(s["key"], s["status"]) for s in parsed["views"][0]["stages"]] == [("scale", "unknown")]


def test_events_follow_snapshots_in_order_and_stale_snapshots_are_ignored() -> None:
    payload = cad_progress.begin_attempt({}, 1, AT)
    first = cad_progress.parse_snapshot(
        _snapshot(3, "worker", [_view([{"key": "source", "status": "running"}])])
    )
    assert first is not None
    payload, added = cad_progress.apply_snapshot(payload, 1, first, AT)
    assert added == 3  # фаза, вид, этап
    stale = cad_progress.parse_snapshot(_snapshot(2, "intake"))
    assert stale is not None
    payload, added = cad_progress.apply_snapshot(payload, 1, stale, AT)
    assert added == 0, "снимок со старым номером не применяется"
    second = cad_progress.parse_snapshot(
        _snapshot(
            4,
            "worker",
            [
                _view(
                    [
                        {"key": "source", "status": "done", "elapsed_s": 0.1},
                        {"key": "geometry", "status": "running", "completed": 3, "total": 9},
                    ]
                )
            ],
        )
    )
    assert second is not None
    payload, added = cad_progress.apply_snapshot(payload, 1, second, AT)
    assert added == 2  # source: running -> done, geometry: новый
    record = cad_progress.attempt_record(payload, 1)
    assert record is not None
    seqs = [event["seq"] for event in record["events"]]
    assert seqs == list(range(1, len(seqs) + 1))
    assert all(event["attempt"] == 1 for event in record["events"])
    geometry = record["events"][-1]
    assert (geometry["stage"], geometry["completed"], geometry["total"]) == ("geometry", 3, 9)
    # Завершённая попытка новых событий не принимает.
    payload = cad_progress.finish_attempt(payload, 1, AT, outcome="failed", error_code="X")
    again = cad_progress.parse_snapshot(_snapshot(9, "collect"))
    assert again is not None
    assert cad_progress.apply_snapshot(payload, 1, again, AT)[1] == 0
    # Новая попытка начинает свою нумерацию, прежняя остаётся в истории.
    payload = cad_progress.begin_attempt(payload, 2, AT)
    assert [row["attempt"] for row in cad_progress.attempts_of(payload)] == [1, 2]
    second_record = cad_progress.attempt_record(payload, 2)
    assert second_record is not None and second_record["events"][0]["seq"] == 1


def test_event_log_is_bounded() -> None:
    payload = cad_progress.begin_attempt({}, 1, AT)
    for seq in range(2, cad_progress.MAX_EVENTS_PER_ATTEMPT + 50):
        snapshot = cad_progress.parse_snapshot(_snapshot(seq, "worker" if seq % 2 else "collect"))
        assert snapshot is not None
        payload, _ = cad_progress.apply_snapshot(payload, 1, snapshot, AT)
    record = cad_progress.attempt_record(payload, 1)
    assert record is not None
    assert len(record["events"]) == cad_progress.MAX_EVENTS_PER_ATTEMPT
    assert record["events_dropped"] > 0


def test_previous_attempt_result_is_not_current() -> None:
    job = Job(attempt=2, payload={"cad_result": {"attempt": 1, "result_status": "failed"}})
    assert cad_service.current_result(job) == {}
    job.attempt = 1
    assert cad_service.current_result(job)["result_status"] == "failed"


def test_retry_state_explains_every_refusal() -> None:
    def job(status: JobStatus, code: str | None = None) -> Job:
        return Job(status=status, error_code=code, attempt=1, payload={})

    assert cad_service.retry_state(job(JobStatus.FAILED, "STORAGE_UNAVAILABLE")) == (True, None)
    assert cad_service.retry_state(job(JobStatus.FAILED, "JOB_LEASE_LOST"))[0] is True
    for status, code in (
        (JobStatus.RUNNING, None),
        (JobStatus.QUEUED, None),
        (JobStatus.SUCCEEDED, None),
        (JobStatus.FAILED, "CAD_INPUT_INVALID"),
        (JobStatus.FAILED, "CAD_ENGINE_FAILED"),
        (JobStatus.FAILED, "SOMETHING_NEW"),
    ):
        allowed, reason = cad_service.retry_state(job(status, code))
        assert allowed is False and reason, (status, code)


def test_hold_reasons_and_frame() -> None:
    held = {"status": "unknown", "controls": [], "printed_scale_labels": [100]}
    reasons = cad_views.hold_reasons(held)
    assert any("размерных цепочек" in r for r in reasons)
    assert any("по надписи" in r for r in reasons)
    scale = cad_views.scale_from(held)
    assert scale is not None and scale.passed is False
    frame = cad_views.frame_from(scale, {"units": "mm", "origin_pdf_display_pt": [1.0, 2.0]})
    assert frame.confirmed is False and frame.reason

    passed = {
        "status": "dimension_checks_passed",
        "mm_per_pdf_point_fitted": 35.2,
        "fit_controls": 2,
        "heldout_controls": 2,
        "controls": [{"role": "fit", "within_tolerance": True, "endpoints_pt": [[0, 0], [1, 0]]}],
    }
    assert cad_views.hold_reasons(passed) == []
    scale = cad_views.scale_from(passed)
    frame = cad_views.frame_from(scale, {"units": "mm", "origin_pdf_display_pt": [1.0, 2.0]})
    assert frame.confirmed is True and frame.origin_pt == (1.0, 2.0)
    assert cad_views.frame_from(scale, None).confirmed is False


def test_operator_scale_diagnostics_and_frame() -> None:
    needs_review = {
        "status": "needs_review",
        "source": "operator_calibration",
        "operator_mm_per_pt": 70.5556,
        "dimension_mm_per_pt": 68.9,
        "deviation": 0.023,
        "tolerances": {"warn": 0.01, "fail": 0.05, "bad": "x"},
        "reason": "Отклонение 2,3% выше допуска проверки",
    }
    scale = cad_views.scale_from(needs_review)
    assert scale is not None and scale.passed is False
    assert scale.source == "operator_calibration"
    assert scale.operator_mm_per_pt == 70.5556 and scale.dimension_mm_per_pt == 68.9
    assert scale.deviation == 0.023 and scale.tolerances == {"warn": 0.01, "fail": 0.05}
    assert scale.mm_per_pdf_point == 70.5556
    assert cad_views.hold_reasons(needs_review)[0].startswith("Отклонение")
    checks = {"units": "mm", "origin_pdf_display_pt": [1.0, 2.0]}
    assert cad_views.frame_from(scale, checks).confirmed is True

    by_chains = cad_views.scale_from({**needs_review, "source": "dimension_chains"})
    assert by_chains is not None and cad_views.frame_from(by_chains, checks).confirmed is False
    failed = cad_views.scale_from({**needs_review, "status": "failed"})
    assert failed is not None and cad_views.frame_from(failed, checks).confirmed is False
    passed = cad_views.scale_from(
        {"status": "passed", "source": "operator_calibration", "operator_mm_per_pt": 35.0}
    )
    assert passed is not None and passed.passed is True
    assert cad_views.hold_reasons({"status": "passed"}) == []
    assert cad_views.frame_from(passed, checks).mm_per_pdf_point == 35.0


def test_contract_is_exported_for_the_client_and_routes_are_always_mounted(
    tmp_path: Path,
) -> None:
    target = tmp_path / "openapi.json"
    export(target)
    paths = json.loads(target.read_text(encoding="utf-8"))["paths"]
    base = "/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
    for suffix in (
        "",
        "/{job_id}",
        "/{job_id}/retry",
        "/{job_id}/events",
        "/{job_id}/views/{page_index}/{view}",
        "/{job_id}/views/{page_index}/{view}/preview",
    ):
        assert base + suffix in paths, suffix
    # ADR-0036: маршруты подключены всегда; закрывает их флаг пространства, а не гейт сборки.
    assert base in create_app(clean_settings()).openapi()["paths"]


# ------------------------------------------------------------------ реальный путь Quantor


@needs_engine
async def test_live_events_diagnostics_preview_and_download(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky: FlakyStorage,
    pdfs: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, pdfs["calibrated"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        listed = (await api.get(base)).json()
        assert [row["job_id"] for row in listed["items"]] == [job_id]

        queued = (await api.get(f"{base}/{job_id}")).json()
        assert queued["attempts"] == [] and queued["retryable"] is False
        assert queued["retry_blocked_reason"]

        job = await _run_cad_worker(db_session, flaky, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED

        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["result_attempt"] == 1
        [attempt] = read["attempts"]
        assert attempt["outcome"] == "succeeded"
        assert attempt["result_status"] == "completed_requires_review"
        assert attempt["pages"] == {"total": 1, "planned": [0], "requested": [0]}
        [view] = attempt["views"]
        assert [stage["key"] for stage in view["stages"]] == STAGES
        assert all(stage["elapsed_s"] is not None for stage in view["stages"])

        events = (await api.get(f"{base}/{job_id}/events")).json()
        seqs = [event["seq"] for event in events["events"]]
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
        assert events["finished"] is True and events["attempt"] == 1
        phases = [e["phase"] for e in events["events"] if e["scope"] == "document"]
        for phase in ("claimed", "download", "verify", "intake", "worker", "publish", "published"):
            assert phase in phases, phase
        assert phases.index("verify") < phases.index("worker") < phases.index("published")
        staged = {e["stage"] for e in events["events"] if e["scope"] == "view" and e["stage"]}
        assert staged == set(STAGES)
        # Курсор: только новее указанного номера.
        tail = (await api.get(f"{base}/{job_id}/events", params={"after_seq": seqs[-3]})).json()
        assert [e["seq"] for e in tail["events"]] == seqs[-2:]
        assert (await api.get(f"{base}/{job_id}/events", params={"attempt": 7})).status_code == 404

        diagnostics = (await api.get(f"{base}/{job_id}/views/0/1")).json()
        assert diagnostics["scale"]["passed"] is True
        assert diagnostics["scale"]["fit_controls"] > 0
        assert diagnostics["scale"]["heldout_controls"] > 0
        assert diagnostics["scale"]["hold_reasons"] == []
        assert diagnostics["frame"]["confirmed"] is True
        assert diagnostics["engineering_acceptance"] == "not_accepted"
        assert diagnostics["dxf"]["name"] == "views/p001_v01/plan_candidates.dxf"
        assert diagnostics["preview_available"] is True
        assert "revisions/" not in json.dumps(diagnostics), "ключ хранилища не уходит наружу"

        preview = (await api.get(f"{base}/{job_id}/views/0/1/preview")).json()
        assert preview["units"] == "mm" and preview["paths"] and preview["layers"]
        assert preview["dxf_sha256"] == diagnostics["dxf"]["sha256"]
        dxf = await api.get(f"{base}/{job_id}/artifacts/views/p001_v01/plan_candidates.dxf")
        assert hashlib.sha256(dxf.content).hexdigest() == preview["dxf_sha256"]

        assert (await api.get(f"{base}/{job_id}/views/0/2")).status_code == 404
        assert (await api.get(f"{base}/{job_id}/views/3/1")).status_code == 404


@needs_engine
async def test_wrong_calibration_gives_diagnostics_without_dxf_or_frame(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky: FlakyStorage,
    pdfs: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(
            api, db_session, pdfs["calibrated"], known_mm=WRONG_KNOWN_MM
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        await _run_cad_worker(db_session, flaky, settings, job_id)
        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["result_status"] == "no_cad_review_required"
        stages = read["attempts"][0]["views"][0]["stages"]
        assert stages[-1]["key"] == "scale" and stages[-1]["status"] == "needs_review"
        diagnostics = (await api.get(f"{base}/{job_id}/views/0/1")).json()
        assert diagnostics["dxf"] is None and diagnostics["preview_available"] is False
        assert diagnostics["scale"]["passed"] is False and diagnostics["scale"]["hold_reasons"]
        assert diagnostics["frame"]["confirmed"] is False
        assert (await api.get(f"{base}/{job_id}/views/0/1/preview")).status_code == 404


@needs_engine
async def test_failed_attempt_keeps_stages_and_retry_runs_a_new_attempt(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky: FlakyStorage,
    pdfs: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        # Отказ движка: этапы вида с ошибкой сохраняются, повтор не предлагается.
        project_id, revision_id = await _upload_calibrated(api, db_session, pdfs["fill_only"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        await _run_cad_worker(db_session, flaky, settings, job_id)
        read = (await api.get(f"{base}/{job_id}")).json()
        assert read["status"] == "failed" and read["retryable"] is False
        assert "детерминирован" in read["retry_blocked_reason"]
        [attempt] = read["attempts"]
        assert attempt["outcome"] == "failed" and attempt["error_code"] == "CAD_ENGINE_FAILED"
        error_stage = attempt["views"][0]["stages"][-1]
        assert (error_stage["key"], error_stage["status"]) == ("geometry", "error")
        refused = await api.post(f"{base}/{job_id}/retry")
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "JOB_NOT_RETRYABLE"
        assert (await api.get(f"{base}/{job_id}/views/0/1")).status_code == 409

        # Повторяемый отказ хранилища: повтор — то же задание, новая попытка со своими событиями.
        project_id, revision_id = await _upload_calibrated(
            api, db_session, pdfs["calibrated"], "Второй.pdf"
        )
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        flaky.fail_reads = 1
        await _run_cad_worker(db_session, flaky, settings, job_id)
        failed = (await api.get(f"{base}/{job_id}")).json()
        assert failed["error_code"] == "STORAGE_UNAVAILABLE" and failed["retryable"] is True
        assert failed["result_attempt"] == 1 and failed["artifacts"] == []
        retried = await api.post(f"{base}/{job_id}/retry")
        assert retried.status_code == 200, retried.text
        body = retried.json()
        assert body["status"] == "queued" and body["result_status"] is None
        assert body["result_attempt"] is None, "итог первой попытки не выдаётся текущим"
        second = await api.post(f"{base}/{job_id}/retry")
        assert second.status_code == 409, "повтор поставленного задания не дублируется"
        assert (await api.post(base, json={"pages": [0]})).json()["job_id"] == job_id

        await _run_cad_worker(db_session, flaky, settings, job_id)
        done = (await api.get(f"{base}/{job_id}")).json()
        assert done["status"] == "succeeded" and done["result_attempt"] == 2
        assert [(a["attempt"], a["outcome"]) for a in done["attempts"]] == [
            (1, "failed"),
            (2, "succeeded"),
        ]
        first_events = (await api.get(f"{base}/{job_id}/events", params={"attempt": 1})).json()
        assert all(e["attempt"] == 1 for e in first_events["events"])
        assert first_events["events"][-1]["status"] == "error"
        assert not any(e["phase"] == "worker" for e in first_events["events"])


@needs_engine
async def test_foreign_workspace_cannot_read_ui_routes(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    flaky: FlakyStorage,
    second_workspace: Workspace,
    pdfs: dict[str, bytes],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, pdfs["calibrated"])
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
        await _run_cad_worker(db_session, flaky, settings, job_id)

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        for path in (
            base,
            f"{base}/{job_id}/events",
            f"{base}/{job_id}/views/0/1",
            f"{base}/{job_id}/views/0/1/preview",
        ):
            assert (await foreign.get(path)).status_code == 404, path
        assert (await foreign.post(f"{base}/{job_id}/retry")).status_code == 404


async def test_ui_routes_are_closed_without_flag(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path, flag=False)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        job = uuid.uuid4()
        for method, path in (
            ("GET", base),
            ("GET", f"{base}/{job}/events"),
            ("POST", f"{base}/{job}/retry"),
            ("GET", f"{base}/{job}/views/0/1"),
        ):
            response = await api.request(method, path)
            assert response.status_code == 403, (method, path)
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"
