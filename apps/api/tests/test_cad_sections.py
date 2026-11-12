"""Разрезы АР (`cad_sections`): задание, кандидаты уровней, решения человека, перенос решений.

Генератор не нужен: `cad_mep/run_sections.py` подменён заглушкой, которая пишет фиксированный
`sections.json` (синтетика) по CLI-контракту. Режим заглушки задаёт файл `mode` рядом со скриптом:
`fail` - код выхода 2, `bad_schema`/`bad_sha`/`bad_page`/`extra_file` - файл вне контракта,
`v2` - у уровня Б другая толщина перекрытия (решение по нему не переносится),
`v3` - схема `cad_sections.v3` с окном и ролями sill/window/above_window у первого уровня,
`bad_v4` - неизвестная схема `cad_sections.v4`.
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

from app.auth.dev import DEV_USER_ID
from app.cad_worker import HANDLERS
from app.cad_worker.sections_handler import execute_cad_sections
from app.contracts.cad_sections import SectionLevelFile
from app.core.config import Settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadSectionLevel, Job, Workspace
from app.services import cad as cad_service
from app.services import cad_sections
from app.services import jobs as jobs_service
from tests.cad_pins_helper import write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload

PARAMS = {"pipe_diameter": {"value": 50, "unit": "mm", "source": "assumed", "note": "тест"}}

STUB = """
import argparse, hashlib, json, pathlib, sys

parser = argparse.ArgumentParser()
parser.add_argument("--pdf")
parser.add_argument("--pages", nargs="*")
parser.add_argument("--params")
parser.add_argument("--out")
args = parser.parse_args()
here = pathlib.Path(__file__).parent
mode = (here / "mode").read_text().strip() if (here / "mode").exists() else ""
for name in ("pdf", "params"):
    if not pathlib.Path(getattr(args, name)).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
(here / "args.json").write_text(json.dumps({
    "pages": args.pages, "out_name": pathlib.Path(args.out).name,
    "params_name": pathlib.Path(args.params).name}))
if mode == "fail":
    print("служебная строка", file=sys.stderr)
    print(json.dumps({"code": "no_sections", "message": "Разрезы не найдены"}), file=sys.stderr)
    sys.exit(2)
box = [0.1, 0.1, 0.2, 0.2]


def level(elevation, upper, clear, structure, cut):
    dims = [] if clear is None else [{"value_mm": clear, "role": "clear", "bbox": box}]
    return {
        "elevation_mm": elevation, "upper_elevation_mm": upper, "floor": None,
        "clear_height_mm": clear, "structure_mm": structure, "cut": cut, "source": "observed",
        "evidence": "отм. %d / %d" % (elevation, upper),
        "markup": {"upper_mark": box, "lower_mark": box, "band": [0.1, 0.1, 0.3, 0.4],
                   "dims": dims},
    }


structure_b = 350 if mode == "v2" else 300
sections = [
    {"page_index": 0, "title": "Разрез 1-1", "corps": "9", "section": "3", "cuts": ["1-1"],
     "page_size_pt": [841.9, 595.3], "rotation": 0,
     "levels": [level(47600, 50900, 3000, 300, "1-1"),
                level(50900, 54200, 3000, structure_b, "1-1"),
                level(54200, 57500, None, None, "1-1")]},
    {"page_index": 1, "title": "Разрез 2-2", "corps": "10", "section": "4", "cuts": ["2-2"],
     "page_size_pt": [841.9, 595.3], "rotation": 90,
     "levels": [level(47600, 51200, 3200, 400, "2-2")]},
]
if args.pages:
    wanted = {int(p) for p in args.pages}
    sections = [s for s in sections if s["page_index"] in wanted]
if mode == "bad_page":
    sections[0]["page_index"] = 7
schemas = {"bad_schema": "cad_sections.v1", "v3": "cad_sections.v3", "bad_v4": "cad_sections.v4"}
if mode in ("v3", "bad_v4"):
    first = sections[0]["levels"][0]
    first["markup"]["dims"] = [
        {"value_mm": 300, "role": "structure", "bbox": box},
        {"value_mm": 900, "role": "sill", "bbox": box},
        {"value_mm": 1500, "role": "window", "bbox": box},
        {"value_mm": 600, "role": "above_window", "bbox": box},
    ]
    first["windows"] = [
        {"sill_mm": 900, "height_mm": 1500, "head_mm": 2400, "source": "observed",
         "dims": [1, 2, 3], "bbox": [0.1, 0.1, 0.2, 0.2], "cut": "1-1"}
    ]
