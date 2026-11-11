"""Трассы механики (ADR-0036 п. 8): гейты решений, постановка, обработчик cad-worker.

Движок и настоящий генератор не нужны: родитель `cad_pdf_convert` выставляется прямо в базе и
хранилище, как его оставил бы исполнитель, а генератор подменён скриптом-заглушкой, которая пишет
файлы по CLI-контракту. Результат заглушки выбирает отметка пола: 99999 - код выхода 2, 88888 -
код 3, 77777 - не хватает файла, остальное - успех. Без отметки/высоты заглушка «находит» их в
документации (47600 observed, 3300 derived); файл `not_found` рядом со скриптом с кодом внутри
(`elevation_not_found` / `floor_height_not_found`) заставляет её отказать, как генератор.
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
from app.models import CadDecision, CadRemark, Job, Workspace
from app.services import cad as cad_service
from app.services import cad_mep as cad_mep_service
from app.services import cad_risers
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
             "floor-elevation-mm", "floor-height-mm", "approval-id", "risers"):
    parser.add_argument("--" + name)
args = parser.parse_args()
for name in ("pdf", "view_dxf", "scale", "preview", "params"):
    if not pathlib.Path(getattr(args, name)).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
seen = pathlib.Path(__file__).parent / "risers_seen.json"
seen.write_text("none" if args.risers is None else pathlib.Path(args.risers).read_text("utf-8"),
                encoding="utf-8")
auto = args.floor_elevation_mm is None or args.floor_height_mm is None
marker = pathlib.Path(__file__).parent / "not_found"
if auto and marker.exists():
    print(json.dumps({"code": marker.read_text().strip(), "message": "введите значение вручную"}),
          file=sys.stderr)
    sys.exit(2)
elevation = 47600 if args.floor_elevation_mm is None else int(args.floor_elevation_mm)
height = 3300 if args.floor_height_mm is None else int(args.floor_height_mm)
elevation_source = "observed" if args.floor_elevation_mm is None else "operator"
height_source = "derived" if args.floor_height_mm is None else "operator"
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
if not (pathlib.Path(__file__).parent / "no_routes3d").exists():  # прежний генератор
    (folder / "routes3d.json").write_text(json.dumps({
        "schema": "cad_mep_routes3d.v1", "frame": "view_dxf_mm",
        "floor_elevation_mm": elevation, "floor_height_mm": height,
        "polylines": [{"layer": "M-OV-T1", "pts": [[0, 0, 50], [1000, 0, 50]]},
                      {"layer": "M-VK-V1", "pts": [[500, 500, 0], [500, 500, 2900]]}]}))
if elevation != 77777:
    (folder / "candidate.json").write_text(json.dumps({
        "schema": "quantor.cad_mep.candidate.v1",
        "floor_elevation_mm": elevation, "floor_height_mm": height,
        "page_index": int(args.page_index),
        "provenance": {
            "floor_elevation": {"value_mm": elevation, "source": elevation_source,
                                "evidence": "стр. 1: заголовок"},
            "floor_height": {"value_mm": height, "source": height_source,
                             "evidence": "стр. 1 -> стр. 2"}}}))
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


def _routes_body(elevation: int | None = 47600, height: int | None = 3300) -> dict[str, int]:
    body = {"attempt": 1}
    if elevation is not None:
        body["floor_elevation_mm"] = elevation
    if height is not None:
        body["floor_height_mm"] = height
    return body


async def _approve_and_queue(
    api: AsyncClient,
    base: str,
    job_id: str,
    elevation: int | None = 47600,
    height: int | None = 3300,
) -> str:
    view = f"{base}/{job_id}/views/0/1"
    assert (await api.post(f"{view}/approval", json=APPROVAL)).status_code == 201
    queued = await api.post(f"{view}/mep-routes", json=_routes_body(elevation, height))
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
    assert f"{base}/recompute" in paths
    assert (
        "/api/v1/projects/{project_id}/revisions/{revision_id}/cad/decisions/{decision_id}/revoke"
        in paths
    )
    assert set(HANDLERS) == {
        JobType.CAD_PDF_CONVERT,
        JobType.CAD_MEP_ROUTE,
        JobType.CAD_WALLS,
        JobType.CAD_FLOOR3D_DXF,
        JobType.CAD_ZONES,
    }
    assert JobType.CAD_MEP_ROUTE.value == "cad_mep_route"


def test_route_artifact_names_are_closed_and_dxf_needs_the_route_pattern() -> None:
    revision, job = uuid.uuid4(), uuid.uuid4()
    for name in ("mep_routes.dxf", "candidate.json", "preview.json", "routes3d.json"):
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

        # Отметки необязательны (определит генератор), но заданные - в пределах.
        for body in (
            _routes_body(height=1999),
            _routes_body(height=6001),
            _routes_body(elevation=2_000_000),
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

        # Идемпотентность: то же одобрение, параметры и версия - то же задание; другие отметки
        # нового задания не создают (их правят пересчётом).
        again = await api.post(f"{view}/mep-routes", json=_routes_body())
        assert again.json()["job_id"] == route["job_id"]
        other = await api.post(f"{view}/mep-routes", json=_routes_body(elevation=50900))
        assert other.status_code == 202 and other.json()["job_id"] == route["job_id"]
        auto = await api.post(f"{view}/mep-routes", json={"attempt": 1})
        assert auto.json()["job_id"] == route["job_id"]

        # Родитель показывает одобрение и route-задания вида; список - тип и родителя.
        parent = (await api.get(f"{base}/{job_id}")).json()
        assert parent["job_type"] == "cad_pdf_convert" and parent["parent_job_id"] is None
        [row] = parent["pages"][0]["views"]
        assert row["approval"]["id"] == decision["id"]
        assert row["acceptance"] is None
        assert [r["job_id"] for r in row["route_jobs"]] == [route["job_id"]]
        assert row["route_jobs"][0]["approval_revoked"] is False
        assert row["revoked_decisions"] == []
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
            f"{FOLDER}/routes3d.json",
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


# ------------------------------------------------------------------ отзыв решений


async def test_revoking_the_approval_blocks_routes_and_allows_a_new_approval(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        view = f"{base}/{job_id}/views/0/1"
        approval = (await api.post(f"{view}/approval", json=APPROVAL)).json()
        route_id = str((await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"])

        assert (
            await api.post(f"{base}/decisions/{uuid.uuid4()}/revoke", json={})
        ).status_code == 404
        revoked = await api.post(
            f"{base}/decisions/{approval['id']}/revoke", json={"reason": " Кликнул случайно "}
        )
        assert revoked.status_code == 200, revoked.text
        body = revoked.json()
        assert body["id"] == approval["id"] and body["revoked_at"] and body["revoked_by"]
        assert body["revoke_reason"] == "Кликнул случайно"
        again = await api.post(f"{base}/decisions/{approval['id']}/revoke", json={})
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "CAD_ALREADY_REVOKED"
        # запись не удалена
        assert await db_session.scalar(select(func.count()).select_from(CadDecision)) == 1

        # В чтении - только действующее решение, история отдельно.
        [row] = (await api.get(f"{base}/{job_id}")).json()["pages"][0]["views"]
        assert row["approval"] is None
        [old] = row["revoked_decisions"]
        assert old["id"] == approval["id"] and old["revoke_reason"] == "Кликнул случайно"
        assert row["route_jobs"][0]["approval_revoked"] is True
        assert (await api.get(f"{base}/{route_id}")).json()["approval_revoked"] is True

        # Без действующего одобрения трассы не строятся; поставленное задание не запускается.
        refused = await api.post(f"{view}/mep-routes", json=_routes_body())
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "CAD_VIEW_APPROVAL_REVOKED"
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_VIEW_APPROVAL_REVOKED"

        # После отзыва вид одобряется заново - новой записью; трассы - новым заданием.
        second = await api.post(f"{view}/approval", json=APPROVAL)
        assert second.status_code == 201 and second.json()["id"] != approval["id"]
        [row] = (await api.get(f"{base}/{job_id}")).json()["pages"][0]["views"]
        assert row["approval"]["id"] == second.json()["id"] and len(row["revoked_decisions"]) == 1
        fresh = await api.post(f"{view}/mep-routes", json=_routes_body())
        assert fresh.status_code == 202 and fresh.json()["job_id"] != route_id
        assert await db_session.scalar(select(func.count()).select_from(CadDecision)) == 2


async def test_acceptance_revoke_and_the_approval_it_depends_on(
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
        view = f"{base}/{job_id}/views/0/1"
        approval = (await api.post(f"{view}/approval", json=APPROVAL)).json()
        route_id = str((await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"])
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        route = f"{base}/{route_id}"
        accepted = (await api.post(f"{route}/acceptance", json=APPROVAL)).json()

        # Одобрение отзывается, только пока нет принятых трасс.
        blocked = await api.post(f"{base}/decisions/{approval['id']}/revoke", json={})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "CAD_ROUTES_ACCEPTED"

        stranger = make_context(platform_admin=False, workspace_id=second_id)
        async with build_api(stranger, settings=settings) as foreign:
            gone = await foreign.post(f"{base}/decisions/{accepted['id']}/revoke", json={})
            assert gone.status_code == 404

        revoked = await api.post(f"{base}/decisions/{accepted['id']}/revoke", json={})
        assert revoked.status_code == 200 and revoked.json()["kind"] == "mep_acceptance"
        closed = await api.get(f"{route}/artifacts/{FOLDER}/mep_routes.dxf")
        assert closed.status_code == 409
        assert closed.json()["detail"]["code"] == "CAD_ROUTES_NOT_ACCEPTED"
        [row] = (await api.get(route)).json()["pages"][0]["views"]
        assert row["acceptance"] is None and len(row["revoked_decisions"]) == 1
        [ref] = (await api.get(f"{base}/{job_id}")).json()["pages"][0]["views"][0]["route_jobs"]
        assert ref["accepted"] is False

        assert (
            await api.post(f"{base}/decisions/{approval['id']}/revoke", json={})
        ).status_code == 200
        # Принять трассы по отозванному одобрению нельзя; просмотр и кандидат работают.
        late = await api.post(f"{route}/acceptance", json=APPROVAL)
        assert late.status_code == 409
        assert late.json()["detail"]["code"] == "CAD_VIEW_APPROVAL_REVOKED"
        assert (await api.get(f"{route}/artifacts/{FOLDER}/candidate.json")).status_code == 200
        assert (await api.get(f"{route}/artifacts/{FOLDER}/preview.json")).status_code == 200
        assert (await api.get(f"{route}/views/0/1/preview")).status_code == 200
        assert (await api.get(f"{route}/views/0/1")).status_code == 200
        assert (await api.get(f"{route}/remarks?attempt=1&page_index=0&view=1")).status_code == 200


# ------------------------------------------------------------------ отметки из документации


async def test_floor_values_come_from_the_generator_result(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id, None, None)
        queued = (await api.get(f"{base}/{route_id}")).json()
        assert queued["floor_elevation_mm"] is None and queued["floor_height_mm"] is None
        assert queued["floor_elevation_source"] is None
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        read = (await api.get(f"{base}/{route_id}")).json()
        assert (read["floor_elevation_mm"], read["floor_elevation_source"]) == (47600, "observed")
        assert (read["floor_height_mm"], read["floor_height_source"]) == (3300, "derived")
        assert read["floor_elevation_evidence"] and read["floor_height_evidence"]
        [attempt] = read["route_attempts"]
        assert attempt["attempt"] == 1 and attempt["status"] == "succeeded"
        assert attempt["requested_elevation_mm"] is None and attempt["requested_height_mm"] is None
        assert attempt["floor_height_source"] == "derived"


@pytest.mark.parametrize(
    ("generator_code", "error_code"),
    [
        ("elevation_not_found", "CAD_ELEVATION_NOT_FOUND"),
        ("floor_height_not_found", "CAD_FLOOR_HEIGHT_NOT_FOUND"),
    ],
)
async def test_generator_without_floor_values_asks_for_manual_input(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
    generator_code: str,
    error_code: str,
) -> None:
    (tools / "not_found").write_text(generator_code)
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id, None, None)
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.FAILED and job.error_code == error_code
        assert "вручную" in (job.error_message or "")
        read = (await api.get(f"{base}/{route_id}")).json()
        assert read["status"] == "failed" and read["error_code"] == error_code
        [attempt] = read["route_attempts"]
        assert attempt["status"] == "failed" and attempt["error_code"] == error_code

        # Ручной ввод даёт результат: пересчёт той же попыткой задания.
        done = await api.post(
            f"{base}/{route_id}/recompute",
            json={"floor_elevation_mm": 47600, "floor_height_mm": 3300},
        )
        assert done.status_code == 202, done.text
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)


# ------------------------------------------------------------------ пересчёт трасс


async def test_recompute_is_a_new_attempt_that_carries_open_remarks(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        view = f"{base}/{job_id}/views/0/1"
        route_id = await _approve_and_queue(api, base, job_id)
        route = f"{base}/{route_id}"
        recompute = f"{route}/recompute"

        # Пока задание в очереди - нельзя.
        busy = await api.post(recompute, json={"floor_elevation_mm": 50900})
        assert busy.status_code == 409
        assert busy.json()["detail"]["code"] == "JOB_NOT_RETRYABLE"

        await _run_route_worker(db_session, fake_storage, settings, route_id)
        routes_sha = (await api.get(f"{route}/views/0/1")).json()["dxf"]["sha256"]
        open_key, done_key = uuid.uuid4(), uuid.uuid4()
        for key, status in ((open_key, "open"), (done_key, "resolved")):
            url = f"{route}/remarks/{key}?attempt=1&page_index=0&view=1"
            assert (await api.put(url, json=_remark(routes_sha, status))).status_code == 200

        # Те же параметры - тот же результат.
        same = await api.post(
            recompute, json={"floor_elevation_mm": 47600, "floor_height_mm": 3300}
        )
        assert same.status_code == 409
        assert same.json()["detail"]["code"] == "CAD_RECOMPUTE_SAME_PARAMS"

        jobs_before = await db_session.scalar(select(func.count()).select_from(Job))
        queued = await api.post(
            recompute, json={"floor_elevation_mm": 50900, "floor_height_mm": 3300}
        )
        assert queued.status_code == 202, queued.text
        body = queued.json()
        assert body["job_id"] == route_id and body["status"] == "queued"
        assert [a["attempt"] for a in body["route_attempts"]] == [1, 2]
        assert [a["status"] for a in body["route_attempts"]] == ["succeeded", "queued"]
        assert body["route_attempts"][1]["requested_elevation_mm"] == 50900
        assert await db_session.scalar(select(func.count()).select_from(Job)) == jobs_before

        # В новую попытку перешло только открытое замечание; привязка к DXF - после расчёта.
        db_session.expire_all()
        carried = list(
            await db_session.scalars(
                select(CadRemark).where(
                    CadRemark.job_id == uuid.UUID(route_id), CadRemark.attempt == 2
                )
            )
        )
        assert [(r.remark_key, r.status, r.dxf_sha256) for r in carried] == [
            (str(open_key), "open", None)
        ]
        again_busy = await api.post(recompute, json={"floor_elevation_mm": 51000})
        assert again_busy.status_code == 409

        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED and job.attempt == 2
        db_session.expire_all()
        carried = list(
            await db_session.scalars(
                select(CadRemark).where(
                    CadRemark.job_id == uuid.UUID(route_id), CadRemark.attempt == 2
                )
            )
        )
        assert [r.dxf_sha256 for r in carried] == [routes_sha]

        read = (await api.get(route)).json()
        assert read["result_attempt"] == 2 and read["attempt"] == 2
        assert (read["floor_elevation_mm"], read["floor_elevation_source"]) == (50900, "operator")
        assert [a["status"] for a in read["route_attempts"]] == ["succeeded", "succeeded"]
        assert read["route_attempts"][0]["floor_elevation_mm"] == 47600
        assert any(f"/attempt-2/{FOLDER}/" in k for k in fake_storage.objects if route_id in k)
        assert any(f"/attempt-1/{FOLDER}/" in k for k in fake_storage.objects if route_id in k)

        # Прошлая попытка открывается для просмотра: файлы, превью, диагностика.
        old = await api.get(f"{route}/artifacts/{FOLDER}/candidate.json?attempt=1")
        assert old.status_code == 200 and old.json()["floor_elevation_mm"] == 47600
        new = await api.get(f"{route}/artifacts/{FOLDER}/candidate.json")
        assert new.json()["floor_elevation_mm"] == 50900
        assert (await api.get(f"{route}/views/0/1/preview?attempt=1")).status_code == 200
        assert (await api.get(f"{route}/views/0/1?attempt=1")).json()["attempt"] == 1
        assert (await api.get(f"{route}/views/0/1?attempt=7")).status_code == 404

        # Повторная постановка на тот же вид возвращает то же задание.
        rebuilt = await api.post(f"{view}/mep-routes", json=_routes_body(elevation=40000))
        assert rebuilt.json()["job_id"] == route_id and rebuilt.json()["attempt"] == 2


async def test_recompute_refused_when_accepted_or_approval_revoked(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        view = f"{base}/{job_id}/views/0/1"
        approval = (await api.post(f"{view}/approval", json=APPROVAL)).json()
        route_id = str((await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"])
        await _run_route_worker(db_session, fake_storage, settings, route_id)
        route = f"{base}/{route_id}"
        accepted = (await api.post(f"{route}/acceptance", json=APPROVAL)).json()

        refused = await api.post(f"{route}/recompute", json={})
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "CAD_ROUTES_ACCEPTED"

        await api.post(f"{base}/decisions/{accepted['id']}/revoke", json={})
        await api.post(f"{base}/decisions/{approval['id']}/revoke", json={})
        no_approval = await api.post(f"{route}/recompute", json={})
        assert no_approval.status_code == 409
        assert no_approval.json()["detail"]["code"] == "CAD_VIEW_APPROVAL_REVOKED"
        # Только для трасс.
        assert (await api.post(f"{base}/{job_id}/recompute", json={})).status_code == 404

        # Пустое тело - «по документации»: отличается от введённых вручную значений.
        again = await api.post(f"{view}/approval", json=APPROVAL)
        assert again.status_code == 201
        fresh = await api.post(f"{view}/mep-routes", json=_routes_body(None, None))
        assert fresh.json()["job_id"] != route_id


# ------------------------------------------------------------------ реестр стояков (ADR-0041)

RISERS = [
    {
        "system": "V1",
        "mark": "В1.1.1",
        "dn_mm": 50,
        "role": "own",
        "count": 1,
        "shaft_id": None,
        "source": "ИОС2.1 л.2",
        "note": None,
    },
    {
        "system": "VPV",
        "mark": "В2.1",
        "dn_mm": 65,
        "role": "own",
        "count": 2,
        "shaft_id": "S12",
        "source": None,
        "note": None,
    },
]


async def _put_risers(
    api: AsyncClient, project_id: str, revision_id: str, risers: list[dict[str, Any]]
) -> None:
    url = f"/api/v1/projects/{project_id}/cad/risers"
    query = f"?revision_id={revision_id}&page_index=0&view=1"
    assert (await api.put(f"{url}{query}", json={"risers": risers})).status_code == 200


def test_idempotency_key_includes_the_risers_hash() -> None:
    approval = uuid.uuid4()
    base = {"params_sha256": "p", "generator_version": "cad_mep.v6"}
    plain = cad_mep_service.route_idempotency_key(approval, **base)
    assert plain == cad_mep_service.route_idempotency_key(approval, risers_sha256="", **base)
    one = cad_mep_service.route_idempotency_key(approval, risers_sha256="a" * 64, **base)
    two = cad_mep_service.route_idempotency_key(approval, risers_sha256="b" * 64, **base)
    assert len({plain, one, two}) == 3 and one.startswith("cadmep:")


async def test_routes_without_the_registry_carry_no_risers(
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
        stored = await db_session.get(Job, uuid.UUID(route_id))
        assert stored is not None
        assert "risers" not in stored.payload and "risers_sha256" not in stored.payload

        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert (tools / "risers_seen.json").read_text(encoding="utf-8") == "none"


async def test_registry_goes_into_the_job_changes_the_key_and_reaches_the_generator(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        view = f"{base}/{job_id}/views/0/1"
        await _put_risers(api, project_id, revision_id, [])
        assert (await api.post(f"{view}/approval", json=APPROVAL)).status_code == 201
        plain = (await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"]

        # Пустой реестр - как без реестра: то же задание.
        again = (await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"]
        assert again == plain

        await _put_risers(api, project_id, revision_id, RISERS)
        with_registry = (await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"]
        assert with_registry != plain
        # Тот же реестр - то же задание; другой реестр - новое.
        repeated = (await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"]
        assert repeated == with_registry
        await _put_risers(api, project_id, revision_id, RISERS[:1])
        other = (await api.post(f"{view}/mep-routes", json=_routes_body())).json()["job_id"]
        assert other not in (plain, with_registry)

        stored = await db_session.get(Job, uuid.UUID(with_registry))
        assert stored is not None
        expected = cad_risers.registry_bytes(RISERS)
        assert stored.payload["risers"] == RISERS
        assert stored.payload["risers_sha256"] == _sha(expected)
        key = cad_mep_service.route_idempotency_key(
            uuid.UUID(stored.payload["approval_id"]),
            params_sha256=stored.payload["params_sha256"],
            generator_version=stored.payload["generator_version"],
            risers_sha256=_sha(expected),
        )
        assert stored.idempotency_key == key

        # Очередь FIFO: первым выполняется задание без реестра, затем с реестром.
        first = await _run_route_worker(db_session, fake_storage, settings, plain)
        assert first.status is JobStatus.SUCCEEDED
        assert (tools / "risers_seen.json").read_text(encoding="utf-8") == "none"
        second = await _run_route_worker(db_session, fake_storage, settings, with_registry)
        assert second.status is JobStatus.SUCCEEDED, (second.error_code, second.error_message)
        assert (tools / "risers_seen.json").read_bytes() == expected
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"


async def test_worker_refuses_a_registry_that_does_not_match_its_hash(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        await _put_risers(api, project_id, revision_id, RISERS)
        route_id = await _approve_and_queue(api, base, job_id)
        route = await db_session.get(Job, uuid.UUID(route_id))
        assert route is not None
        tampered = [{**RISERS[0], "dn_mm": 80}, RISERS[1]]
        await db_session.execute(
            update(Job)
            .where(Job.id == route.id)
            .values(payload={**route.payload, "risers": tampered})
        )
        await db_session.commit()
        db_session.expire_all()

        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_PARAMS_INVALID"
        assert "sha256" in (job.error_message or "")
        assert not (tools / "risers_seen.json").exists()
        assert not any((tmp_path / "work").rglob("*"))


# ------------------------------------------------------------------ 3D-трассы (routes3d.json)


async def test_routes3d_json_reaches_the_artifacts_and_manifest(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        name = f"{FOLDER}/routes3d.json"
        artifact = cad_service.find_artifact(job, name)
        assert artifact is not None
        key = cad_service.artifact_storage_key(uuid.UUID(revision_id), job.id, 1, name)
        assert artifact["key"] == key
        stored = json.loads(fake_storage.objects[key])
        assert stored["schema"] == "cad_mep_routes3d.v1" and stored["frame"] == "view_dxf_mm"
        assert artifact["sha256"] == _sha(fake_storage.objects[key])
        manifest_key = cad_service.artifact_storage_key(
            uuid.UUID(revision_id), job.id, 1, "manifest.json"
        )
        manifest = json.loads(fake_storage.objects[manifest_key])
        assert name in {row["name"] for row in manifest["files"]}
        assert (await api.get(f"{base}/{route_id}/artifacts/{name}")).status_code == 200


async def test_routes_from_a_generator_without_routes3d_still_succeed(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    (tools / "no_routes3d").write_text("1", encoding="utf-8")
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        route_id = await _approve_and_queue(api, base, job_id)
        job = await _run_route_worker(db_session, fake_storage, settings, route_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        names = {row["name"] for row in (await api.get(f"{base}/{route_id}")).json()["artifacts"]}
        assert f"{FOLDER}/routes3d.json" not in names
        assert f"{FOLDER}/mep_routes.dxf" in names
