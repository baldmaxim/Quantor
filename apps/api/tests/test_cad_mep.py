"""Трассы механики (ADR-0036 п. 8): гейты решений, постановка, обработчик cad-worker.

Движок и настоящий генератор не нужны: родитель `cad_pdf_convert` выставляется прямо в базе и
хранилище, как его оставил бы исполнитель, а генератор подменён скриптом-заглушкой, которая пишет
файлы по CLI-контракту. Результат заглушки выбирает отметка пола: 99999 - код выхода 2, 88888 -
код 3, 77777 - не хватает файла, остальное - успех.
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
from app.cad_worker.mep_handler import execute_cad_mep_route
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadDecision, Job, Workspace
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import jobs as jobs_service
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload_calibrated

FOLDER = "views/p001_v01"
PARENT_DXF = b"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1032\n0\nENDSEC\n0\nEOF\n"
PARAMS = {"pipe_diameter": {"value": 50, "unit": "mm", "source": "assumed", "note": "тест"}}

STUB = """
import argparse, json, pathlib, sys

parser = argparse.ArgumentParser()
for name in ("pdf", "page-index", "view-dxf", "scale", "preview", "params", "out", "view-folder",
             "floor-elevation-mm", "floor-height-mm", "approval-id"):
    parser.add_argument("--" + name)
args = parser.parse_args()
for name in ("pdf", "view_dxf", "scale", "preview", "params"):
    if not pathlib.Path(getattr(args, name)).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
elevation = int(args.floor_elevation_mm)
if elevation == 99999:
    print(json.dumps({"code": "scale_missing", "message": "Нет масштаба вида"}), file=sys.stderr)
    sys.exit(2)
if elevation == 88888:
    print("служебная строка", file=sys.stderr)
    print(json.dumps({"code": "no_risers", "message": "Стояки не найдены"}), file=sys.stderr)
    sys.exit(3)
folder = pathlib.Path(args.out) / "views" / args.view_folder
folder.mkdir(parents=True)
(folder / "mep_routes.dxf").write_bytes(b"0\\nSECTION\\n9\\n$ACADVER\\n1\\nAC1032\\n0\\nEOF\\n")
(folder / "preview.json").write_text(json.dumps({
    "schema": "quantor.cad_engine.preview.v1", "units": "mm", "layers": ["M-OV-T1"],
    "paths": [{"layer": 0, "closed": False, "fill": False, "points": [0, 0, 1000, 0]}],
    "bbox": [0, 0, 1000, 0], "truncated": False, "flatten_mm": 0}))
if elevation != 77777:
    (folder / "candidate.json").write_text(json.dumps({
        "schema": "quantor.cad_mep.candidate.v1",
        "floor_elevation_mm": elevation, "floor_height_mm": int(args.floor_height_mm),
        "page_index": int(args.page_index)}))
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    """Параметры, версия и заглушка генератора: то, что в образе лежит в tools/cad_mep."""
    root = tmp_path / "tools" / "cad_mep"
    (root / "params").mkdir(parents=True)
    (root / "cad_mep").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "cad_mep" / "version.py").write_text('GENERATOR_VERSION = "cad_mep.v1"\n')
    (root / "run_mep.py").write_text(STUB, encoding="utf-8")
    return root


