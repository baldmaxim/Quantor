"""Автоход петли ИИ пилота: оформление, правщик, перестроение, проверщик, лимит, перенос."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import ai_review
from app.contracts.cad import CadRemarkWrite
from app.contracts.cad_ai_review import AiLoopPilot
from app.contracts.cad_ai_style import AiStyleResult
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import CadRemark, DocumentRevision, Job
from app.services import ai_loop, cad_convert_hints, cad_walls
from app.storage.base import StorageUnavailableError
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.doc_questions_support import add_pdf, make_project
from tests.test_cad_queue import add_job

DXF = "d" * 64
SIGNATURES_SHA = "5" * 64
DXF_NAME = "views/p001_v01/plan_candidates.dxf"
SIGNATURES_NAME = "views/p001_v01/hatch_signatures.json"
MONOLITH = {
    "signature_id": "ae2b34038041",
    "color": [0.145, 0.0, 0.29],
    "pen_pt": 0.28,
    "angle_deg": 135.0,
    "pitch_pt": 4.5,
}


CHAIN_HINTS = {"schema": "quantor.cad_convert_hints.v1", "page": 1, "hints": []}


def _settings(project_id: uuid.UUID, *, max_iterations: int = 3) -> Settings:
    pilot = AiLoopPilot(
        project_id=project_id, max_iterations=max_iterations, sources={"vor": "/pilot/vor.md"}
    )
    return clean_settings(environment="test", cad_ai_loop=pilot.model_dump_json())


def _no_pilot() -> Settings:
    return clean_settings(environment="test")


class _Ctx:
    def __init__(self, *, workspace_id: uuid.UUID, project_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.revision: DocumentRevision
        self.convert: Job


async def _context(
    session: AsyncSession,
    storage: FakeObjectStorage,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
) -> _Ctx:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as api:
        project_id = await make_project(api)
    ctx = _Ctx(workspace_id=workspace_id, project_id=uuid.UUID(project_id))
    ctx.revision = await add_pdf(session, storage, project_id, "АР План.pdf")
    ctx.convert = await _convert(session, ctx)
    return ctx


async def _convert(
    session: AsyncSession,
    ctx: _Ctx,
    *,
    hints: dict[str, Any] | None = None,
    signatures: bool = True,
    minutes: int = 0,
) -> Job:
    params: dict[str, Any] = {
        "schema": "quantor.cad_engine.params.v2",
        "pages": [0],
        "scales": {"0": {"mm_per_pt": 35.0, "calibration_id": "cal-1"}},
    }
    if hints is not None:
        params["convert_hints"] = hints
    artifacts = [{"name": DXF_NAME, "sha256": DXF, "key": "k"}]
    if signatures:
        artifacts.append({"name": SIGNATURES_NAME, "sha256": SIGNATURES_SHA, "key": "k2"})
    job = add_job(
        session,
        workspace_id=ctx.workspace_id,
        project_id=ctx.project_id,
        status=JobStatus.SUCCEEDED,
        minutes=minutes,
        job_type=JobType.CAD_PDF_CONVERT,
        attempt=1,
        payload={
            "revision_id": str(ctx.revision.id),
            "params": params,
            "params_sha256": "p" * 64,
            "cad_result": {
                "attempt": 1,
                "pages": [{"index": 0, "views": [{"view": 1}]}],
                "artifacts": artifacts,
            },
        },
    )
    await session.commit()
    return job


async def _walls(
    session: AsyncSession, convert: Job, *, status: JobStatus = JobStatus.SUCCEEDED, **marker: Any
) -> Job:
    assert convert.workspace_id is not None
    payload: dict[str, Any] = {
        "revision_id": convert.payload["revision_id"],
        "parent_job_id": str(convert.id),
        "parent_attempt": 1,
        "page_index": 0,
        "view": 1,
        "cad_result": {"attempt": 1, "page_index": 0, "view": 1, "dxf_sha256": DXF},
    }
    if marker:
        payload["ai_loop"] = marker
    job = add_job(
        session,
        workspace_id=convert.workspace_id,
        project_id=convert.project_id,
        status=status,
        minutes=2,
        job_type=JobType.CAD_WALLS,
        payload=payload,
        attempt=1,
    )
    await session.commit()
    return job


def _style_payload(convert: Job, classes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "role": "style",
        "cad_job_id": str(convert.id),
        "cad_attempt": 1,
        "revision_id": convert.payload["revision_id"],
        "page_index": 0,
        "view": 1,
        "ai_style": {
            "cad_job_id": str(convert.id),
            "cad_attempt": 1,
            "revision_id": convert.payload["revision_id"],
            "page_index": 0,
            "view": 1,
            "model": "claude-test",
            "input_sha256": "a" * 64,
            "signatures_sha256": SIGNATURES_SHA,
            "prompt_sha256": "b" * 64,
            "bundle_sha256": "c" * 64,
            "usage": {},
            "sources": {},
            "classes": classes,
            "dropped": [],
            "limitations": [],
        },
    }


def _style_class(class_name: str = "monolith", confidence: str = "high") -> dict[str, Any]:
    return {**MONOLITH, "class_name": class_name, "confidence": confidence, "evidence": "легенда"}


async def _style(
    session: AsyncSession,
    convert: Job,
    classes: list[dict[str, Any]] | None,
    *,
    status: JobStatus = JobStatus.SUCCEEDED,
) -> Job:
    assert convert.workspace_id is not None
    payload = _style_payload(convert, classes or [])
    if status is not JobStatus.SUCCEEDED:
        payload.pop("ai_style")
    job = add_job(
        session,
        workspace_id=convert.workspace_id,
        project_id=convert.project_id,
        status=status,
        minutes=3,
        job_type=JobType.CAD_AI_REVIEW,
        payload=payload,
        attempt=1,
    )
    await session.commit()
    return job


def _report(verdict: str) -> dict[str, Any]:
    findings = (
        []
        if verdict == "ready_for_human_review"
        else [
            {
                "type": "missing_wall",
                "priority": "major",
                "bbox_px": [1.0, 1.0, 5.0, 5.0],
                "construction_ids": [],
                "observation": "нет стены",
                "evidence": "чертёж",
                "suggested_fix": "добавить",
            }
        ]
    )
    return {
        "verdict": verdict,
        "findings": findings,
        "props": [],
        "vor_check": [],
        "limitations": [],
    }


async def _review(
    session: AsyncSession,
    walls: Job,
    verdict: str,
    *,
    role: str = "corrector",
    status: JobStatus = JobStatus.SUCCEEDED,
    minutes: int = 4,
) -> Job:
    assert walls.workspace_id is not None
    payload: dict[str, Any] = {
        "walls_job_id": str(walls.id),
        "walls_attempt": 1,
        "cad_job_id": walls.payload["parent_job_id"],
        "cad_attempt": 1,
        "revision_id": walls.payload["revision_id"],
        "page_index": 0,
        "view": 1,
        "role": role,
        "iteration": 1,
    }
    if status is JobStatus.SUCCEEDED:
        payload["ai_review"] = {
            "walls_job_id": str(walls.id),
            "walls_attempt": 1,
            "cad_job_id": walls.payload["parent_job_id"],
            "revision_id": walls.payload["revision_id"],
            "page_index": 0,
            "view": 1,
            "role": role,
            "iteration": 1,
            "model": "claude-test",
            "input_sha256": "a" * 64,
            "walls_sha256": "b" * 64,
            "dxf_sha256": DXF,
            "prompt_sha256": "c" * 64,
            "bundle_sha256": "e" * 64,
            "sources": {},
            "usage": {},
            "render": {"clip": [0, 0, 10, 10], "zoom": 1.0},
            "remark_keys": [],
            "report": _report(verdict),
        }
    job = add_job(
        session,
        workspace_id=walls.workspace_id,
        project_id=walls.project_id,
        status=status,
        minutes=minutes,
        job_type=JobType.CAD_AI_REVIEW,
        payload=payload,
        attempt=1,
    )
    await session.commit()
    return job


async def _remark(
    session: AsyncSession,
    convert: Job,
    key: str,
    kind: str,
    *,
    status: str = "open",
    user: uuid.UUID = ai_loop.SYSTEM_USER,
) -> None:
    from app.services import cad_remarks

    await cad_remarks.upsert_remark(
        session,
        job=convert,
        attempt=1,
        page_index=0,
        view=1,
        remark_key=key,
        body=CadRemarkWrite.model_validate(
            {
                "type": kind,
                "comment": f"замечание {key}",
                "reviewer": "ИИ правщик · круг 1",
                "status": status,
                "bbox_pt": [10.0, 20.0, 30.0, 40.0],
                "dxf_sha256": DXF,
            }
        ),
        user_id=user,
    )
    await session.commit()


async def _jobs(session: AsyncSession, job_type: JobType) -> list[Job]:
    rows = await session.scalars(
        select(Job).where(Job.job_type == job_type).order_by(Job.created_at, Job.id)
    )
    return list(rows)


async def _reviews(session: AsyncSession, role: str) -> list[Job]:
    return [
        job
        for job in await _jobs(session, JobType.CAD_AI_REVIEW)
        if job.payload.get("role") == role
    ]


# ------------------------------------------------------------------ чистые функции


def _result(classes: list[dict[str, Any]]) -> AiStyleResult:
    convert = uuid.uuid4()
    return AiStyleResult.model_validate(
        {
            "cad_job_id": str(convert),
            "cad_attempt": 1,
            "revision_id": str(uuid.uuid4()),
            "page_index": 0,
            "view": 1,
            "model": "m",
            "input_sha256": "a" * 64,
            "signatures_sha256": "b" * 64,
            "prompt_sha256": "c" * 64,
            "bundle_sha256": "d" * 64,
            "usage": {},
            "sources": {},
            "classes": classes,
            "dropped": [],
            "limitations": [],
        }
    )


def test_merge_classes_drops_low_confidence_and_disputed_signatures() -> None:
    same = _result([_style_class("monolith")])
    low = _result([{**_style_class("masonry", "low"), "pen_pt": 0.5, "signature_id": "low"}])
    clashing = _result([_style_class("masonry")])
    other = _result([{**_style_class("ignore", "medium"), "pen_pt": 0.9, "signature_id": "x"}])
    assert [c.class_ for c in ai_loop.merge_classes([same, low])] == ["monolith"]
    merged = ai_loop.merge_classes([same, other])
    assert [(c.signature_id, c.class_) for c in merged] == [
        ("ae2b34038041", "monolith"),
        ("x", "ignore"),
    ]
    # Те же числа и разный класс у видов страницы: спорная подпись не передаётся движку.
    assert [c.signature_id for c in ai_loop.merge_classes([same, clashing, other])] == ["x"]


def test_pilot_for_project() -> None:
    project = uuid.uuid4()
    assert ai_loop.pilot_for_project(project, _settings(project)) is not None
    assert ai_loop.pilot_for_project(uuid.uuid4(), _settings(project)) is None
    assert ai_loop.pilot_for_project(project, _no_pilot()) is None
    assert ai_loop.pilot_for_project(None, _settings(project)) is None


# ------------------------------------------------------------------ после преобразования


async def test_first_convert_enqueues_style_once_per_view(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    await ai_loop.after_convert(db_session, ctx.convert, settings)
    await ai_loop.after_convert(db_session, ctx.convert, settings)
    await db_session.commit()
    [style] = await _reviews(db_session, "style")
    assert style.payload["cad_job_id"] == str(ctx.convert.id)
    assert (style.payload["page_index"], style.payload["view"]) == (0, 1)
    assert (
        style.payload["sources"] == {"vor": "/pilot/vor.md"} and "walls_job_id" not in style.payload
    )


async def test_convert_outside_pilot_or_without_signatures_or_with_hints_does_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    await ai_loop.after_convert(db_session, ctx.convert, _no_pilot())
    await ai_loop.after_convert(db_session, ctx.convert, _settings(uuid.uuid4()))
    bare = await _convert(db_session, ctx, signatures=False, minutes=1)
    await ai_loop.after_convert(db_session, bare, _settings(ctx.project_id))
    hinted = await _convert(
        db_session,
        ctx,
        hints={"schema": "quantor.cad_convert_hints.v1", "page": 1, "hints": []},
        minutes=2,
    )
    await ai_loop.after_convert(db_session, hinted, _settings(ctx.project_id))
    await db_session.commit()
    assert await _reviews(db_session, "style") == []


async def test_new_convert_carries_open_ai_remarks_only(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    old = ctx.convert
    await _remark(db_session, old, "ai-open", "false_wall")
    await _remark(db_session, old, "ai-wall", "missing_wall")
    await _remark(db_session, old, "ai-done", "missing_door", status="resolved")
    await _remark(db_session, old, "human", "missing_wall", user=uuid.uuid4())
    new = await _convert(db_session, ctx, minutes=5)
    new.payload = {
        **new.payload,
        "ai_loop": {"carry_from": {"job_id": str(old.id), "attempt": 1}},
    }
    await db_session.commit()
    await ai_loop.after_convert(db_session, new, _settings(ctx.project_id))
    await db_session.commit()
    rows = list(await db_session.scalars(select(CadRemark).where(CadRemark.job_id == new.id)))
    assert sorted(row.type for row in rows) == ["false_wall", "missing_wall"]
    assert all(row.remark_key.startswith("carry-") and row.status == "open" for row in rows)
    assert all(row.dxf_sha256 == DXF and row.created_by == ai_loop.SYSTEM_USER for row in rows)
    # Повтор не плодит копий: ключи детерминированы.
    await ai_loop.after_convert(db_session, new, _settings(ctx.project_id))
    await db_session.commit()
    count = len(list(await db_session.scalars(select(CadRemark).where(CadRemark.job_id == new.id))))
    assert count == 2


# ------------------------------------------------------------------ после оформления


async def test_style_with_classes_enqueues_reconvert_with_numbers_from_the_package(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    style = await _style(
        db_session, ctx.convert, [_style_class("masonry"), _style_class("monolith", "low")]
    )
    await ai_loop.after_style(db_session, style, settings)
    await db_session.commit()
    converts = [
        job for job in await _jobs(db_session, JobType.CAD_PDF_CONVERT) if job.id != ctx.convert.id
    ]
    [new] = converts
    hints = new.payload["params"]["convert_hints"]
    assert hints["hints"] == [] and hints["page"] == 1
    assert hints["hatch_classes"] == [{**MONOLITH, "class": "masonry"}]
    assert new.payload["ai_loop"]["reason"] == "style"
    assert new.payload["params"]["scales"] == ctx.convert.payload["params"]["scales"]
    # Повтор того же хода не ставит второе преобразование.
    await ai_loop.after_style(db_session, style, settings)
    await db_session.commit()
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 2


async def test_style_without_classes_starts_the_corrector_on_existing_walls(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    walls = await _walls(db_session, ctx.convert)
    style = await _style(db_session, ctx.convert, [])
    await ai_loop.after_style(db_session, style, _settings(ctx.project_id))
    await db_session.commit()
    [corrector] = await _reviews(db_session, "corrector")
    assert corrector.payload["walls_job_id"] == str(walls.id)
    assert corrector.payload["iteration"] == 1
    assert await _jobs(db_session, JobType.CAD_PDF_CONVERT) == [ctx.convert]


async def test_style_waits_for_other_views_and_stands_on_failure(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    await _walls(db_session, ctx.convert)
    settings = _settings(ctx.project_id)
    done = await _style(db_session, ctx.convert, [_style_class()])
    other = await _style(db_session, ctx.convert, None, status=JobStatus.RUNNING)
    await ai_loop.after_style(db_session, done, settings)
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 1
    other.status = JobStatus.FAILED
    await db_session.commit()
    await ai_loop.after_style(db_session, done, settings)
    await db_session.commit()
    # Упавшая роль не повторяется и цепочку не двигает.
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 1
    assert await _reviews(db_session, "corrector") == []


# ------------------------------------------------------------------ после конструкций


async def test_walls_waits_for_style_and_reconvert_then_starts_corrector(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    walls = await _walls(db_session, ctx.convert)
    running = await _style(db_session, ctx.convert, None, status=JobStatus.RUNNING)
    await ai_loop.after_walls(db_session, walls, settings)
    assert await _reviews(db_session, "corrector") == []  # оформление идёт: ход за его хуком
    running.status = JobStatus.FAILED
    await db_session.commit()
    await ai_loop.after_walls(db_session, walls, settings)
    assert await _reviews(db_session, "corrector") == []  # оформление упало: цепочка стоит
    running.status = JobStatus.SUCCEEDED
    running.payload = {**running.payload, **_style_payload(ctx.convert, [_style_class()])}
    await db_session.commit()
    await ai_loop.after_style(db_session, running, settings)  # ставит преобразование с классами
    await ai_loop.after_walls(db_session, walls, settings)
    assert await _reviews(db_session, "corrector") == []  # идёт перестроение с классами
    running.payload = {**running.payload, **_style_payload(ctx.convert, [])}
    await db_session.commit()
    await ai_loop.after_walls(db_session, walls, settings)
    await db_session.commit()
    assert len(await _reviews(db_session, "corrector")) == 1


async def test_walls_of_style_converted_sheet_and_plain_sheet_start_corrector_once(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    classes = {**MONOLITH, "class": "monolith"}
    styled = await _convert(
        db_session,
        ctx,
        hints={
            "schema": "quantor.cad_convert_hints.v1",
            "page": 1,
            "hints": [],
            "hatch_classes": [classes],
        },
        minutes=1,
    )
    first = await _walls(db_session, styled)
    await ai_loop.after_walls(db_session, first, settings)
    await db_session.commit()
    assert len(await _reviews(db_session, "corrector")) == 1
    # Пересчёт конструкций после авто-зон того же преобразования второго правщика не порождает.
    again = await _walls(db_session, styled)
    await ai_loop.after_walls(db_session, again, settings)
    await ai_loop.after_walls(db_session, first, settings)
    await db_session.commit()
    assert len(await _reviews(db_session, "corrector")) == 1


async def test_walls_outside_pilot_do_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    walls = await _walls(db_session, ctx.convert)
    await ai_loop.after_walls(db_session, walls, _no_pilot())
    await ai_loop.after_walls(db_session, walls, _settings(uuid.uuid4()))
    await db_session.commit()
    assert await _reviews(db_session, "corrector") == []


# ------------------------------------------------------------------ после правщика


async def test_ready_corrector_starts_the_verifier_once(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    walls = await _walls(db_session, ctx.convert)
    review = await _review(db_session, walls, "ready_for_human_review")
    settings = _settings(ctx.project_id)
    await ai_loop.after_review(db_session, fake_storage, review, settings)
    await ai_loop.after_review(db_session, fake_storage, review, settings)
    await db_session.commit()
    [verifier] = await _reviews(db_session, "verifier")
    assert verifier.payload["walls_job_id"] == str(walls.id)


async def test_verifier_and_insufficient_evidence_do_not_continue_the_chain(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    walls = await _walls(db_session, ctx.convert)
    settings = _settings(ctx.project_id)
    verifier = await _review(db_session, walls, "needs_correction", role="verifier")
    await ai_loop.after_review(db_session, fake_storage, verifier, settings)
    insufficient = await _review(db_session, walls, "insufficient_evidence", minutes=5)
    await ai_loop.after_review(db_session, fake_storage, insufficient, settings)
    await ai_loop.after_review(db_session, fake_storage, insufficient, _no_pilot())
    await db_session.commit()
    assert len(await _jobs(db_session, JobType.CAD_AI_REVIEW)) == 2
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 1


async def test_needs_correction_with_missing_walls_reconverts_with_hints_classes_and_carry(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    classes = {**MONOLITH, "class": "masonry"}
    styled = await _convert(
        db_session,
        ctx,
        hints={
            "schema": "quantor.cad_convert_hints.v1",
            "page": 1,
            "hints": [],
            "hatch_classes": [classes],
        },
        minutes=1,
    )
    walls = await _walls(db_session, styled)
    await _remark(db_session, styled, "ai-1", "missing_wall")
    await _remark(db_session, styled, "ai-2", "false_wall")
    review = await _review(db_session, walls, "needs_correction")
    await ai_loop.after_review(db_session, fake_storage, review, _settings(ctx.project_id))
    await db_session.commit()
    new = [
        job
        for job in await _jobs(db_session, JobType.CAD_PDF_CONVERT)
        if job.id not in (ctx.convert.id, styled.id)
    ]
    assert len(new) == 1
    hints = new[0].payload["params"]["convert_hints"]
    assert [item["id"] for item in hints["hints"]] == ["ai-1"]
    assert hints["hatch_classes"] == [classes]
    assert new[0].payload["ai_loop"]["carry_from"] == {"job_id": str(styled.id), "attempt": 1}
    assert await _reviews(db_session, "verifier") == []


async def test_same_hints_fall_back_to_false_wall_rebuild_then_verifier(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    await _remark(db_session, ctx.convert, "ai-1", "missing_wall")
    await _remark(db_session, ctx.convert, "ai-2", "false_wall")
    walls = await _walls(db_session, ctx.convert)
    first = await _review(db_session, walls, "needs_correction")
    await ai_loop.after_review(db_session, fake_storage, first, settings)
    await db_session.commit()
    # Повторный круг с теми же подсказками: преобразование уже есть - перестроение по false_wall.
    rebuilt = Job(
        id=uuid.uuid4(),
        project_id=ctx.project_id,
        workspace_id=ctx.workspace_id,
        job_type=JobType.CAD_WALLS,
        payload={},
    )
    rebuild = AsyncMock(return_value=rebuilt)
    monkeypatch.setattr(cad_walls, "schedule_rebuild_by_remarks", rebuild)
    second = await _review(db_session, walls, "needs_correction", minutes=5)
    await ai_loop.after_review(db_session, fake_storage, second, settings)
    rebuild.assert_awaited_once()
    assert rebuilt.payload["ai_loop"]["rebuild_of"] == str(second.id)
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 2
    # Перестроение отказало (занято): итог за проверщиком.
    rebuild.side_effect = DomainError(ErrorCode.CAD_WALLS_BUSY)
    third = await _review(db_session, walls, "needs_correction", minutes=6)
    await ai_loop.after_review(
        db_session, fake_storage, third, _settings(ctx.project_id, max_iterations=5)
    )
    await db_session.commit()
    assert len(await _reviews(db_session, "verifier")) == 1


async def test_needs_correction_without_hintable_remarks_goes_to_verifier(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    await _remark(db_session, ctx.convert, "ai-1", "wrong_class")
    walls = await _walls(db_session, ctx.convert)
    review = await _review(db_session, walls, "needs_correction")
    await ai_loop.after_review(db_session, fake_storage, review, _settings(ctx.project_id))
    await db_session.commit()
    assert len(await _reviews(db_session, "verifier")) == 1
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 1


async def _chain(db_session: AsyncSession, ctx: _Ctx, rounds: int) -> tuple[Job, Job, Job]:
    """Цепочка из `rounds` преобразований с успешным правщиком у каждого; последний - вид."""
    convert, walls, review = ctx.convert, await _walls(db_session, ctx.convert), None
    review = await _review(db_session, walls, "needs_correction", minutes=4)
    for number in range(1, rounds):
        convert = await _convert(db_session, ctx, hints=CHAIN_HINTS, minutes=5 * number)
        walls = await _walls(db_session, convert)
        review = await _review(db_session, walls, "needs_correction", minutes=5 * number + 3)
    return convert, walls, review


async def test_rounds_are_counted_over_the_whole_convert_chain(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    """Два правщика на прежних преобразованиях: у нового преобразования - третий круг."""
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id, max_iterations=3)
    await _chain(db_session, ctx, 2)
    last_convert = await _convert(db_session, ctx, hints=CHAIN_HINTS, minutes=40)
    last = await _walls(db_session, last_convert)
    await ai_loop.after_walls(db_session, last, settings)
    await db_session.commit()
    correctors = await _reviews(db_session, "corrector")
    assert len(correctors) == 3
    assert max(job.payload["iteration"] for job in correctors) == 3


async def test_rounds_start_over_from_the_new_root_without_hints(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    """Старый корень и два его правщика: у нового корня без подсказок круги считаются с первого."""
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id, max_iterations=3)
    await _chain(db_session, ctx, 2)
    new_root = await _convert(db_session, ctx, minutes=40)
    walls = await _walls(db_session, new_root)
    await ai_loop.after_walls(db_session, walls, settings)
    await db_session.commit()
    correctors = await _reviews(db_session, "corrector")
    assert len(correctors) == 3
    fresh = [job for job in correctors if job.payload["walls_job_id"] == str(walls.id)]
    assert [job.payload["iteration"] for job in fresh] == [1]
    assert await _reviews(db_session, "verifier") == []


async def test_exhausted_rounds_go_to_the_verifier_instead_of_a_new_rebuild(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id, max_iterations=3)
    convert, _, third = await _chain(db_session, ctx, 3)
    await _remark(db_session, convert, "ai-1", "missing_wall")
    await ai_loop.after_review(db_session, fake_storage, third, settings)
    await db_session.commit()
    assert len(await _reviews(db_session, "verifier")) == 1
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 3
    # Новые конструкции при исчерпанных кругах: правщик не ставится.
    extra = await _walls(db_session, await _convert(db_session, ctx, hints=CHAIN_HINTS, minutes=60))
    await ai_loop.after_walls(db_session, extra, settings)
    await db_session.commit()
    assert len(await _reviews(db_session, "corrector")) == 3


async def test_loop_survives_enqueue_failure(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    walls = await _walls(db_session, ctx.convert)
    review = await _review(db_session, walls, "ready_for_human_review")
    monkeypatch.setattr(
        ai_review,
        "enqueue_for_walls",
        AsyncMock(side_effect=DomainError(ErrorCode.CAD_RESULT_NOT_READY)),
    )
    await ai_loop.after_review(db_session, fake_storage, review, _settings(ctx.project_id))
    await ai_loop.after_walls(db_session, walls, _settings(ctx.project_id))
    await db_session.commit()
    assert await _reviews(db_session, "verifier") == []
    assert len(await _reviews(db_session, "corrector")) == 1


async def test_hooks_do_not_raise_on_foreign_errors(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    walls = await _walls(db_session, ctx.convert)
    style = await _style(db_session, ctx.convert, [_style_class()])
    review = await _review(db_session, walls, "ready_for_human_review")
    monkeypatch.setattr(
        cad_walls, "_not_plan_pages", AsyncMock(side_effect=HTTPException(status_code=409))
    )
    monkeypatch.setattr(ai_loop, "_style_jobs", AsyncMock(side_effect=KeyError("view")))
    monkeypatch.setattr(ai_loop, "_walls_context", AsyncMock(side_effect=HTTPException(400)))
    monkeypatch.setattr(
        ai_loop, "_after_corrector", AsyncMock(side_effect=StorageUnavailableError("down"))
    )
    await ai_loop.after_convert(db_session, ctx.convert, settings)
    await ai_loop.after_style(db_session, style, settings)
    await ai_loop.after_walls(db_session, walls, settings)
    await ai_loop.after_review(db_session, fake_storage, review, settings)
    await db_session.commit()
    assert await _reviews(db_session, "verifier") == []
    assert len(await _jobs(db_session, JobType.CAD_PDF_CONVERT)) == 1


async def test_reconvert_enqueue_failure_starts_corrector_and_walls_do_not_wait(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    settings = _settings(ctx.project_id)
    walls = await _walls(db_session, ctx.convert)
    style = await _style(db_session, ctx.convert, [_style_class()])
    monkeypatch.setattr(
        cad_convert_hints,
        "enqueue_reconvert",
        AsyncMock(side_effect=DomainError(ErrorCode.CAD_INPUT_INVALID)),
    )
    await ai_loop.after_style(db_session, style, settings)
    await db_session.commit()
    [corrector] = await _reviews(db_session, "corrector")
    assert corrector.payload["walls_job_id"] == str(walls.id)
    assert await _jobs(db_session, JobType.CAD_PDF_CONVERT) == [ctx.convert]


async def test_walls_do_not_wait_for_nonexistent_classes_reconvert(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    walls = await _walls(db_session, ctx.convert)
    await _style(db_session, ctx.convert, [_style_class()])  # классы есть, преобразования нет
    await ai_loop.after_walls(db_session, walls, _settings(ctx.project_id))
    await db_session.commit()
    assert len(await _reviews(db_session, "corrector")) == 1
