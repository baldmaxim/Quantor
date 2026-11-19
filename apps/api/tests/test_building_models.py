"""Модель здания из пакета QMP (ADR-0053): приём по частям, фиксация, утверждение, чтение.

Пакет - тот же небольшой пакет в памяти, что в `test_model_package`; хранилище в памяти,
база настоящая.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.cad_worker import HANDLERS
from app.cad_worker.model_handler import execute_model_ifc_import, generator_failure
from app.core.config import Settings
from app.domain import DocumentKind, JobStatus, JobType, ModelVersionStatus
from app.errors import ErrorCode
from app.main import create_app
from app.models import BuildingModelVersion, Document, DocumentRevision, Job, ModelPart
from app.services import cad_queue
from app.services import jobs as jobs_service
from app.services import model_package as qmp
from tests.cad_pins_helper import _entry, write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_model_package import (
    STOREY_A,
    STOREY_B,
    build_package,
    reseal,
    two_building_package,
)

GLB_A = f"geometry/{STOREY_A}__ARCH.glb"


def open_settings() -> Any:
    return clean_settings(environment="test", feature_flags="model.import=true")


async def new_project(api: AsyncClient) -> str:
    response = await api.post("/api/v1/projects", json={"name": "Капельский, модель"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def start(api: AsyncClient, project: str, manifest: dict[str, Any]) -> Any:
    return await api.post(
        f"/api/v1/projects/{project}/model/versions",
        content=json.dumps(manifest).encode(),
        headers={"content-type": "application/json"},
    )


async def put_part(api: AsyncClient, project: str, version: str, path: str, data: bytes) -> Any:
    return await api.put(
        f"/api/v1/projects/{project}/model/versions/{version}/parts/{path}",
        content=data,
        headers={"content-type": "application/octet-stream"},
    )


async def upload_all(
    api: AsyncClient, project: str, version: str, files: dict[str, bytes], *, skip: str = ""
) -> None:
    for path, data in files.items():
        if path != skip:
            response = await put_part(api, project, version, path, data)
            assert response.status_code == 200, (path, response.text)


def test_model_routes_are_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/model"
    assert f"{base}/versions" in paths
    assert f"{base}/versions/{{version_id}}/parts/{{path}}" in paths
    assert f"{base}/versions/{{version_id}}/commit" in paths
    assert f"{base}/versions/{{version_id}}/approve" in paths
    assert f"{base}/versions/{{version_id}}/storeys/{{storey_key}}/elements" in paths


async def test_closed_flag_hides_the_routes(build_api: Callable[..., AsyncClient]) -> None:
    settings = clean_settings(environment="test")
    async with build_api(make_context(), settings=settings) as api:
        project = await new_project(api)
        response = await api.get(f"/api/v1/projects/{project}/model/versions")
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_upload_commit_read_and_approve(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, files, manifest = build_package()
        started = await start(api, project, manifest)
        assert started.status_code == 201, started.text
        body = started.json()
        version = body["id"]
        assert body["created"] is True and body["status"] == "uploading" and body["number"] == 1
        assert sorted(body["missing_parts"]) == sorted(files)

        await upload_all(api, project, version, files)
        resumed = await start(api, project, manifest)
        assert resumed.status_code == 200 and resumed.json()["id"] == version
        assert resumed.json()["created"] is False and resumed.json()["missing_parts"] == []

        committed = await api.post(f"/api/v1/projects/{project}/model/versions/{version}/commit")
        assert committed.status_code == 200, committed.text
        data = committed.json()
        assert data["status"] == "candidate" and data["committed_at"] is not None
        assert [s["storey_key"] for s in data["storeys"]] == [STOREY_A, STOREY_B]
        assert [s["element_count"] for s in data["storeys"]] == [2, 1]
        assert {s["building_key"] for s in data["storeys"]} == {None}
        assert data["counts"]["elements"] == 3 and data["warnings"] == []
        parts = {part["path"]: part for part in data["parts"]}
        assert set(parts) == set(files)
        assert parts[GLB_A]["storey_key"] == STOREY_A and parts[GLB_A]["discipline"] == "ARCH"

        listed = (await api.get(f"/api/v1/projects/{project}/model/versions")).json()
        assert [v["id"] for v in listed["items"]] == [version]

        base = f"/api/v1/projects/{project}/model/versions/{version}"
        page = (await api.get(f"{base}/storeys/{STOREY_A}/elements", params={"limit": 1})).json()
        assert page["total"] == 2 and len(page["items"]) == 1
        assert page["items"][0]["props"] == {"Pset.Fire": "EI60"}
        none = await api.get(f"{base}/storeys/{STOREY_A}/elements", params={"category": "door"})
        assert none.json()["total"] == 0

        part = await api.get(f"{base}/parts/{GLB_A}")
        assert part.status_code == 200 and part.content == files[GLB_A]
        assert part.headers["content-type"] == "model/gltf-binary"
        etag = part.headers["etag"]
        assert "immutable" in part.headers["cache-control"]
        cached = await api.get(f"{base}/parts/{GLB_A}", headers={"if-none-match": etag})
        assert cached.status_code == 304

        approved = await api.post(f"{base}/approve", json={"comment": "первая выгрузка"})
        assert approved.status_code == 200 and approved.json()["status"] == "approved"
        again = await api.post(f"{base}/approve", json={})
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "MODEL_VERSION_STATE"


async def test_new_approved_version_supersedes_the_old_one(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        ids = []
        for note in ("первая", "вторая"):
            _, files, manifest = build_package()
            manifest["disciplines"][0]["name"] = note
            started = await start(api, project, reseal(manifest))
            version = started.json()["id"]
            await upload_all(api, project, version, files)
            base = f"/api/v1/projects/{project}/model/versions/{version}"
            assert (await api.post(f"{base}/commit")).status_code == 200
            assert (await api.post(f"{base}/approve", json={})).status_code == 200
            ids.append(version)
        listed = (await api.get(f"/api/v1/projects/{project}/model/versions")).json()["items"]
        statuses = {v["id"]: v["status"] for v in listed}
        assert statuses == {ids[0]: "superseded", ids[1]: "approved"}
        assert [v["number"] for v in listed] == [2, 1]


async def test_storeys_keep_their_building_and_package_order(
    build_api: Callable[..., AsyncClient],
) -> None:
    """Модель с двумя корпусами (раздел 4): этажи отдаются по зданиям, в порядке storeys.json."""
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, files, manifest = two_building_package()
        version = (await start(api, project, manifest)).json()["id"]
        await upload_all(api, project, version, files)
        base = f"/api/v1/projects/{project}/model/versions/{version}"
        committed = await api.post(f"{base}/commit")
        assert committed.status_code == 200, committed.text
        assert committed.json()["warnings"] == []
        detail = (await api.get(base)).json()
        rows = [(s["storey_key"], s["building_key"], s["building_name"]) for s in detail["storeys"]]
        assert rows == [(STOREY_B, "K1", "Корпус 1"), (STOREY_A, "K2", "Корпус 2")]


async def test_part_with_wrong_hash_or_path_is_rejected(
    build_api: Callable[..., AsyncClient], fake_storage: FakeObjectStorage
) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, files, manifest = build_package()
        version = (await start(api, project, manifest)).json()["id"]
        broken = files[GLB_A] + b"x"
        response = await put_part(api, project, version, GLB_A, broken)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "MODEL_PACKAGE_INVALID"
        assert not any(key.endswith(GLB_A) for key in fake_storage.objects)

        extra = await put_part(api, project, version, "geometry/other.glb", b"data")
        assert (
            extra.status_code == 422
            and extra.json()["detail"]["issue"]["code"] == "PART_UNDECLARED"
        )
        bad = await put_part(api, project, version, "a/../b.json", b"{}")
        assert bad.status_code in (404, 422)


async def test_commit_with_missing_part_keeps_the_upload_open(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, files, manifest = build_package()
        version = (await start(api, project, manifest)).json()["id"]
        await upload_all(api, project, version, files, skip="grids.json")
        base = f"/api/v1/projects/{project}/model/versions/{version}"
        refused = await api.post(f"{base}/commit")
        assert refused.status_code == 422
        assert refused.json()["detail"]["issue"]["code"] == "PART_MISSING"
        assert (await api.get(base)).json()["status"] == "uploading"
        assert (
            await put_part(api, project, version, "grids.json", files["grids.json"])
        ).status_code == 200
        assert (await api.post(f"{base}/commit")).status_code == 200


async def test_only_unfinished_uploads_can_be_deleted(
    build_api: Callable[..., AsyncClient], fake_storage: FakeObjectStorage
) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, files, manifest = build_package()
        version = (await start(api, project, manifest)).json()["id"]
        await upload_all(api, project, version, files, skip="grids.json")
        base = f"/api/v1/projects/{project}/model/versions/{version}"
        assert (await api.delete(base)).status_code == 204
        assert not fake_storage.objects
        assert (await api.get(base)).status_code == 404

        started = (await start(api, project, manifest)).json()
        await upload_all(api, project, started["id"], files)
        base = f"/api/v1/projects/{project}/model/versions/{started['id']}"
        assert (await api.post(f"{base}/commit")).status_code == 200
        assert (await api.delete(base)).status_code == 409


async def test_broken_manifest_is_rejected(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, _, manifest = build_package()
        manifest["counts"]["elements"] = 99
        response = await start(api, project, manifest)
        assert response.status_code == 422
        assert response.json()["detail"]["issue"]["code"] == "MANIFEST_HASH"
        assert manifest["schema"] == qmp.SCHEMA


async def test_other_workspace_does_not_see_the_model(
    build_api: Callable[..., AsyncClient], second_workspace: Any
) -> None:
    async with build_api(make_context(), settings=open_settings()) as api:
        project = await new_project(api)
        _, files, manifest = build_package()
        version = (await start(api, project, manifest)).json()["id"]
        await upload_all(api, project, version, files)
    stranger = make_context(workspace_id=second_workspace.id)
    async with build_api(stranger, settings=open_settings()) as other:
        response = await other.get(f"/api/v1/projects/{project}/model/versions/{version}")
        assert response.status_code == 404


# ------------------------------------------------------------------ модель из IFC проекта

STUB = """
import argparse, base64, json, pathlib, sys

