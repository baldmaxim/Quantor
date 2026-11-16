"""Фасады АР (`cad_facades`, ADR-0048): задание, кандидаты видов, решения человека, перенос решений.

Генератор не нужен: `cad_facades/run_facades.py` подменён заглушкой, которая пишет фиксированный
`facades.json` (синтетика) по CLI-контракту. Режим заглушки задаёт файл `mode` рядом со скриптом:
`fail` - код выхода 2 и `facades_not_found`, `bad_schema`/`bad_sha`/`bad_page`/`extra_file` - файл
вне контракта, `renamed` - у второго вида другой заголовок (решение по нему не переносится).
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
from app.cad_worker.facades_handler import execute_cad_facades
from app.contracts.cad_facades import FacadesFile
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadFacadeView, Job, Workspace
from app.services import cad as cad_service
from app.services import cad_facades
from app.services import jobs as jobs_service
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload

PARAMS = {"window_gap_mm": {"value": 80, "unit": "mm", "source": "assumed", "note": "тест"}}

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
    print(json.dumps({"code": "facades_not_found", "message": "no facade titles"}),
          file=sys.stderr)
    sys.exit(2)
box = [0.1, 0.1, 0.9, 0.5]


def window(u0, u1, z0, z1):
    return {"bbox": [0.2, 0.2, 0.25, 0.3], "u0_mm": u0, "u1_mm": u1, "width_mm": u1 - u0,
            "z_bottom_mm": z0, "z_top_mm": z1, "height_mm": z1 - z0, "cells": 2, "hatch": 6,
            "sash": 0, "source": "observed"}


def view(key, page, title, a_from, a_to, body, scale, windows):
    return {
        "id": key, "page_index": page, "bbox": box, "title": title,
        "axis_from": a_from, "axis_to": a_to, "corps": "9", "section": None, "body": body,
        "image_cover": 0.0 if body == "vector" else 1.0,
        "scale": {"status": scale, "mm_per_pt": 35.28 if scale in ("fitted", "weak") else None,
                  "residual_mm": 1.5 if scale in ("fitted", "weak") else None, "marks_used": 3},
        "axes": [{"label": a_from or "1", "label_full": None, "x": 0.1, "y": 0.6, "u_mm": 0},
                 {"label": a_to or "5", "label_full": None, "x": 0.9, "y": 0.6, "u_mm": 17202}],
        "marks": [{"value_mm": 6460, "text": "+6.460", "bbox": [0.0, 0.1, 0.05, 0.12],
                   "tip": [0.04, 0.11], "used": True, "fit_dev_mm": 2},
                  {"value_mm": 0, "text": "±0.000", "bbox": [0.0, 0.4, 0.05, 0.42],
                   "tip": None, "used": False, "fit_dev_mm": None}],
        "floors": [{"label": "2 этаж", "floor": 2, "mark_mm": 6460, "label_z_mm": 6460,
                    "bbox": [0.0, 0.1, 0.05, 0.12]}],
        "windows": windows,
    }


second_title = "Фасад 5-1" if mode == "renamed" else "Фасад 1-13"
views = [
    view("p0v1", 0, "Фасад в осях 1-5", "1", "5", "vector", "fitted",
         [window(0, 1500, 7360, 8860), window(2000, 3500, 7360, 8860)]),
    view("p0v2", 0, second_title, "1", "13", "raster", "weak", []),
    view("p1v1", 1, "Фасад в осях А-Г", "А", "Г", "vector", "text_only", []),
]
if args.pages:
    wanted = {int(p) for p in args.pages}
    views = [v for v in views if v["page_index"] in wanted]
if mode == "bad_page":
    views[0]["page_index"] = 7
if mode == "nan":
    views[0]["scale"]["mm_per_pt"] = float("nan")
if mode == "nul":
    views[0]["title"] = "Фасад\\u0000"
if mode == "shifted":
    views[0]["windows"][0]["z_bottom_mm"] = 7361
doc = {
    "schema": "cad_facades.v0" if mode == "bad_schema" else "cad_facades.v1",
    "generator_version": "cad_facades.v9" if mode == "bad_version" else "cad_facades.v1",
    "params": {"version": "v1", "sha256": "0" * 64},
    "source": {"pdf_sha256": "0" * 64 if mode == "bad_sha"
               else hashlib.sha256(pathlib.Path(args.pdf).read_bytes()).hexdigest(),
               "pages": sorted({v["page_index"] for v in views})},
    "views": views,
    "issues": [
        {"code": "facade_raster", "message": "Фасад нарисован картинкой", "page_index": 0,
         "bbox": box},
        {"code": "facade_scale_text_only", "message": "Нет знака отметки", "page_index": None,
         "bbox": None},
    ],
}
out = pathlib.Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
if mode == "extra_file":
    (out.parent / "extra.txt").write_text("лишнее")
"""


