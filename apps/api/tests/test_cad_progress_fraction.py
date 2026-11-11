"""Доля `Job.progress` по снимку runner и монотонность подъёма в исполнителе CAD."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.cad_worker.handler import _raise_progress
from app.domain import JobStatus
from app.models import Job
from app.services import cad_progress


def _view(index: int, statuses: dict[str, str]) -> dict[str, Any]:
    return {
        "index": index,
        "stages": [{"key": key, "status": status} for key, status in statuses.items()],
    }


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("claimed", 0.0),
        ("download", 0.02),
        ("starting", 0.04),
        ("verify", 0.05),
        ("intake", 0.08),
        ("worker", 0.10),
        ("collect", 0.92),
        ("finished", 0.94),
        ("publish", 0.96),
    ],
)
def test_phase_fractions_without_views(phase: str, expected: float) -> None:
    assert cad_progress.progress_fraction({"phase": phase, "views": []}) == pytest.approx(expected)


def test_worker_with_partial_stages_of_two_views() -> None:
    snapshot = {
        "phase": "worker",
        "views": [
            _view(0, {"source": "done", "regions": "needs_review", "scale": "running"}),
            _view(1, {"source": "error", "regions": "queued", "geometry": "unknown"}),
        ],
    }
    # w = (1 + 1 + 0.5 + 1) / (7 * 2) = 3.5 / 14 = 0.25 -> 0.10 + 0.80 * 0.25
    assert cad_progress.progress_fraction(snapshot) == pytest.approx(0.30)


def test_worker_all_stages_done_is_clamped() -> None:
    stages = dict.fromkeys(cad_progress.STAGE_KEYS, "done")
    snapshot = {"phase": "worker", "views": [_view(0, stages)]}
    assert cad_progress.progress_fraction(snapshot) == pytest.approx(0.90)


def test_collect_takes_max_of_phase_and_views() -> None:
    stages = dict.fromkeys(cad_progress.STAGE_KEYS, "done")
    snapshot = {"phase": "collect", "views": [_view(0, stages)]}
    assert cad_progress.progress_fraction(snapshot) == pytest.approx(0.92)
    assert cad_progress.progress_fraction({"phase": "finished", "views": []}) == 0.94


def test_fraction_never_exceeds_cap() -> None:
    assert cad_progress.progress_fraction({"phase": "publish", "views": []}) <= 0.99


@pytest.mark.asyncio
async def test_raise_progress_is_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[float] = []

    async def fake_report(_session: object, *, job: Job, progress: float, stage: None) -> Job:
        written.append(progress)
        job.progress = progress
        return job

    monkeypatch.setattr("app.cad_worker.handler.jobs_service.report_progress", fake_report)
    job = cast(Job, SimpleNamespace(status=JobStatus.RUNNING, progress=0.30))
    session = cast(Any, object())
    await _raise_progress(session, job, 0.10)
    await _raise_progress(session, job, 0.30)
    await _raise_progress(session, job, 0.50)
    assert written == [0.50]
    job.status = JobStatus.SUCCEEDED
    await _raise_progress(session, job, 0.90)
    assert written == [0.50]