parser = argparse.ArgumentParser()
parser.add_argument("--ifc", action="append", default=[])
parser.add_argument("--params")
parser.add_argument("--out")
args = parser.parse_args()
for name in args.ifc:
    if not pathlib.Path(name).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
if any("FAIL" in pathlib.Path(name).name for name in args.ifc):
    print(json.dumps({"code": "no_storeys", "message": "Нет этажей"}), file=sys.stderr)
    sys.exit(3)
package = json.loads((pathlib.Path(__file__).parent / "package.json").read_text())
out = pathlib.Path(args.out)
for rel, data in package.items():
    (out / rel).parent.mkdir(parents=True, exist_ok=True)
    (out / rel).write_bytes(base64.b64decode(data))
"""


@pytest.fixture
def model_tools(tmp_path: Path) -> Path:
    """Каталог генераторов: заглушка `cad_model`, которая пишет готовый пакет QMP."""
    manifest, files, _ = build_package()
    root = tmp_path / "generators"
    (root / "cad_model" / "params").mkdir(parents=True)
    (root / "cad_model" / "params" / "v1.json").write_text(
        json.dumps({"drop_classes": {"value": ["IfcCovering"], "source": "assumed"}}),
        encoding="utf-8",
    )
    (root / "cad_model" / "run_model.py").write_text(STUB, encoding="utf-8")
    package = {"manifest.json": manifest, **files}
    (root / "cad_model" / "package.json").write_text(
        json.dumps({k: base64.b64encode(v).decode() for k, v in package.items()}),
        encoding="utf-8",
    )
    return root


def import_settings(tools: Path, tmp_path: Path) -> Settings:
    pins = Path(write_pins(tmp_path))
    data = json.loads(pins.read_text(encoding="utf-8"))
    data["generators"]["cad_model"] = _entry(
        tools / "cad_model" / "params" / "v1.json", "cad_model.v0.1"
    )
    pins.write_text(json.dumps(data), encoding="utf-8")
    return clean_settings(
        environment="test",
        feature_flags="model.import=true",
        cad_engine_python=sys.executable,
        cad_model_runner=str(tools / "cad_model" / "run_model.py"),
        cad_model_params=str(tools / "cad_model" / "params" / "v1.json"),
        cad_engine_pins=str(pins),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


async def add_ifc(
    session: AsyncSession, storage: FakeObjectStorage, project: str, name: str
) -> DocumentRevision:
    document = Document(
        project_id=uuid.UUID(project), display_name=name, document_kind=DocumentKind.IFC
    )
    session.add(document)
    await session.flush()
    payload = (
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n" + name.encode()
    )
    key = f"test/{uuid.uuid4()}"
    storage.objects[key] = payload
    revision = DocumentRevision(
        document_id=document.id,
        source_filename=name,
        source_mime="application/octet-stream",
        source_size=len(payload),
        source_sha256=hashlib.sha256(payload).hexdigest(),
        storage_key=key,
    )
    session.add(revision)
    await session.commit()
    return revision


async def run_import_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session, worker_id="model-test", job_types=[t.value for t in HANDLERS], lease_seconds=600
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_model_ifc_import
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


def test_import_route_and_job_type_are_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert "/api/v1/projects/{project_id}/model/imports" in paths
    assert "/api/v1/projects/{project_id}/model/imports/latest" in paths
    assert HANDLERS[JobType.MODEL_IFC_IMPORT] is execute_model_ifc_import
    assert JobType.MODEL_IFC_IMPORT in cad_queue.QUEUE_JOB_TYPES


def test_generator_exit_codes_map_to_job_failures() -> None:
    line = json.dumps({"code": "no_storeys", "message": "Нет этажей"}).encode()
    built = generator_failure(3, b"log\n" + line)
    assert built.code is ErrorCode.MODEL_IFC_NOT_BUILT and built.message == "Нет этажей"
    assert generator_failure(2, b"").code is ErrorCode.CAD_INPUT_INVALID
    assert generator_failure(9, b"boom").code is ErrorCode.CAD_ENGINE_FAILED


async def test_import_without_ifc_documents_is_refused(
    build_api: Callable[..., AsyncClient], model_tools: Path, tmp_path: Path
) -> None:
    settings = import_settings(model_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project = await new_project(api)
        response = await api.post(f"/api/v1/projects/{project}/model/imports", json={})
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "MODEL_IFC_NOT_FOUND"
        latest = await api.get(f"/api/v1/projects/{project}/model/imports/latest")
        assert latest.status_code == 404


async def test_worker_builds_the_model_from_the_project_ifc(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    model_tools: Path,
    tmp_path: Path,
) -> None:
    settings = import_settings(model_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project = await new_project(api)
        await add_ifc(db_session, fake_storage, project, "KPLSK_ARCH.ifc")
        await add_ifc(db_session, fake_storage, project, "KPLSK_PL.ifc")
        base = f"/api/v1/projects/{project}/model"
        queued = await api.post(f"{base}/imports", json={})
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["job_id"]
        assert queued.json()["status"] == "queued" and queued.json()["inputs"] == 2
        assert queued.json()["generator_version"] == "cad_model.v0.1"
        again = await api.post(f"{base}/imports", json={})
        assert again.json()["job_id"] == job_id

        job = await run_import_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"

        latest = (await api.get(f"{base}/imports/latest")).json()
        assert latest["status"] == "succeeded" and latest["version_id"] is not None
        version = (await api.get(f"{base}/versions/{latest['version_id']}")).json()
        assert version["status"] == "candidate" and version["number"] == 1
        assert [s["storey_key"] for s in version["storeys"]] == [STOREY_A, STOREY_B]
        listed = (await api.get(f"{base}/versions")).json()["items"]
        assert [v["id"] for v in listed] == [latest["version_id"]]


async def test_generator_refusal_fails_the_job_with_its_reason(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    model_tools: Path,
    tmp_path: Path,
) -> None:
    settings = import_settings(model_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project = await new_project(api)
        await add_ifc(db_session, fake_storage, project, "KPLSK_FAIL.ifc")
        queued = await api.post(f"/api/v1/projects/{project}/model/imports", json={})
        job = await run_import_worker(db_session, fake_storage, settings, queued.json()["job_id"])
        assert job.status is JobStatus.FAILED
        assert job.error_code == ErrorCode.MODEL_IFC_NOT_BUILT.value
        latest = (await api.get(f"/api/v1/projects/{project}/model/imports/latest")).json()
        assert latest["status"] == "failed" and latest["version_id"] is None


async def test_api_writes_are_committed_and_seen_from_another_session(
    db_session: AsyncSession,
    db_engine: AsyncEngine,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    model_tools: Path,
    tmp_path: Path,
) -> None:
    """Запись маршрута фиксируется в базе: её видно из другой сессии.

    API и проверка в тестах делят одну сессию и не заметили бы пропущенный `commit`; на проде
    сессия запроса закрывается без него, и всё, что маршрут не зафиксировал, откатывается
    (кнопка «Построить модель из IFC» отвечала 202, а задания в базе не появлялось).
    """
    settings = import_settings(model_tools, tmp_path)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def seen_status(version: str) -> ModelVersionStatus | None:
        async with factory() as other:
            row = await other.get(BuildingModelVersion, uuid.UUID(version))
            return None if row is None else row.status

    async with build_api(make_context(), settings=settings) as api:
        project = await new_project(api)
        await add_ifc(db_session, fake_storage, project, "KPLSK_ARCH.ifc")
        base = f"/api/v1/projects/{project}/model"

        queued = await api.post(f"{base}/imports", json={})
        assert queued.status_code == 202, queued.text
        async with factory() as other:
            assert await other.get(Job, uuid.UUID(queued.json()["job_id"])) is not None

        _, files, manifest = build_package()
        started = await start(api, project, manifest)
        version = started.json()["id"]
        assert await seen_status(version) is ModelVersionStatus.UPLOADING

        first = next(iter(files))
        assert (await put_part(api, project, version, first, files[first])).status_code == 200
        async with factory() as other:
            stored = (
                (
                    await other.execute(
                        select(ModelPart.path).where(ModelPart.version_id == uuid.UUID(version))
                    )
                )
                .scalars()
                .all()
            )
        assert stored == [first]

        await upload_all(api, project, version, files, skip=first)
        assert (await api.post(f"{base}/versions/{version}/commit")).status_code == 200
        assert await seen_status(version) is ModelVersionStatus.CANDIDATE
        assert (await api.post(f"{base}/versions/{version}/approve", json={})).status_code == 200
        assert await seen_status(version) is ModelVersionStatus.APPROVED

        # Отмена выгрузки: незавершённая версия другого проекта удаляется насовсем.
        other_project = await new_project(api)
        draft = (await start(api, other_project, manifest)).json()["id"]
        assert await seen_status(draft) is ModelVersionStatus.UPLOADING
        deleted = await api.delete(f"/api/v1/projects/{other_project}/model/versions/{draft}")
        assert deleted.status_code == 204
        assert await seen_status(draft) is None