@pytest.fixture
def facades_tools(tmp_path: Path) -> Path:
    """Параметры и заглушка CLI фасадов: то, что в образе лежит в generators/cad_facades."""
    root = tmp_path / "tools" / "cad_facades"
    (root / "params").mkdir(parents=True)
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_facades.py").write_text(STUB, encoding="utf-8")
    return root


def _write_pins(tmp_path: Path, params: Path | None) -> str:
    generators: dict[str, Any] = {"path": "generators"}
    if params is not None:
        raw = params.read_bytes()
        generators["cad_facades"] = {
            "generator_version": "cad_facades.v1",
            "params_path": f"generators/cad_facades/params/{params.name}",
            "params_sha256": hashlib.sha256(raw).hexdigest(),
            "params_canonical_sha256": cad_service.params_sha256(json.loads(raw)),
        }
    target = tmp_path / "pins.json"
    target.write_text(
        json.dumps({"schema": "quantor.cad_engine.pins.v1", "generators": generators}),
        encoding="utf-8",
    )
    return str(target)


def facades_settings(
    tools: Path, tmp_path: Path, *, flag: bool = True, pinned: bool = True
) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
        cad_facades_runner=str(tools / "run_facades.py"),
        cad_facades_params=str(tools / "params" / "v1.json"),
        cad_engine_pins=_write_pins(tmp_path, tools / "params" / "v1.json" if pinned else None),
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
        worker_id="cad-facades-test",
        job_types=[t.value for t in HANDLERS],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_facades
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


