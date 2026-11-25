"""ИИ-проверка вида: пилот, отчёт, рамки в pt, круги, замечания и разбор ответа CLI."""

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.cad_worker import ai_review
from app.cad_worker.ai_review import (
    bbox_px_to_pt,
    build_remarks,
    enqueue_for_walls,
    execute_ai_review,
    pilot_for,
    review_available,
)
from app.contracts.cad import MAX_COMMENT_LENGTH
from app.contracts.cad_ai_review import AiLoopPilot, AiRender, AiReviewReport
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError
from app.models import Job
from app.services import jobs

DXF = "d" * 64
PROMPT_ID = uuid.uuid4()


def _pilot(**fields: Any) -> AiLoopPilot:
    return AiLoopPilot(
        project_id=fields.pop("project_id", uuid.uuid4()),
        sources={"vor": "/pilot/vor.md", "project": "/pilot/project.md"},
        **fields,
    )


def _settings(pilot: AiLoopPilot) -> Settings:
    return Settings(
        cad_ai_loop=pilot.model_dump_json(),
        cad_review_ssh_config="/ssh/config",
        cad_engine_python="/engine/python",
    )


def _walls(pilot: AiLoopPilot, *, foreign: bool = False) -> Job:
    return Job(
        id=uuid.uuid4(),
        project_id=uuid.uuid4() if foreign else pilot.project_id,
        workspace_id=uuid.uuid4(),
        attempt=1,
        status=JobStatus.SUCCEEDED,
        job_type=JobType.CAD_WALLS,
        payload={
            "revision_id": str(uuid.uuid4()),
            "parent_job_id": str(uuid.uuid4()),
            "parent_attempt": 2,
            "cad_result": {"attempt": 1, "page_index": 81, "view": 1, "dxf_sha256": DXF},
        },
    )


def _review(status: JobStatus, role: str = "corrector") -> Job:
    return Job(
        id=uuid.uuid4(), status=status, job_type=JobType.CAD_AI_REVIEW, payload={"role": role}
    )


def _stub_reviews(monkeypatch: pytest.MonkeyPatch, rows: list[Job]) -> AsyncMock:
    monkeypatch.setattr(ai_review, "reviews_of", AsyncMock(return_value=rows))
    queue = AsyncMock(return_value=Job(id=uuid.uuid4()))
    monkeypatch.setattr(jobs, "enqueue", queue)
    return queue


def _finding(**fields: Any) -> dict[str, Any]:
    return {
        "type": "missing_wall",
        "priority": "major",
        "bbox_px": [100.0, 200.0, 300.0, 400.0],
        "construction_ids": ["c1"],
        "observation": "Нет контура",
        "evidence": "Лист 32",
        "suggested_fix": "Достроить",
        **fields,
    }


def _report(**fields: Any) -> dict[str, Any]:
    return {
        "verdict": "needs_correction",
        "findings": [_finding()],
        "props": [],
        "vor_check": [],
        "limitations": [],
        **fields,
    }


# ------------------------------------------------------------------ контракты


def test_pilot_validation() -> None:
    assert _pilot().model == "claude-opus-5-5"
    pid = uuid.uuid4()
    for bad in (
        {"sources": {}},
        {"sources": {"Vor": "/a.md"}},
        {"sources": {"vor": "relative.md"}},
        {"sources": {"vor": "/a.txt"}},
        {"sources": {f"s_{chr(97 + i)}x": "/a.md" for i in range(9)}},
        {"sources": {"vor": "/a.md"}, "max_iterations": 6},
        {"sources": {"vor": "/a.md"}, "model": "Bad Model"},
        {"sources": {"vor": "/a.md"}, "extra": 1},
    ):
        with pytest.raises(ValidationError):
            AiLoopPilot.model_validate({"project_id": pid, **bad})


def test_report_verdict_rules() -> None:
    AiReviewReport.model_validate(_report())
    with pytest.raises(ValidationError, match="находки или правки"):
        AiReviewReport.model_validate(_report(findings=[]))
    AiReviewReport.model_validate(
        _report(
            findings=[], props=[{"construction_id": "c1", "count_openings": False, "evidence": "x"}]
        )
    )
    with pytest.raises(ValidationError, match="Существенные"):
        AiReviewReport.model_validate(_report(verdict="ready_for_human_review"))
    AiReviewReport.model_validate(
        _report(verdict="ready_for_human_review", findings=[_finding(priority="minor")])
    )


@pytest.mark.parametrize(
    "bbox", [[1, 2, 3], [5, 5, 5, 9], [-1, 0, 5, 5], [0, 0, 5, 0], [0, 0, float("inf"), 5]]
)
def test_finding_bbox_must_be_a_positive_rectangle(bbox: list[float]) -> None:
    with pytest.raises(ValidationError):
        AiReviewReport.model_validate(_report(findings=[_finding(bbox_px=bbox)]))


def test_prop_needs_a_change() -> None:
    with pytest.raises(ValidationError, match="хотя бы одно"):
        AiReviewReport.model_validate(_report(props=[{"construction_id": "c1", "evidence": "x"}]))
    with pytest.raises(ValidationError):
        AiReviewReport.model_validate(
            _report(props=[{"construction_id": "c1", "thickness_mm": 0, "evidence": "x"}])
        )