def mep_settings(tools: Path, tmp_path: Path, *, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_mep_runner=str(tools / "run_mep.py"),
        cad_mep_params=str(tools / "params" / "v1.json"),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


async def _parent(
    api: AsyncClient, session: AsyncSession, storage: FakeObjectStorage
) -> tuple[str, str, str, str]:
    """Проект, ревизия, успешное задание CAD с видом p001_v01 и базовый адрес."""
    project_id, revision_id = await _upload_calibrated(api, session, BROKEN_PDF)
    base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
    job_id = (await api.post(base, json={"pages": [0]})).json()["job_id"]
    files = {
        "plan_candidates.dxf": PARENT_DXF,
        "scale.json": json.dumps(
            {
                "status": "needs_review",
                "source": "operator_calibration",
                "operator_mm_per_pt": 35.2778,
            }
        ).encode(),
        "cad_checks.json": json.dumps({"units": "mm", "origin_pdf_display_pt": [10, 20]}).encode(),
        "preview.json": b"{}",
    }
    artifacts = []
    for name, data in files.items():
        full = f"{FOLDER}/{name}"
        key = cad_service.artifact_storage_key(uuid.UUID(revision_id), uuid.UUID(job_id), 1, full)
        await storage.put_bytes(key, data, content_type="application/octet-stream")
        artifacts.append({"name": full, "sha256": _sha(data), "size": len(data), "key": key})
    job = await session.get(Job, uuid.UUID(job_id))
    assert job is not None
    payload = {
        **job.payload,
        "cad_result": {
            "attempt": 1,
            "result_status": "completed_requires_review",
            "pages": [
                {
                    "index": 0,
                    "legacy_pdf_page": 1,
                    "views": [
                        {
                            "view": 1,
                            "status": "needs_review",
                            "scale_status": "needs_review",
                            "scale_source": "operator_calibration",
                            "scale_deviation": 0.01,
                            "failure_code": None,
                            "failure_reason": None,
                            "dxf": f"{FOLDER}/plan_candidates.dxf",
                            "dxf_entities": 10,
                        }
                    ],
                }
            ],
            "artifacts": artifacts,
        },
    }
    await session.execute(
        update(Job)
        .where(Job.id == uuid.UUID(job_id))
        .values(status=JobStatus.SUCCEEDED, attempt=1, payload=payload)
    )
    await session.commit()
    session.expire_all()
    return project_id, revision_id, job_id, base


APPROVAL = {"attempt": 1, "comment": "Вид проверен"}


def _routes_body(elevation: int = 47600, height: int = 3300) -> dict[str, int]:
    return {"attempt": 1, "floor_elevation_mm": elevation, "floor_height_mm": height}


async def _approve_and_queue(
    api: AsyncClient, base: str, job_id: str, elevation: int = 47600
) -> str:
    view = f"{base}/{job_id}/views/0/1"
    assert (await api.post(f"{view}/approval", json=APPROVAL)).status_code == 201
    queued = await api.post(f"{view}/mep-routes", json=_routes_body(elevation))
    assert queued.status_code == 202, queued.text
    return str(queued.json()["job_id"])


async def _run_route_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session, worker_id="cad-mep-test", job_types=[t.value for t in HANDLERS], lease_seconds=600
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_mep_route
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


def _remark(dxf_sha: str | None, status: str = "open") -> dict[str, Any]:
    return {
        "type": "route",
        "comment": "Трасса идёт через стену",
        "reviewer": "Иванов",
        "status": status,
        "bbox_pt": [10.0, 20.0, 110.0, 120.0],
        "dxf_sha256": dxf_sha,
    }


# ------------------------------------------------------------------ без базы


def test_new_routes_are_in_openapi_and_job_type_is_registered() -> None:
    base = "/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}"
    paths = create_app(clean_settings()).openapi()["paths"]
    assert f"{base}/views/{{page_index}}/{{view}}/approval" in paths
    assert f"{base}/views/{{page_index}}/{{view}}/mep-routes" in paths
    assert f"{base}/acceptance" in paths
    assert set(HANDLERS) == {JobType.CAD_PDF_CONVERT, JobType.CAD_MEP_ROUTE}
    assert JobType.CAD_MEP_ROUTE.value == "cad_mep_route"


def test_route_artifact_names_are_closed_and_dxf_needs_the_route_pattern() -> None:
    revision, job = uuid.uuid4(), uuid.uuid4()
    for name in ("mep_routes.dxf", "candidate.json", "preview.json"):
        key = cad_service.artifact_storage_key(revision, job, 1, f"{FOLDER}/{name}")
        assert key.endswith(f"/attempt-1/{FOLDER}/{name}")
    for bad in (f"{FOLDER}/other.dxf", "mep_routes.dxf", f"{FOLDER}/../mep_routes.dxf"):
        with pytest.raises(ValueError, match="артефакта"):
            cad_service.artifact_storage_key(revision, job, 1, bad)


def test_params_hash_and_version_come_from_files(tools: Path, tmp_path: Path) -> None:
    settings = mep_settings(tools, tmp_path)
    params = cad_mep_service.load_params(settings)
    assert params.generator_version == "cad_mep.v1"
    assert params.sha256 == cad_service.params_sha256(PARAMS)
    (tools / "cad_mep" / "version.py").unlink()
    with pytest.raises(Exception, match="не найдены"):
        cad_mep_service.load_params(settings)


async def test_new_routes_are_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    tools: Path,
    tmp_path: Path,
) -> None:
    base = f"/api/v1/projects/{uuid.uuid4()}/revisions/{uuid.uuid4()}/cad/{uuid.uuid4()}"
    async with build_api(make_context(), settings=mep_settings(tools, tmp_path, flag=False)) as api:
        for path in (
            f"{base}/views/0/1/approval",
            f"{base}/views/0/1/mep-routes",
            f"{base}/acceptance",
        ):
            response = await api.post(path, json={})
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", path