async def _queue(
    api: AsyncClient, project_id: str, revision_id: str, pages: list[int] | None = None
) -> str:
    response = await api.post(
        f"/api/v1/projects/{project_id}/cad/facades/jobs",
        json={"revision_id": revision_id, "page_indexes": pages},
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _views_url(project_id: str, revision_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/facades?revision_id={revision_id}"


def _decide_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/facades/views/decide"


def _set_mode(tools: Path, mode: str) -> None:
    (tools / "mode").write_text(mode, encoding="utf-8")


# ------------------------------------------------------------------ без базы


def test_facades_routes_and_job_type_are_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert "/api/v1/projects/{project_id}/cad/facades" in paths
    assert "/api/v1/projects/{project_id}/cad/facades/jobs" in paths
    assert "/api/v1/projects/{project_id}/cad/facades/views/decide" in paths
    assert HANDLERS[JobType.CAD_FACADES] is execute_cad_facades
    assert JobType.CAD_FACADES.value == "cad_facades"


def test_idempotency_key_depends_on_pages_params_and_version_but_not_on_order() -> None:
    revision = uuid.uuid4()

    def key(pages: list[int] | None, params: str = "p", version: str = "v") -> str:
        return cad_facades.idempotency_key(
            revision, params_sha256=params, generator_version=version, page_indexes=pages
        )

    assert key([2, 0, 1]) == key([0, 1, 2])
    assert key(None).startswith("cadfacades:")
    assert len({key(None), key([0]), key([0, 1]), key([0], "q"), key([0], "p", "w")}) == 5


def test_facades_file_ignores_extra_fields_and_defaults_the_lists() -> None:
    box = [0.1, 0.1, 0.2, 0.2]
    document = FacadesFile.model_validate(
        {
            "generator_version": "cad_facades.v1",
            "source": {"pdf_sha256": "0" * 64, "pages": [3]},
            "views": [
                {
                    "id": "p3v1",
                    "page_index": 3,
                    "bbox": box,
                    "title": "Фасад 1-13",
                    "body": "raster",
                    "scale": {"status": "none", "новое_поле": 1},
                }
            ],
        }
    )
    [view] = document.views
    assert (view.axes, view.marks, view.floors, view.windows) == ([], [], [], [])
    assert view.scale.mm_per_pt is None and document.issues == []


# ------------------------------------------------------------------ задание


async def test_job_publishes_candidates_windows_and_the_artifact(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        empty = (await api.get(_views_url(project_id, revision_id))).json()
        assert empty["job"] is None and empty["views"] == [] and empty["issues"] == []

        job_id = await _queue(api, project_id, revision_id)
        queued = (await api.get(_views_url(project_id, revision_id))).json()
        assert queued["job"]["status"] == "queued" and queued["result_job_id"] is None

        job = await _run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"
        assert json.loads((facades_tools / "args.json").read_text())["pages"] is None

        result = cad_service.result_of(job)
        assert result["generator_version"] == "cad_facades.v1"
        assert result["params_sha256"] == cad_service.params_sha256(PARAMS)
        assert result["input_sha256"] == _sha(BROKEN_PDF)
        assert result["counts"] == {"views": 3, "windows": 2, "issues": 2}
        [artifact] = result["artifacts"]
        assert artifact["name"] == "facades.json"
        assert artifact["key"] in fake_storage.objects

        read = (await api.get(_views_url(project_id, revision_id))).json()
        assert read["job"]["status"] == "succeeded" and read["result_job_id"] == job_id
        views = read["views"]
        assert [(v["page_index"], v["seq"], v["view_key"]) for v in views] == [
            (0, 0, "p0v1"),
            (0, 1, "p0v2"),
            (1, 2, "p1v1"),
        ]
        assert all(v["status"] == "candidate" and v["decided_by"] is None for v in views)
        first = views[0]
        assert (first["title"], first["axis_from"], first["axis_to"]) == (
            "Фасад в осях 1-5",
            "1",
            "5",
        )
        assert (first["corps"], first["section"], first["body"]) == ("9", None, "vector")
        assert (first["scale_status"], first["mm_per_pt"], first["residual_mm"]) == (
            "fitted",
            35.28,
            1.5,
        )
        assert first["window_count"] == 2 and len(first["windows"]) == 2
        assert first["windows"][0]["z_bottom_mm"] == 7360
        assert first["windows"][0]["height_mm"] == 1500
        assert first["windows"][1]["u0_mm"] == 2000
        assert [a["u_mm"] for a in first["axes"]] == [0, 17202]
        assert first["marks"][0]["tip"] == [0.04, 0.11] and first["marks"][1]["tip"] is None
        assert first["floors"][0]["label"] == "2 этаж" and first["bbox"] == [0.1, 0.1, 0.9, 0.5]
        assert (views[1]["body"], views[1]["window_count"]) == ("raster", 0)
        assert views[2]["scale_status"] == "text_only"
        assert [i["code"] for i in read["issues"]] == ["facade_raster", "facade_scale_text_only"]
        assert read["issues"][1]["page_index"] is None and read["issues"][1]["bbox"] is None


async def test_scheduling_is_idempotent_and_pages_reach_the_generator(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        first = await _queue(api, project_id, revision_id, [1, 0])
        assert await _queue(api, project_id, revision_id, [0, 1]) == first
        assert await _queue(api, project_id, revision_id, None) != first
        base = f"/api/v1/projects/{project_id}/cad/facades/jobs"
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
        assert json.loads((facades_tools / "args.json").read_text())["pages"] == ["0", "1"]
        assert job.payload["page_indexes"] == [0, 1]


async def test_scheduling_says_the_generator_is_not_configured_without_a_pin(
    build_api: Callable[..., AsyncClient], facades_tools: Path, tmp_path: Path
) -> None:
    settings = facades_settings(facades_tools, tmp_path, pinned=False)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        response = await api.post(
            f"/api/v1/projects/{project_id}/cad/facades/jobs", json={"revision_id": revision_id}
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "CAD_ENGINE_UNAVAILABLE"
        assert "Генератор фасадов не настроен" in response.text


@pytest.mark.parametrize(
    ("mode", "error_code", "message"),
    [
        ("fail", "CAD_INPUT_INVALID", "не найдено видов фасада с заголовком"),
        ("bad_schema", "CAD_ENGINE_FAILED", "вне контракта"),
        ("bad_sha", "CAD_ENGINE_FAILED", "другому PDF"),
        ("bad_page", "CAD_ENGINE_FAILED", "вне задания"),
        ("extra_file", "CAD_ENGINE_FAILED", "состав out/"),
        ("nan", "CAD_ENGINE_FAILED", "вне контракта"),
        ("nul", "CAD_ENGINE_FAILED", "вне контракта"),
        ("bad_version", "CAD_ENGINE_FAILED", "другой версией генератора"),
    ],
)
async def test_generator_failure_fails_the_job_and_publishes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
    mode: str,
    error_code: str,
    message: str,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    _set_mode(facades_tools, mode)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        before = set(fake_storage.objects)
        job_id = await _queue(api, project_id, revision_id, [0])

        job = await _run_worker(db_session, fake_storage, settings, job_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == error_code and message in (job.error_message or "")
        assert set(fake_storage.objects) == before, "неудачная попытка ничего не публикует"
        assert not any((tmp_path / "work").rglob("*"))
        count = await db_session.scalar(select(func.count()).select_from(CadFacadeView))
        assert count == 0

        read = (await api.get(_views_url(project_id, revision_id))).json()
        assert read["job"]["status"] == "failed" and read["job"]["error_code"] == error_code
        assert read["views"] == [] and read["issues"] == [] and read["result_job_id"] is None


async def test_worker_fails_closed_when_the_pin_does_not_match_the_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        job_id = await _queue(api, project_id, revision_id)
        job = await db_session.get(Job, uuid.UUID(job_id))
        assert job is not None
        await db_session.execute(
            update(Job)
            .where(Job.id == job.id)
            .values(payload={**job.payload, "generator_version": "cad_facades.v0"})
        )
        await db_session.commit()
        db_session.expire_all()

        failed = await _run_worker(db_session, fake_storage, settings, job_id)
        assert failed.status is JobStatus.FAILED and failed.error_code == "CAD_PARAMS_INVALID"
        assert not (facades_tools / "args.json").exists(), "генератор не запускался"


# ------------------------------------------------------------------ решения человека


async def test_decisions_accept_reject_reset_and_the_unbound_view_cannot_be_accepted(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        job_id = await _queue(api, project_id, revision_id)
        assert (await _run_worker(db_session, fake_storage, settings, job_id)).status is (
            JobStatus.SUCCEEDED
        )
        views = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        fitted, weak, text_only = (v["id"] for v in views)

        accepted = await api.post(
            _decide_url(project_id), json={"view_ids": [fitted, weak], "decision": "accept"}
        )
        assert accepted.status_code == 200, accepted.text
        rows = accepted.json()["views"]
        assert [r["status"] for r in rows] == ["accepted", "accepted"]
        assert all(r["decided_by"] is not None and r["decided_at"] is not None for r in rows)

        # вид без привязки по отметкам принять нельзя; остальные в запросе не меняются
        refused = await api.post(
            _decide_url(project_id), json={"view_ids": [text_only, fitted], "decision": "accept"}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "VALIDATION_FAILED"
        assert "привязки по отметкам" in refused.text and "text_only" in refused.text

        rejected = await api.post(
            _decide_url(project_id), json={"view_ids": [text_only], "decision": "reject"}
        )
        assert [r["status"] for r in rejected.json()["views"]] == ["rejected"]

        reset = await api.post(
            _decide_url(project_id), json={"view_ids": [fitted, text_only], "decision": "reset"}
        )
        assert [(r["status"], r["decided_by"], r["decided_at"]) for r in reset.json()["views"]] == [
            ("candidate", None, None),
            ("candidate", None, None),
        ]
        after = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        assert [v["status"] for v in after] == ["candidate", "accepted", "candidate"]

        unknown = await api.post(
            _decide_url(project_id), json={"view_ids": [str(uuid.uuid4())], "decision": "accept"}
        )
        assert unknown.status_code == 404
        for body in (
            {"view_ids": [], "decision": "accept"},
            {"view_ids": [fitted], "decision": "maybe"},
            {"view_ids": [fitted], "decision": "accept", "extra": 1},
        ):
            assert (await api.post(_decide_url(project_id), json=body)).status_code == 422, body


async def test_rerun_carries_decisions_over_by_page_title_and_axes(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        first = await _queue(api, project_id, revision_id)
        assert (await _run_worker(db_session, fake_storage, settings, first)).status is (
            JobStatus.SUCCEEDED
        )
        views = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        fitted, weak, text_only = (v["id"] for v in views)
        await api.post(_decide_url(project_id), json={"view_ids": [fitted], "decision": "accept"})
        await api.post(_decide_url(project_id), json={"view_ids": [weak], "decision": "reject"})
        decided = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        author, moment = decided[0]["decided_by"], decided[0]["decided_at"]

        # у второго вида в новом выходе другой заголовок: его решение не переносится
        _set_mode(facades_tools, "renamed")
        second = await _queue(api, project_id, revision_id, [0, 1])
        assert second != first
        assert (await _run_worker(db_session, fake_storage, settings, second)).status is (
            JobStatus.SUCCEEDED
        )
        read = (await api.get(_views_url(project_id, revision_id))).json()
        assert read["result_job_id"] == second
        new = read["views"]
        assert len(new) == 3, "строки прежнего задания заменены"
        assert {v["job_id"] for v in new} == {second}
        assert [v["id"] for v in new] != [fitted, weak, text_only]
        assert [v["status"] for v in new] == ["accepted", "candidate", "candidate"]
        assert (new[0]["decided_by"], new[0]["decided_at"]) == (author, moment)
        assert new[1]["title"] == "Фасад 5-1" and new[1]["decided_by"] is None
        total = await db_session.scalar(select(func.count()).select_from(CadFacadeView))
        assert total == 3


async def test_rerun_does_not_carry_a_decision_to_a_view_with_other_numbers(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        first = await _queue(api, project_id, revision_id)
        assert (await _run_worker(db_session, fake_storage, settings, first)).status is (
            JobStatus.SUCCEEDED
        )
        fitted = (await api.get(_views_url(project_id, revision_id))).json()["views"][0]["id"]
        await api.post(_decide_url(project_id), json={"view_ids": [fitted], "decision": "accept"})

        # то же, что и было: числа те же - решение переносится
        same = await _queue(api, project_id, revision_id, [0, 1])
        await _run_worker(db_session, fake_storage, settings, same)
        views = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        assert [v["status"] for v in views] == ["accepted", "candidate", "candidate"]

        # у окна другой z_bottom_mm - вид снова кандидат
        _set_mode(facades_tools, "shifted")
        third = await _queue(api, project_id, revision_id, [0])
        assert (await _run_worker(db_session, fake_storage, settings, third)).status is (
            JobStatus.SUCCEEDED
        )
        views = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        assert [v["status"] for v in views] == ["candidate", "candidate", "candidate"]
        assert views[0]["decided_by"] is None and views[0]["windows"][0]["z_bottom_mm"] == 7361


def test_fingerprint_changes_with_view_axes_and_window_boxes() -> None:
    """Оси вида и `bbox` окон - входы сопоставления: изменились - решение не переносится."""
    windows = [{"z_bottom_mm": 900, "z_top_mm": 2400, "bbox": [0.5, 0.3, 0.63, 0.4]}]
    axes = [
        {"label": "1", "label_full": None, "x": 0.1},
        {"label": "2", "label_full": None, "x": 0.9},
    ]
    base = cad_facades._fingerprint("fitted", 1.0, 1, windows, [], axes)
    assert base == cad_facades._fingerprint("fitted", 1.0, 1, [dict(windows[0])], [], list(axes))
    moved_axis = [axes[0], {**axes[1], "x": 0.91}]
    assert base != cad_facades._fingerprint("fitted", 1.0, 1, windows, [], moved_axis)
    renamed = [{**axes[0], "label": "A"}, axes[1]]
    assert base != cad_facades._fingerprint("fitted", 1.0, 1, windows, [], renamed)
    moved_box = [{**windows[0], "bbox": [0.5, 0.3, 0.64, 0.4]}]
    assert base != cad_facades._fingerprint("fitted", 1.0, 1, moved_box, [], axes)


async def test_partial_rerun_replaces_only_its_pages_and_keeps_other_decisions(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        first = await _queue(api, project_id, revision_id)
        assert (await _run_worker(db_session, fake_storage, settings, first)).status is (
            JobStatus.SUCCEEDED
        )
        views = (await api.get(_views_url(project_id, revision_id))).json()["views"]
        on_a, _, on_b = (v["id"] for v in views)
        await api.post(_decide_url(project_id), json={"view_ids": [on_a], "decision": "accept"})
        await api.post(_decide_url(project_id), json={"view_ids": [on_b], "decision": "reject"})

        second = await _queue(api, project_id, revision_id, [1])
        assert (await _run_worker(db_session, fake_storage, settings, second)).status is (
            JobStatus.SUCCEEDED
        )
        read = (await api.get(_views_url(project_id, revision_id))).json()
        rows = read["views"]
        assert [(v["page_index"], v["view_key"], v["status"]) for v in rows] == [
            (0, "p0v1", "accepted"),
            (0, "p0v2", "candidate"),
            (1, "p1v1", "rejected"),
        ]
        # страница A - от первого задания (строки на месте), страница B заменена вторым
        assert rows[0]["id"] == on_a and rows[0]["job_id"] == first
        assert rows[2]["id"] != on_b and rows[2]["job_id"] == second
        assert rows[2]["decided_by"] is not None
        assert read["result_job_id"] == second


# ------------------------------------------------------------------ флаг и пространство


async def test_facades_are_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient], facades_tools: Path, tmp_path: Path
) -> None:
    base = f"/api/v1/projects/{uuid.uuid4()}/cad/facades"
    settings = facades_settings(facades_tools, tmp_path, flag=False)
    async with build_api(make_context(), settings=settings) as api:
        posts = (
            (f"{base}/jobs", {"revision_id": str(uuid.uuid4())}),
            (f"{base}/views/decide", {"view_ids": [str(uuid.uuid4())], "decision": "accept"}),
        )
        for path, body in posts:
            response = await api.post(path, json=body)
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", path
        read = await api.get(f"{base}?revision_id={uuid.uuid4()}")
        assert read.status_code == 403 and read.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_foreign_workspace_sees_nothing_of_the_facades(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    facades_tools: Path,
    tmp_path: Path,
) -> None:
    settings = facades_settings(facades_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        job_id = await _queue(api, project_id, revision_id)
        assert (await _run_worker(db_session, fake_storage, settings, job_id)).status is (
            JobStatus.SUCCEEDED
        )
        view_id = (await api.get(_views_url(project_id, revision_id))).json()["views"][0]["id"]
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        base = f"/api/v1/projects/{project_id}/cad/facades"
        assert (await foreign.get(f"{base}?revision_id={revision_id}")).status_code == 404
        scheduled = await foreign.post(f"{base}/jobs", json={"revision_id": revision_id})
        assert scheduled.status_code == 404
        decided = await foreign.post(
            f"{base}/views/decide", json={"view_ids": [view_id], "decision": "accept"}
        )
        assert decided.status_code == 404