# ------------------------------------------------------------------ рамка


def test_bbox_px_to_pt_scales_pads_and_clamps() -> None:
    clip = [100.0, 50.0, 300.0, 250.0]
    assert bbox_px_to_pt([20, 40, 60, 80], clip, 2.0) == (
        100.0 + 10.0 - 6.0,
        50.0 + 20.0 - 6.0,
        100.0 + 30.0 + 6.0,
        50.0 + 40.0 + 6.0,
    )
    # Рамка у края растра ограничивается clip.
    assert bbox_px_to_pt([0, 0, 400, 400], clip, 2.0) == (100.0, 50.0, 300.0, 250.0)
    # Рамка целиком за краем остаётся видимой и внутри clip.
    x0, y0, x1, y1 = bbox_px_to_pt([900, 900, 950, 950], clip, 2.0)
    assert 100.0 <= x0 < x1 <= 300.0 and 50.0 <= y0 < y1 <= 250.0


# ------------------------------------------------------------------ доступность и круги


def test_pilot_for_other_project_is_none() -> None:
    pilot = _pilot()
    assert pilot_for(_walls(pilot), _settings(pilot)) is not None
    assert pilot_for(_walls(pilot, foreign=True), _settings(pilot)) is None
    assert pilot_for(_walls(pilot), Settings()) is None
    assert pilot_for(_walls(pilot), Settings(cad_ai_loop="{bad")) is None
    assert review_available(_walls(pilot), _settings(pilot))
    assert not review_available(_walls(pilot, foreign=True), _settings(pilot))


async def test_enqueue_creates_job_with_view_and_cad_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pilot = _pilot()
    walls = _walls(pilot)
    queue = _stub_reviews(monkeypatch, [])
    await enqueue_for_walls(AsyncMock(), walls, _settings(pilot), "verifier")
    request = queue.call_args.kwargs
    assert request["job_type"] == JobType.CAD_AI_REVIEW
    assert request["workspace_id"] == walls.workspace_id
    payload = request["payload"]
    assert payload["cad_job_id"] == walls.payload["parent_job_id"]
    assert (payload["page_index"], payload["pdf_page"], payload["view"]) == (81, 82, 1)
    assert (payload["role"], payload["iteration"], payload["cad_attempt"]) == ("verifier", 1, 2)
    assert request["idempotency_key"].startswith("cad-ai-review:v1:")
    assert request["idempotency_key"].endswith(":1")