# ------------------------------------------------------------------ гейты и постановка


async def test_approval_gates_and_route_scheduling(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=mep_settings(tools, tmp_path)) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        view = f"{base}/{job_id}/views/0/1"

        # Без одобрения трассы не строятся.
        refused = await api.post(f"{view}/mep-routes", json=_routes_body())
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "CAD_VIEW_NOT_APPROVED"

        # Отметки - ввод человека, обе обязательны и в пределах.
        for body in (
            {"attempt": 1, "floor_elevation_mm": 1000},
            {"attempt": 1, "floor_height_mm": 3000},
            _routes_body(height=1999),
            _routes_body(height=6001),
            {**_routes_body(), "extra": 1},
        ):
            assert (await api.post(f"{view}/mep-routes", json=body)).status_code == 422, body

        # Открытое замечание блокирует одобрение.
        remark = f"{base}/{job_id}/remarks/{uuid.uuid4()}?attempt=1&page_index=0&view=1"
        assert (await api.put(remark, json=_remark(_sha(PARENT_DXF)))).status_code == 200
        blocked = await api.post(f"{view}/approval", json=APPROVAL)
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "CAD_OPEN_REMARKS"
        assert (
            await api.put(remark, json=_remark(_sha(PARENT_DXF), "resolved"))
        ).status_code == 200

        # Чужая попытка, неизвестный вид, пустое тело.
        assert (await api.post(f"{view}/approval", json={"attempt": 2})).status_code == 409
        assert (
            await api.post(f"{base}/{job_id}/views/0/9/approval", json=APPROVAL)
        ).status_code == 404
        assert (await api.post(f"{view}/approval", json={})).status_code == 422

        approved = await api.post(f"{view}/approval", json=APPROVAL)
        assert approved.status_code == 201, approved.text
        decision = approved.json()
        assert decision["kind"] == "view_approval" and decision["attempt"] == 1
        assert decision["artifact_sha256"] == _sha(PARENT_DXF)
        assert decision["comment"] == "Вид проверен" and decision["decided_by"]
        repeated = await api.post(f"{view}/approval", json=APPROVAL)
        assert repeated.status_code == 409
        assert repeated.json()["detail"]["code"] == "CAD_ALREADY_DECIDED"
        count = await db_session.scalar(select(func.count()).select_from(CadDecision))
        assert count == 1

        queued = await api.post(f"{view}/mep-routes", json=_routes_body())
        assert queued.status_code == 202, queued.text
        route = queued.json()
        assert route["job_type"] == "cad_mep_route" and route["status"] == "queued"
        assert route["parent_job_id"] == job_id and route["parent_attempt"] == 1
        assert (route["page_index"], route["view"]) == (0, 1)
        assert (route["floor_elevation_mm"], route["floor_height_mm"]) == (47600, 3300)
        assert route["generator_version"] == "cad_mep.v1"

        stored = await db_session.get(Job, uuid.UUID(route["job_id"]))
        assert stored is not None and stored.job_type is JobType.CAD_MEP_ROUTE
        assert stored.payload["approval_id"] == decision["id"]
        assert stored.payload["params_sha256"] == cad_service.params_sha256(PARAMS)
        assert stored.payload["view_dxf_sha256"] == _sha(PARENT_DXF)

        # Идемпотентность: то же одобрение, параметры, версия и отметки - то же задание.
        again = await api.post(f"{view}/mep-routes", json=_routes_body())
        assert again.json()["job_id"] == route["job_id"]
        other = await api.post(f"{view}/mep-routes", json=_routes_body(elevation=50900))
        assert other.status_code == 202 and other.json()["job_id"] != route["job_id"]

        # Родитель показывает одобрение и route-задания вида; список - тип и родителя.
        parent = (await api.get(f"{base}/{job_id}")).json()
        assert parent["job_type"] == "cad_pdf_convert" and parent["parent_job_id"] is None
        [row] = parent["pages"][0]["views"]
        assert row["approval"]["id"] == decision["id"]
        assert row["acceptance"] is None
        assert {r["job_id"] for r in row["route_jobs"]} == {route["job_id"], other.json()["job_id"]}
        listed = {i["job_id"]: i for i in (await api.get(base)).json()["items"]}
        assert listed[route["job_id"]]["job_type"] == "cad_mep_route"
        assert listed[route["job_id"]]["parent_job_id"] == job_id
        assert (listed[route["job_id"]]["page_index"], listed[route["job_id"]]["view"]) == (0, 1)
        assert listed[job_id]["job_type"] == "cad_pdf_convert"

        # До успеха принять нечего.
        early = await api.post(f"{base}/{route['job_id']}/acceptance", json=APPROVAL)
        assert early.status_code == 409
        assert early.json()["detail"]["code"] == "CAD_RESULT_NOT_READY"
        # Одобрение и постановка - только для задания-преобразования, принятие - только для трасс.
        assert (
            await api.post(f"{base}/{route['job_id']}/views/0/1/approval", json=APPROVAL)
        ).status_code == 404
        assert (await api.post(f"{base}/{job_id}/acceptance", json=APPROVAL)).status_code == 404


