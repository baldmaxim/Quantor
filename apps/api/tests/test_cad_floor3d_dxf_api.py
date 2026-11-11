"""3D DXF этажа (ADR-0036 п. 6, ADR-0039): постановка, идемпотентность, исполнитель, скачивание.

Настоящий скрипт `tools/cad_walls/run_floor3d_dxf.py` в окружении API не запускается (ezdxf только
в образе cad-worker): он подменён заглушкой по CLI-контракту, а его собственные тесты лежат в
`tools/cad_walls/tests/test_floor3d_dxf.py`. Режим заглушки задаёт файл `mode` рядом со скриптом:
`fail` — код выхода 2, `badsha` — DXF другого хеша, `badgen` — чужая версия скрипта, `extra` —
лишний файл, `empty` — пустой DXF.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker.floor3d_dxf_handler import execute_cad_floor3d_dxf
from app.core.config import Settings
from app.domain import JobStatus, JobType, Role
from app.main import create_app
from app.models import Job, Workspace
from app.services import cad as cad_service
from app.services import cad_floor3d_dxf as floor3d_service
from app.services import jobs as jobs_service
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import _ready_sheet, _url, walls_settings
from tests.test_cad_floor3d_api import floor_tools  # noqa: F401  фикстура: заглушка cad_walls v1.1
from tests.test_cad_mep import FOLDER

DXF_BODY = b"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1032\n0\nENDSEC\n0\nEOF\n"
SCRIPT = Path(__file__).resolve().parents[3] / "tools/cad_walls/cad_walls/floor3d_dxf.py"

STUB = """
import argparse, hashlib, json, pathlib, sys

parser = argparse.ArgumentParser()
for name in ("model", "out"):
    parser.add_argument("--" + name, required=True)
args = parser.parse_args()
here = pathlib.Path(__file__).parent
mode = (here / "mode").read_text().strip() if (here / "mode").exists() else ""
model = pathlib.Path(args.model)
if not model.is_file():
    print(json.dumps({"code": "bad_model", "message": "нет модели"}), file=sys.stderr)
    sys.exit(2)
if mode == "fail":
    print(json.dumps({"code": "bad_model", "message": "модель негодна"}), file=sys.stderr)
    sys.exit(2)
raw = model.read_bytes()
info = {"model_name": model.name, "out_name": pathlib.Path(args.out).name}
(here / "args.json").write_text(json.dumps(info))
body = b"" if mode == "empty" else DXF_BODY
out = pathlib.Path(args.out)
out.write_bytes(body)
if mode == "extra":
    (out.parent / "other.txt").write_text("x")