async def test_enqueue_unavailable_for_foreign_project(monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = _pilot()
    queue = _stub_reviews(monkeypatch, [])
    with pytest.raises(DomainError):
        await enqueue_for_walls(
            AsyncMock(), _walls(pilot, foreign=True), _settings(pilot), "corrector"
        )
    queue.assert_not_awaited()


async def test_running_review_is_not_duplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = _pilot()
    running = _review(JobStatus.RUNNING)
    queue = _stub_reviews(monkeypatch, [running, _review(JobStatus.FAILED)])
    result = await enqueue_for_walls(AsyncMock(), _walls(pilot), _settings(pilot), "corrector")
    assert result is running
    queue.assert_not_awaited()


async def test_iteration_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = _pilot(max_iterations=2)
    done = [_review(JobStatus.SUCCEEDED), _review(JobStatus.FAILED)]
    queue = _stub_reviews(monkeypatch, done[:1])
    await enqueue_for_walls(AsyncMock(), _walls(pilot), _settings(pilot), "corrector")
    assert queue.call_args.kwargs["idempotency_key"].endswith(":2")
    queue = _stub_reviews(monkeypatch, done)
    with pytest.raises(DomainError, match="лимит кругов"):
        await enqueue_for_walls(AsyncMock(), _walls(pilot), _settings(pilot), "corrector")
    queue.assert_not_awaited()
    # У проверщика свой лимит: исчерпанные круги правщика верификацию не закрывают.
    queue = _stub_reviews(monkeypatch, done)
    await enqueue_for_walls(AsyncMock(), _walls(pilot), _settings(pilot), "verifier")
    assert queue.call_args.kwargs["idempotency_key"].endswith(":1")


# ------------------------------------------------------------------ замечания


def test_remarks_have_deterministic_keys_and_bound_comment() -> None:
    job_id = uuid.uuid4()
    report = AiReviewReport.model_validate(
        _report(findings=[_finding(), _finding(observation="я" * 1000, evidence="э" * 1000)])
    )
    render = AiRender(clip=[10.0, 20.0, 310.0, 320.0], zoom=2.0)

    def build() -> list[tuple[str, Any]]:
        return build_remarks(
            job_id=job_id,
            role="corrector",
            iteration=2,
            report=report,
            render=render,
            dxf_sha256=DXF,
        )

    rows = build()
    assert [key for key, _ in rows] == [key for key, _ in build()]
    assert len({key for key, _ in rows}) == 2 and all(len(k) == 23 for k, _ in rows)
    other = build_remarks(
        job_id=uuid.uuid4(),
        role="corrector",
        iteration=2,
        report=report,
        render=render,
        dxf_sha256=DXF,
    )
    assert {k for k, _ in other}.isdisjoint({k for k, _ in rows})
    _, body = rows[0]
    assert body.reviewer == "ИИ правщик · круг 2" and body.status == "open"
    assert body.type == "missing_wall" and body.dxf_sha256 == DXF
    assert body.comment.startswith("[major] Нет контура — Доказательство: Лист 32")
    assert body.bbox_pt == (
        10.0 + 50.0 - 6.0,
        20.0 + 100.0 - 6.0,
        10.0 + 150.0 + 6.0,
        20.0 + 200.0 + 6.0,
    )
    assert len(rows[1][1].comment) <= MAX_COMMENT_LENGTH


# ------------------------------------------------------------------ разбор ответа CLI


def _response(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": {"vor": {"filename": "vor.md", "sha256": "a" * 64}},
        "report": report,
        "usage": {"cost_usd": 0.5, "duration_ms": 1000, "input_tokens": 10, "output_tokens": 5},
        "model": "claude-opus-5-5",
        "prompt_sha256": "b" * 64,
        "bundle_sha256": "c" * 64,
    }


async def _run_execute(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any], exit_code: int = 0
) -> tuple[Job, AsyncMock, AsyncMock, AsyncMock]:
    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.RUNNING,
        job_type=JobType.CAD_AI_REVIEW,
        worker_id="w",
        attempt=1,
        payload={},
    )
    manifest = {
        "walls_job_id": str(uuid.uuid4()),
        "walls_attempt": 1,
        "cad_job_id": str(uuid.uuid4()),
        "revision_id": str(uuid.uuid4()),
        "page_index": 81,
        "view": 1,
        "role": "verifier",
        "iteration": 1,
        "model": "claude-opus-5-5",
        "input_sha256": "e" * 64,
        "walls_sha256": "f" * 64,
        "dxf_sha256": DXF,
        "sources": {"vor": "/pilot/vor.md"},
        "prompt_version_id": str(PROMPT_ID),
        "prompt_version": 3,
    }

    async def prepare(*args: Any) -> dict[str, Any]:
        return manifest

    async def run(session: Any, job_: Job, owner: Any, attempt: Any, command: list[str], **kw: Any):
        root = Path(command[3])
        (root / "review.json").write_text(json.dumps(response), encoding="utf-8")
        (root / "render.json").write_text(
            json.dumps({"clip": [0.0, 0.0, 100.0, 100.0], "zoom": 2.0}), encoding="utf-8"
        )
        return exit_code, ""

    monkeypatch.setattr(ai_review, "_prepare", prepare)
    monkeypatch.setattr(ai_review, "_run_while_owned", run)
    monkeypatch.setattr(ai_review, "_still_owned", AsyncMock(return_value=True))
    write = AsyncMock()
    monkeypatch.setattr(ai_review, "_write_remarks", write)
    start = AsyncMock()
    monkeypatch.setattr(jobs, "start", start)
    succeed = AsyncMock(side_effect=lambda session, job, payload: job)
    monkeypatch.setattr(jobs, "succeed", succeed)
    fail = AsyncMock(side_effect=lambda session, job, **kw: job)
    monkeypatch.setattr(jobs, "fail", fail)
    settings = Settings(cad_review_ssh_config="/ssh/config", cad_engine_python="/engine/python")
    await execute_ai_review(AsyncMock(), job, AsyncMock(), settings)
    return job, write, succeed, fail


async def test_execute_stores_report_and_writes_remarks(monkeypatch: pytest.MonkeyPatch) -> None:
    _, write, succeed, fail = await _run_execute(monkeypatch, _response(_report()))
    fail.assert_not_awaited()
    stored = succeed.call_args.kwargs["payload"]["ai_review"]
    assert stored["report"]["verdict"] == "needs_correction"
    assert stored["usage"]["cost_usd"] == 0.5 and stored["role"] == "verifier"
    assert len(stored["remark_keys"]) == 1 and stored["prompt_sha256"] == "b" * 64
    assert stored["prompt_version_id"] == str(PROMPT_ID) and stored["prompt_version"] == 3
    rows = write.call_args.args[2]
    assert [key for key, _ in rows] == stored["remark_keys"]
    assert rows[0][1].bbox_pt == (44.0, 94.0, 100.0, 100.0)


@pytest.mark.parametrize(
    "response",
    [
        _response(_report(verdict="needs_correction", findings=[])),
        {**_response(_report()), "sources": {}},
        {k: v for k, v in _response(_report()).items() if k != "report"},
    ],
)
async def test_execute_rejects_bad_response(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    _, write, succeed, fail = await _run_execute(monkeypatch, response)
    succeed.assert_not_awaited()
    write.assert_not_awaited()
    fail.assert_awaited_once()


@pytest.mark.parametrize("code", [124, 255, 3])
async def test_execute_maps_exit_codes_to_failure(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    _, write, succeed, fail = await _run_execute(monkeypatch, _response(_report()), code)
    succeed.assert_not_awaited()
    write.assert_not_awaited()
    assert fail.call_args.kwargs["error_code"]