async def test_foreign_workspace_cannot_decide_or_schedule(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        for path, body in (
            (f"{base}/{job_id}/views/0/1/approval", APPROVAL),
            (f"{base}/{job_id}/views/0/1/mep-routes", _routes_body()),
            (f"{base}/{route_id}/acceptance", APPROVAL),
        ):
            assert (await foreign.post(path, json=body)).status_code == 404, path
        assert (await foreign.get(f"{base}/{route_id}")).status_code == 404


# ------------------------------------------------------------------ обработчик cad-worker


async def test_worker_builds_routes_and_acceptance_opens_the_dxf(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        route = f"{base}/{route_id}"

        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"

        read = (await api.get(route)).json()
        assert read["job_type"] == "cad_mep_route" and read["status"] == "succeeded"
        assert read["result_status"] == "completed_requires_review"
        assert read["requested_pages"] == [0] and read["result_attempt"] == 1
        names = {row["name"] for row in read["artifacts"]}
        assert names == {
            "report.json",
            "manifest.json",
            f"{FOLDER}/mep_routes.dxf",
            f"{FOLDER}/preview.json",
            f"{FOLDER}/candidate.json",
        }
        [view] = read["pages"][0]["views"]
        assert view["dxf"] == f"{FOLDER}/mep_routes.dxf" and view["acceptance"] is None
        assert all(
            f"/cad/{route_id}/attempt-1/" in k for k in fake_storage.objects if route_id in k
        )

        # Кандидат и превью видны всегда, DXF трасс - только после принятия.
        candidate = await api.get(f"{route}/artifacts/{FOLDER}/candidate.json")
        assert candidate.status_code == 200
        assert candidate.json()["floor_elevation_mm"] == 47600
        assert candidate.json()["floor_height_mm"] == 3300 and candidate.json()["page_index"] == 0
        assert (await api.get(f"{route}/artifacts/{FOLDER}/preview.json")).status_code == 200
        manifest = (await api.get(f"{route}/artifacts/manifest.json")).json()
        assert {f["name"] for f in manifest["files"]} == names - {"manifest.json"}
        closed = await api.get(f"{route}/artifacts/{FOLDER}/mep_routes.dxf")
        assert closed.status_code == 409
        assert closed.json()["detail"]["code"] == "CAD_ROUTES_NOT_ACCEPTED"

        diagnostics = (await api.get(f"{route}/views/0/1")).json()
        assert diagnostics["dxf"]["name"] == f"{FOLDER}/mep_routes.dxf"
        assert diagnostics["preview_available"] is True and diagnostics["checks"] is None
        assert diagnostics["frame"]["confirmed"] is True, diagnostics["frame"]
        preview = await api.get(f"{route}/views/0/1/preview")
        assert preview.status_code == 200, preview.text
        assert preview.json()["layers"] == ["M-OV-T1"] and preview.json()["point_count"] == 2
        assert preview.json()["dxf_sha256"] == diagnostics["dxf"]["sha256"]

        # Замечание «Трасса» привязано к DXF трасс; открытое блокирует принятие.
        routes_sha = diagnostics["dxf"]["sha256"]
        key = uuid.uuid4()
        url = f"{route}/remarks/{key}?attempt=1&page_index=0&view=1"
        wrong = await api.put(url, json=_remark(_sha(PARENT_DXF)))
        assert wrong.status_code == 422
        assert wrong.json()["detail"]["code"] == "CAD_REMARKS_BINDING_MISMATCH"
        assert (await api.put(url, json=_remark(routes_sha))).status_code == 200
        blocked = await api.post(f"{route}/acceptance", json=APPROVAL)
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "CAD_OPEN_REMARKS"
        assert (await api.put(url, json=_remark(routes_sha, "resolved"))).status_code == 200

        accepted = await api.post(f"{route}/acceptance", json=APPROVAL)
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["kind"] == "mep_acceptance"
        assert accepted.json()["artifact_sha256"] == routes_sha
        again = await api.post(f"{route}/acceptance", json=APPROVAL)
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "CAD_ALREADY_DECIDED"

        dxf = await api.get(f"{route}/artifacts/{FOLDER}/mep_routes.dxf")
        assert dxf.status_code == 200
        assert _sha(dxf.content) == routes_sha == dxf.headers["x-content-sha256"]
        assert b"AC1032" in dxf.content

        accepted_view = (await api.get(route)).json()["pages"][0]["views"][0]
        assert accepted_view["acceptance"]["id"] == accepted.json()["id"]
        parent_row = (await api.get(f"{base}/{job_id}")).json()["pages"][0]["views"][0]
        [ref] = [r for r in parent_row["route_jobs"] if r["job_id"] == route_id]
        assert ref["accepted"] is True and ref["status"] == "succeeded"
        assert (await api.get(f"{route}/views/0/1")).json()["acceptance"]["id"] == accepted.json()[
            "id"
        ]


@pytest.mark.parametrize(
    ("elevation", "error_code", "generator_error", "message"),
    [
        (99999, "CAD_INPUT_INVALID", "scale_missing", "Нет масштаба вида"),
        (88888, "CAD_MEP_NOT_BUILT", "no_risers", "Стояки не найдены"),
        (77777, "CAD_ENGINE_FAILED", None, "состав out/"),
    ],
)
async def test_worker_maps_generator_failures_and_publishes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
    elevation: int,
    error_code: str,
    generator_error: str | None,
    message: str,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        before = set(fake_storage.objects)
        route_id = await _approve_and_queue(api, base, job_id, elevation)

        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == error_code and message in (job.error_message or "")
        assert cad_service.result_of(job).get("generator_error") == generator_error
        assert set(fake_storage.objects) == before, "неудачная попытка ничего не публикует"
        assert not any((tmp_path / "work").rglob("*"))

        read = (await api.get(f"{base}/{route_id}")).json()
        assert read["status"] == "failed" and read["error_code"] == error_code
        assert read["retryable"] is False and read["pages"] == [] and read["artifacts"] == []
        not_ready = await api.post(f"{base}/{route_id}/acceptance", json=APPROVAL)
        assert not_ready.status_code == 409
        assert not_ready.json()["detail"]["code"] == "CAD_RESULT_NOT_READY"


async def test_worker_refuses_a_job_without_the_approval(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    """Защита в глубину: задание, у которого одобрение исчезло или подменено, не запускается."""
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        route = await db_session.get(Job, uuid.UUID(route_id))
        assert route is not None
        await db_session.execute(
            update(Job)
            .where(Job.id == route.id)
            .values(payload={**route.payload, "approval_id": str(uuid.uuid4())})
        )
        await db_session.commit()
        db_session.expire_all()

        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_INPUT_INVALID"
        assert "не одобрен" in (job.error_message or "")


async def test_worker_fails_closed_when_the_generator_is_not_configured(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        broken = settings.model_copy(update={"cad_mep_runner": str(tools / "нет.py")})
        job = await _run_route_worker(db_session, fake_storage, broken, route_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_ENGINE_UNAVAILABLE"