doc = {
    "schema": schemas.get(mode, "cad_sections.v2"),
    "generator_version": "cad_mep.v9",
    "source": {"pdf_sha256": "0" * 64 if mode == "bad_sha"
               else hashlib.sha256(pathlib.Path(args.pdf).read_bytes()).hexdigest(),
               "pages": [s["page_index"] for s in sections]},
    "sections": sections,
    "issues": [
        {"code": "slab_thickness_assumed", "message": "Толщина плиты по умолчанию",
         "page_index": 0, "bbox": box},
        {"code": "no_dimensions", "message": "Нет размеров", "page_index": None, "bbox": None},
    ],
}
out = pathlib.Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
if mode == "extra_file":
    (out.parent / "extra.txt").write_text("лишнее")
"""


@pytest.fixture
def sections_tools(tmp_path: Path) -> Path:
    """Параметры, версия и заглушка CLI разрезов: то, что в образе лежит в generators/cad_mep."""
    root = tmp_path / "tools" / "cad_mep"
    (root / "params").mkdir(parents=True)
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_mep.py").write_text("", encoding="utf-8")
    (root / "run_sections.py").write_text(STUB, encoding="utf-8")
    return root


def sections_settings(tools: Path, tmp_path: Path, *, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_mep_runner=str(tools / "run_mep.py"),
        cad_mep_params=str(tools / "params" / "v1.json"),
        cad_engine_pins=write_pins(tmp_path, mep=tools / "params" / "v1.json"),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _run_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session,
        worker_id="cad-sections-test",
        job_types=[t.value for t in HANDLERS],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_sections
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


async def _queue(
    api: AsyncClient, project_id: str, revision_id: str, pages: list[int] | None = None
) -> str:
    response = await api.post(
        f"/api/v1/projects/{project_id}/cad/sections/jobs",
        json={"revision_id": revision_id, "page_indexes": pages},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _levels_url(project_id: str, revision_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/sections?revision_id={revision_id}"


def _set_mode(tools: Path, mode: str) -> None:
    (tools / "mode").write_text(mode, encoding="utf-8")


# ------------------------------------------------------------------ без базы


def test_sections_routes_job_type_and_artifact_name_are_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert "/api/v1/projects/{project_id}/cad/sections" in paths
    assert "/api/v1/projects/{project_id}/cad/sections/jobs" in paths
    assert "/api/v1/projects/{project_id}/cad/sections/levels/decide" in paths
    assert HANDLERS[JobType.CAD_SECTIONS] is execute_cad_sections
    assert JobType.CAD_SECTIONS.value == "cad_sections"
    key = cad_service.artifact_storage_key(uuid.uuid4(), uuid.uuid4(), 1, "sections.json")
    assert key.endswith("/attempt-1/sections.json")
    for bad in ("../sections.json", "views/p001_v01/sections.json", "other.json"):
        with pytest.raises(ValueError, match="артефакта"):
            cad_service.artifact_storage_key(uuid.uuid4(), uuid.uuid4(), 1, bad)


def test_idempotency_key_depends_on_pages_params_and_version_but_not_on_order() -> None:
    revision = uuid.uuid4()

    def key(pages: list[int] | None, params: str = "p", version: str = "v") -> str:
        return cad_sections.idempotency_key(
            revision, params_sha256=params, generator_version=version, page_indexes=pages
        )

    assert key([2, 0, 1]) == key([0, 1, 2])
    assert len({key(None), key([0]), key([0, 1]), key([0], "q"), key([0], "p", "w")}) == 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9", {"9"}),
        ("Корпус 9", {"9"}),
        ("2-4", {"2", "3", "4"}),
        ("1, 2", {"1", "2"}),
        ("секция 3", {"3"}),
        ("Корпус А", {"а"}),
        (None, set()),
        ("", set()),
    ],
)
def test_marks_normalize_corps_and_section(raw: str | None, expected: set[str]) -> None:
    assert cad_sections.marks(raw) == frozenset(expected)


# ------------------------------------------------------------------ задание


async def test_job_publishes_candidates_and_the_artifact(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        empty = (await api.get(_levels_url(project_id, revision_id))).json()
        assert empty["job"] is None and empty["levels"] == [] and empty["pages"] == []

        job_id = await _queue(api, project_id, revision_id)
        queued = (await api.get(_levels_url(project_id, revision_id))).json()
        assert queued["job"]["status"] == "queued" and queued["result_job_id"] is None

        job = await _run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"
        assert json.loads((sections_tools / "args.json").read_text())["pages"] is None

        result = cad_service.result_of(job)
        assert result["generator_version"] == "cad_mep.v1"
        assert result["params_sha256"] == cad_service.params_sha256(PARAMS)
        assert result["input_sha256"] == _sha(BROKEN_PDF)
        assert result["counts"] == {"pages": 2, "levels": 4, "issues": 2}
        [artifact] = result["artifacts"]
        assert artifact["name"] == "sections.json"
        assert artifact["key"] in fake_storage.objects

        read = (await api.get(_levels_url(project_id, revision_id))).json()
        assert read["job"]["status"] == "succeeded" and read["result_job_id"] == job_id
        levels = read["levels"]
        assert [(row["page_index"], row["seq"]) for row in levels] == [
            (0, 0),
            (0, 1),
            (0, 2),
            (1, 3),
        ]
        first = levels[0]
        assert first["status"] == "candidate" and first["decided_by"] is None
        assert (first["elevation_mm"], first["upper_elevation_mm"]) == (47600, 50900)
        assert (first["clear_height_mm"], first["structure_mm"]) == (3000, 300)
        assert (first["corps"], first["section"], first["cut"]) == ("9", "3", "1-1")
        assert first["markup"]["band"] == [0.1, 0.1, 0.3, 0.4]
        assert first["markup"]["dims"] == [
            {"value_mm": 3000, "role": "clear", "bbox": [0.1, 0.1, 0.2, 0.2]}
        ]
        assert levels[2]["clear_height_mm"] is None
        assert [
            (p["page_index"], p["title"], p["corps"], p["rotation"]) for p in read["pages"]
        ] == [
            (0, "Разрез 1-1", "9", 0),
            (1, "Разрез 2-2", "10", 90),
        ]
        assert read["pages"][0]["cuts"] == ["1-1"] and read["pages"][0]["page_size_pt"] == [
            841.9,
            595.3,
        ]
        assert [i["code"] for i in read["issues"]] == ["slab_thickness_assumed", "no_dimensions"]
        assert read["issues"][1]["page_index"] is None and read["issues"][1]["bbox"] is None


async def test_v3_file_with_windows_is_accepted_and_the_new_roles_reach_the_api(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    _set_mode(sections_tools, "v3")
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        job_id = await _queue(api, project_id, revision_id)
        job = await _run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        levels = (await api.get(_levels_url(project_id, revision_id))).json()["levels"]
        assert [d["role"] for d in levels[0]["markup"]["dims"]] == [
            "structure",
            "sill",
            "window",
            "above_window",
        ]
        # окна разреза в уровень API не попадают: высоты окон плана из них не берутся
        assert "windows" not in levels[0]


def test_sections_file_reads_windows_in_v3_and_defaults_them_to_empty_in_v2() -> None:
    box = [0.1, 0.1, 0.2, 0.2]
    level: dict[str, Any] = {
        "elevation_mm": 47600,
        "upper_elevation_mm": 50900,
        "source": "observed",
        "evidence": "отм.",
        "markup": {
            "upper_mark": box,
            "lower_mark": box,
            "band": box,
            "dims": [{"value_mm": 900, "role": "sill", "bbox": box}],
        },
    }
    assert SectionLevelFile.model_validate(level).windows == []
    window = {
        "sill_mm": 900,
        "height_mm": 1500,
        "head_mm": 2400,
        "source": "observed",
        "dims": [0],
        "bbox": box,
        "cut": None,
    }
    parsed = SectionLevelFile.model_validate({**level, "windows": [window]})
    assert [(w.sill_mm, w.height_mm, w.head_mm, w.dims) for w in parsed.windows] == [
        (900, 1500, 2400, [0])
    ]
    assert SectionLevelFile.model_validate({**level, "windows": []}).windows == []


async def test_scheduling_is_idempotent_and_pages_reach_the_generator(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        first = await _queue(api, project_id, revision_id, [1, 0])
        assert await _queue(api, project_id, revision_id, [0, 1]) == first
        assert await _queue(api, project_id, revision_id, None) != first
        base = f"/api/v1/projects/{project_id}/cad/sections/jobs"
        for body in (
            {"revision_id": revision_id, "page_indexes": []},
            {"revision_id": revision_id, "page_indexes": [0, 0]},
            {"revision_id": revision_id, "page_indexes": [-1]},
            {"revision_id": revision_id, "extra": 1},
        ):
            assert (await api.post(base, json=body)).status_code == 422, body
        missing = await api.post(base, json={"revision_id": str(uuid.uuid4())})
        assert missing.status_code == 404

        job = await _run_worker(db_session, fake_storage, settings, first)
        assert job.status is JobStatus.SUCCEEDED
        assert json.loads((sections_tools / "args.json").read_text())["pages"] == ["0", "1"]
        assert job.payload["page_indexes"] == [0, 1]


@pytest.mark.parametrize(
    ("mode", "error_code", "message"),
    [
        ("fail", "CAD_INPUT_INVALID", "Разрезы не найдены"),
        ("bad_schema", "CAD_ENGINE_FAILED", "вне контракта"),
        ("bad_v4", "CAD_ENGINE_FAILED", "вне контракта"),
        ("bad_sha", "CAD_ENGINE_FAILED", "другому PDF"),
        ("bad_page", "CAD_ENGINE_FAILED", "вне задания"),
        ("extra_file", "CAD_ENGINE_FAILED", "состав out/"),
    ],
)
async def test_generator_failure_fails_the_job_and_publishes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
    mode: str,
    error_code: str,
    message: str,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    _set_mode(sections_tools, mode)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        before = set(fake_storage.objects)
        job_id = await _queue(api, project_id, revision_id, [0])

        job = await _run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == error_code and message in (job.error_message or "")
        assert set(fake_storage.objects) == before, "неудачная попытка ничего не публикует"
        assert not any((tmp_path / "work").rglob("*"))
        count = await db_session.scalar(select(func.count()).select_from(CadSectionLevel))
        assert count == 0

        read = (await api.get(_levels_url(project_id, revision_id))).json()
        assert read["job"]["status"] == "failed" and read["job"]["error_code"] == error_code
        assert read["levels"] == [] and read["issues"] == [] and read["result_job_id"] is None


async def test_worker_fails_closed_when_the_pin_does_not_match_the_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        job_id = await _queue(api, project_id, revision_id)
        job = await db_session.get(Job, uuid.UUID(job_id))
        assert job is not None
        await db_session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(payload={**job.payload, "generator_version": "cad_mep.v0"})
        )
        await db_session.commit()
        db_session.expire_all()

        failed = await _run_worker(db_session, fake_storage, settings, job_id)
        assert failed.status is JobStatus.FAILED and failed.error_code == "CAD_PARAMS_INVALID"
        assert not (sections_tools / "args.json").exists(), "генератор не запускался"


async def test_sections_are_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    base = f"/api/v1/projects/{uuid.uuid4()}/cad/sections"
    settings = sections_settings(sections_tools, tmp_path, flag=False)
    async with build_api(make_context(), settings=settings) as api:
        posts = (
            (f"{base}/jobs", {"revision_id": str(uuid.uuid4())}),
            (f"{base}/levels/decide", {"level_ids": [str(uuid.uuid4())], "decision": "accept"}),
        )
        for path, body in posts:
            response = await api.post(path, json=body)
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", path
        read = await api.get(f"{base}?revision_id={uuid.uuid4()}")
        assert read.status_code == 403 and read.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_foreign_workspace_sees_nothing_of_the_sections(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        job_id = await _queue(api, project_id, revision_id)
        assert (await _run_worker(db_session, fake_storage, settings, job_id)).status is (
            JobStatus.SUCCEEDED
        )
        level_id = (await api.get(_levels_url(project_id, revision_id))).json()["levels"][0]["id"]
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        base = f"/api/v1/projects/{project_id}/cad/sections"
        assert (await foreign.get(f"{base}?revision_id={revision_id}")).status_code == 404
        scheduled = await foreign.post(f"{base}/jobs", json={"revision_id": revision_id})
        assert scheduled.status_code == 404
        decided = await foreign.post(
            f"{base}/levels/decide", json={"level_ids": [level_id], "decision": "accept"}
        )
        assert decided.status_code == 404


# ------------------------------------------------------------------ решения человека


async def _published(
    api: AsyncClient,
    db_session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Settings,
    pages: list[int] | None = None,
) -> tuple[str, str, list[dict[str, Any]]]:
    project_id, revision_id = await _upload(api, BROKEN_PDF)
    job_id = await _queue(api, project_id, revision_id, pages)
    job = await _run_worker(db_session, storage, settings, job_id)
    assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
    levels = (await api.get(_levels_url(project_id, revision_id))).json()["levels"]
    return project_id, revision_id, levels


async def test_decisions_accept_reject_reset_and_their_guards(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, levels = await _published(api, db_session, fake_storage, settings)
        decide = f"/api/v1/projects/{project_id}/cad/sections/levels/decide"
        a, b, no_clear, d = (row["id"] for row in levels)

        accepted = await api.post(decide, json={"level_ids": [a, b], "decision": "accept"})
        assert accepted.status_code == 200, accepted.text
        rows = accepted.json()["levels"]
        assert [r["id"] for r in rows] == [a, b]
        assert all(r["status"] == "accepted" and r["decided_by"] == str(DEV_USER_ID) for r in rows)
        assert all(r["decided_at"] is not None for r in rows)

        rejected = await api.post(decide, json={"level_ids": [d], "decision": "reject"})
        assert rejected.json()["levels"][0]["status"] == "rejected"

        # Принять уровень без высоты нельзя: 422, остальные уровни запроса не меняются.
        refused = await api.post(decide, json={"level_ids": [d, no_clear], "decision": "accept"})
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "VALIDATION_FAILED"
        assert "нет высоты в свету" in refused.json()["detail"]["message"]
        after = {
            r["id"]: r
            for r in (await api.get(_levels_url(project_id, revision_id))).json()["levels"]
        }
        assert after[d]["status"] == "rejected" and after[no_clear]["status"] == "candidate"
        # Отклонить такой уровень можно.
        assert (
            await api.post(decide, json={"level_ids": [no_clear], "decision": "reject"})
        ).status_code == 200

        # Высота вне пределов генератора трасс - тоже 422.
        await db_session.execute(
            update(CadSectionLevel)
            .where(CadSectionLevel.id == uuid.UUID(d))
            .values(clear_height_mm=900)
        )
        await db_session.commit()
        low = await api.post(decide, json={"level_ids": [d], "decision": "accept"})
        assert low.status_code == 422 and "вне пределов" in low.json()["detail"]["message"]

        reset = await api.post(decide, json={"level_ids": [a], "decision": "reset"})
        [row] = reset.json()["levels"]
        assert row["status"] == "candidate"
        assert row["decided_by"] is None and row["decided_at"] is None

        for body in (
            {"level_ids": [], "decision": "accept"},
            {"level_ids": [a], "decision": "approve"},
            {"level_ids": [a], "decision": "accept", "extra": 1},
        ):
            assert (await api.post(decide, json=body)).status_code == 422, body
        unknown = await api.post(
            decide, json={"level_ids": [a, str(uuid.uuid4())], "decision": "accept"}
        )
        assert unknown.status_code == 404

        # Чужой проект того же пространства: уровень не найден.
        other = (await api.post("/api/v1/projects", json={"name": "Другой"})).json()["id"]
        stranger = await api.post(
            f"/api/v1/projects/{other}/cad/sections/levels/decide",
            json={"level_ids": [a], "decision": "accept"},
        )
        assert stranger.status_code == 404
        still = {
            r["id"]: r
            for r in (await api.get(_levels_url(project_id, revision_id))).json()["levels"]
        }
        assert still[a]["status"] == "candidate"


async def test_rerun_replaces_old_rows_and_carries_decisions_over(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, levels = await _published(api, db_session, fake_storage, settings)
        decide = f"/api/v1/projects/{project_id}/cad/sections/levels/decide"
        a, b, _no_clear, d = (row["id"] for row in levels)
        await api.post(decide, json={"level_ids": [a], "decision": "accept"})
        await api.post(decide, json={"level_ids": [b], "decision": "accept"})
        await api.post(decide, json={"level_ids": [d], "decision": "reject"})
        before = {
            r["id"]: r
            for r in (await api.get(_levels_url(project_id, revision_id))).json()["levels"]
        }
        first_job = before[a]["job_id"]

        # У уровня Б другая толщина перекрытия: его решение теряется, остальные переносятся.
        _set_mode(sections_tools, "v2")
        second_job = await _queue(api, project_id, revision_id, [0, 1])
        assert second_job != first_job
        job = await _run_worker(db_session, fake_storage, settings, second_job)
        assert job.status is JobStatus.SUCCEEDED

        read = (await api.get(_levels_url(project_id, revision_id))).json()
        after = read["levels"]
        assert len(after) == 4 and {r["job_id"] for r in after} == {second_job}
        assert not {r["id"] for r in after} & set(before), "строки прежнего задания удалены"
        by_key = {(r["page_index"], r["elevation_mm"]): r for r in after}
        carried_a, changed_b = by_key[(0, 47600)], by_key[(0, 50900)]
        assert carried_a["status"] == "accepted"
        assert carried_a["decided_by"] == before[a]["decided_by"]
        assert carried_a["decided_at"] == before[a]["decided_at"]
        assert changed_b["structure_mm"] == 350 and changed_b["status"] == "candidate"
        assert changed_b["decided_by"] is None
        assert by_key[(1, 47600)]["status"] == "rejected"
        assert by_key[(0, 54200)]["status"] == "candidate"
        total = await db_session.scalar(select(func.count()).select_from(CadSectionLevel))
        assert total == 4

        # Третий запуск падает: прежние строки остаются, задание в ответе - упавшее.
        _set_mode(sections_tools, "fail")
        third_job = await _queue(api, project_id, revision_id, [1])
        failed = await _run_worker(db_session, fake_storage, settings, third_job)
        assert failed.status is JobStatus.FAILED
        read = (await api.get(_levels_url(project_id, revision_id))).json()
        assert read["job"]["job_id"] == third_job and read["job"]["status"] == "failed"
        assert read["result_job_id"] == second_job
        assert len(read["levels"]) == 4 and len(read["issues"]) == 2 and len(read["pages"]) == 2


# ------------------------------------------------------------------ уровни для трасс


async def test_unknown_floor_elevation_with_accepted_levels_warns_instead_of_skipping_silently(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    sections_tools: Path,
    tmp_path: Path,
) -> None:
    settings = sections_settings(sections_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, levels = await _published(api, db_session, fake_storage, settings)

        async def resolve(elevation: int | None) -> cad_sections.RouteLevels:
            return await cad_sections.resolve_route_levels(
                db_session,
                settings=settings,
                workspace_id=DEV_WORKSPACE_ID,
                project_id=uuid.UUID(project_id),
                floor_elevation_mm=elevation,
                plan_revision_id=uuid.UUID(revision_id),
                plan_page_index=0,
            )

        # Принятых уровней нет: предупреждать не о чем.
        assert (await resolve(None)).warnings == ()

        decide = f"/api/v1/projects/{project_id}/cad/sections/levels/decide"
        ids = [levels[0]["id"], levels[1]["id"]]
        accepted = await api.post(decide, json={"level_ids": ids, "decision": "accept"})
        assert accepted.status_code == 200, accepted.text

        unknown = await resolve(None)
        assert unknown.warnings == (cad_sections.WARNING_FLOOR_ELEVATION_UNKNOWN,)
        assert cad_sections.WARNING_FLOOR_ELEVATION_UNKNOWN == "section_floor_elevation_unknown"
        assert unknown.source == cad_sections.LEVELS_SOURCE_NONE and unknown.clear_height_mm is None

        # Отметка известна: уровни работают, предупреждения нет.
        known = await resolve(47600)
        assert known.warnings == ()
        assert known.source == cad_sections.LEVELS_SOURCE_SECTION and known.clear_height_mm == 3000