summary = {
    "generator": "cad_floor3d_dxf.v0" if mode == "badgen" else "cad_floor3d_dxf.v2",
    "model_sha256": hashlib.sha256(raw).hexdigest(),
    "dxf_sha256": "f" * 64 if mode == "badsha" else hashlib.sha256(body).hexdigest(),
    "meshes": {"Q3D_ПЛИТА": 1, "Q3D_КЛАДКА": 2},
    "outlines": 2,
    "skipped": ["стена k: высота не определена"],
    "triangulation_mismatch": [],
}
print("служебная строка")
print(json.dumps(summary, ensure_ascii=False))
""".replace("DXF_BODY", repr(DXF_BODY))

NAME = f"{FOLDER}/floor3d.dxf"


@pytest.fixture
def dxf_tools(floor_tools: Path) -> Path:  # noqa: F811
    """Каталог tools/cad_walls тестов 3D-вида, дополненный заглушкой выгрузки 3D DXF."""
    (floor_tools / "run_floor3d_dxf.py").write_text(STUB, encoding="utf-8")
    return floor_tools


def _dxf_url(project_id: str, job_id: str) -> str:
    return _url(project_id, job_id, "floor3d/dxf")


def _download(project_id: str, revision_id: str, job_id: str, name: str = NAME) -> str:
    return f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}/artifacts/{name}"


async def _run_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session,
        worker_id="cad-floor3d-dxf-test",
        job_types=[t.value for t in HANDLERS],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_floor3d_dxf
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


# ------------------------------------------------------------------ без базы


def test_route_job_type_and_handler_are_registered() -> None:
    sheet = "/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}"
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths[f"{sheet}/floor3d/dxf"]) == {"post"}
    assert JobType.CAD_FLOOR3D_DXF.value == "cad_floor3d_dxf"
    assert HANDLERS[JobType.CAD_FLOOR3D_DXF] is execute_cad_floor3d_dxf
    assert JobType.CAD_FLOOR3D_DXF not in cad_service.CAD_JOB_TYPES
    assert JobType.CAD_FLOOR3D_DXF in cad_service.CAD_ARTIFACT_JOB_TYPES


def test_generator_version_matches_the_script() -> None:
    found = re.search(r'^GENERATOR_VERSION: Final = "([^"]+)"', SCRIPT.read_text("utf-8"), re.M)
    assert found is not None
    assert found.group(1) == floor3d_service.GENERATOR_VERSION


def test_artifact_name_is_closed() -> None:
    revision, job = uuid.uuid4(), uuid.uuid4()
    key = cad_service.artifact_storage_key(revision, job, 1, NAME)
    assert key.endswith(f"/attempt-1/{NAME}")
    for bad in ("floor3d.dxf", f"{FOLDER}/floor3d.json", f"{FOLDER}/../floor3d.dxf"):
        with pytest.raises(ValueError, match="артефакта"):
            cad_service.artifact_storage_key(revision, job, 1, bad)


# ------------------------------------------------------------------ доступ


async def test_route_is_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(
        make_context(), settings=walls_settings(dxf_tools, tmp_path, flag=False)
    ) as api:
        response = await api.post(_dxf_url(str(uuid.uuid4()), str(uuid.uuid4())))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_foreign_workspace_and_viewer_cannot_queue_or_download(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(dxf_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        queued = await api.post(_dxf_url(project_id, job_id))
        assert queued.status_code == 202, queued.text
        floor_id = queued.json()["job_id"]
        await _run_worker(db_session, fake_storage, settings, floor_id)

    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=settings) as reader:
        assert (await reader.post(_dxf_url(project_id, job_id))).status_code == 403
        # Читать результат зритель может: скачивание — право чтения.
        assert (await reader.get(_download(project_id, revision_id, floor_id))).status_code == 200

    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.post(_dxf_url(project_id, job_id))).status_code == 404
        downloaded = await foreign.get(_download(project_id, revision_id, floor_id))
        assert downloaded.status_code == 404


async def test_not_ready_walls_give_not_ready_error(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    from tests.test_cad_mep import _parent

    settings = walls_settings(dxf_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _base = await _parent(api, db_session, fake_storage)
        response = await api.post(_dxf_url(project_id, job_id))
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "CAD_WALLS_NOT_READY"
    assert not [k for k in fake_storage.objects if "floor3d-input" in k]


# ------------------------------------------------------------------ постановка и идемпотентность


async def test_queue_stores_the_same_model_as_get_and_is_idempotent(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(dxf_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        model = (await api.get(_url(project_id, job_id, "floor3d"))).json()
        queued = await api.post(_dxf_url(project_id, job_id))
        assert queued.status_code == 202, queued.text
        body = queued.json()
        assert set(body) == {
            "job_id",
            "parent_job_id",
            "page_index",
            "view",
            "status",
            "attempt",
            "created_at",
        }
        assert (body["parent_job_id"], body["page_index"], body["view"]) == (job_id, 0, 1)
        assert (body["status"], body["attempt"]) == ("queued", 0)

        job = await db_session.get(Job, uuid.UUID(body["job_id"]))
        assert job is not None and job.job_type is JobType.CAD_FLOOR3D_DXF
        payload = job.payload
        assert payload["revision_id"] == revision_id and payload["parent_job_id"] == job_id
        assert payload["generator_version"] == "cad_floor3d_dxf.v2"
        key = floor3d_service.input_key(uuid.UUID(revision_id), payload["model_sha256"])
        stored = fake_storage.objects[key]
        assert hashlib.sha256(stored).hexdigest() == payload["model_sha256"]
        assert payload["model_size"] == len(stored)
        assert json.loads(stored) == model

        again = await api.post(_dxf_url(project_id, job_id))
        assert again.status_code == 202 and again.json()["job_id"] == body["job_id"]

        # Другая модель (решение по отверстию) — другой вход и новое задание.
        holes = model["slab_holes"]
        put = await api.put(
            _url(project_id, job_id, f"floor3d/holes/{holes[0]['key']}"), json={"enabled": False}
        )
        assert put.status_code == 200, put.text
        changed = await api.post(_dxf_url(project_id, job_id))
        assert changed.json()["job_id"] != body["job_id"]
        assert len([k for k in fake_storage.objects if "floor3d-input" in k]) == 2


async def test_succeeded_job_is_returned_again_and_file_is_downloadable(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(dxf_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        floor_id = (await api.post(_dxf_url(project_id, job_id))).json()["job_id"]
        job = await _run_worker(db_session, fake_storage, settings, floor_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)

        result = cad_service.result_of(job)
        assert result["result_status"] == "floor3d_dxf_ready" and result["attempt"] == 1
        assert result["counts"]["meshes"] == {"Q3D_ПЛИТА": 1, "Q3D_КЛАДКА": 2}
        assert result["counts"]["skipped"] == 1
        [artifact] = result["artifacts"]
        assert artifact["name"] == NAME
        assert artifact["sha256"] == hashlib.sha256(DXF_BODY).hexdigest()
        assert artifact["key"] == f"revisions/{revision_id}/cad/{floor_id}/attempt-1/{NAME}"
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"

        scripts = json.loads((dxf_tools / "args.json").read_text(encoding="utf-8"))
        assert scripts == {"model_name": "floor3d_model.json", "out_name": "floor3d.dxf"}

        file = await api.get(_download(project_id, revision_id, floor_id))
        assert file.status_code == 200 and file.content == DXF_BODY
        assert file.headers["x-content-sha256"] == artifact["sha256"]
        assert file.headers["content-type"].startswith("application/dxf")
        # Чужое имя у этого задания не отдаётся.
        missing = await api.get(_download(project_id, revision_id, floor_id, "report.json"))
        assert missing.status_code == 404

        # Повтор с той же моделью и версией скрипта — то же успешное задание, без нового.
        again = await api.post(_dxf_url(project_id, job_id))
        assert again.json()["job_id"] == floor_id and again.json()["status"] == "succeeded"

        # Задание 3D DXF не попадает ни в историю заданий ревизии, ни в общее чтение задания.
        listed = (
            await api.get(f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad")
        ).json()
        assert floor_id not in {row["job_id"] for row in listed["items"]}
        read = await api.get(
            f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{floor_id}"
        )
        assert read.status_code == 404


# ------------------------------------------------------------------ исполнитель


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("fail", "CAD_INPUT_INVALID"),
        ("badsha", "CAD_ENGINE_FAILED"),
        ("badgen", "CAD_ENGINE_FAILED"),
        ("extra", "CAD_ENGINE_FAILED"),
        ("empty", "CAD_ENGINE_FAILED"),
    ],
)
async def test_worker_rejects_bad_script_output_and_repost_makes_a_new_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    dxf_tools: Path,
    tmp_path: Path,
    mode: str,
    code: str,
) -> None:
    settings = walls_settings(dxf_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        (dxf_tools / "mode").write_text(mode)
        floor_id = (await api.post(_dxf_url(project_id, job_id))).json()["job_id"]
        job = await _run_worker(db_session, fake_storage, settings, floor_id)
        assert job.status is JobStatus.FAILED and job.error_code == code, job.error_message
        assert not [k for k in fake_storage.objects if k.endswith("floor3d.dxf")]
        assert not any((tmp_path / "work").rglob("*"))
        denied = await api.get(_download(project_id, revision_id, floor_id))
        assert denied.status_code == 409

        # Отказавшее задание не блокирует выгрузку: та же модель ставится заново.
        (dxf_tools / "mode").write_text("")
        retried = (await api.post(_dxf_url(project_id, job_id))).json()
        assert retried["job_id"] != floor_id and retried["status"] == "queued"


async def test_worker_fails_when_the_model_object_is_gone(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(dxf_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        floor_id = (await api.post(_dxf_url(project_id, job_id))).json()["job_id"]
        for key in [k for k in fake_storage.objects if "floor3d-input" in k]:
            del fake_storage.objects[key]
        job = await _run_worker(db_session, fake_storage, settings, floor_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_INPUT_INVALID"


async def test_worker_fails_when_the_script_is_not_installed(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    dxf_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(dxf_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        floor_id = (await api.post(_dxf_url(project_id, job_id))).json()["job_id"]
        (dxf_tools / "run_floor3d_dxf.py").unlink()
        job = await _run_worker(db_session, fake_storage, settings, floor_id)
        assert job.status is JobStatus.FAILED and job.error_code == "CAD_ENGINE_UNAVAILABLE"
