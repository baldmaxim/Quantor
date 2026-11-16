"""Пилот отправляет на внешнюю проверку только согласованные проект, ревизию и вид."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.cad_worker import outline_review
from app.cad_worker.outline_review import enqueue_for_walls, pilot_floor_for, review_available
from app.contracts.cad_outline_review import SOURCE_ROLES, OutlinePilot, OutlineReport, PilotFloor
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError
from app.models import Job
from app.services import jobs


def _pilot() -> OutlinePilot:
    return OutlinePilot(
        project_id=uuid4(),
        revision_id=uuid4(),
        section=3,
        floors=[
            PilotFloor(floor=14, pdf_page=81, view=1),
            PilotFloor(floor=15, pdf_page=82, view=1),
        ],
        sources={role: f"/pilot/{role}.md" for role in SOURCE_ROLES},
    )


def _settings(pilot: OutlinePilot) -> Settings:
    return Settings(
        cad_review_pilot=pilot.model_dump_json(),
        cad_review_ssh_config="/ssh/config",
        cad_engine_python="/engine/python",
    )


def _walls(pilot: OutlinePilot, scope: str = "matched") -> Job:
    return Job(
        id=uuid4(),
        project_id=uuid4() if scope == "foreign_project" else pilot.project_id,
        workspace_id=uuid4(),
        attempt=1,
        status=JobStatus.SUCCEEDED,
        job_type=JobType.CAD_WALLS,
        payload={
            "revision_id": str(uuid4() if scope == "foreign_revision" else pilot.revision_id),
            "cad_result": {
                "attempt": 1,
                "page_index": 80,
                "view": 2 if scope == "other_view" else 1,
            },
        },
    )


def _review(status: JobStatus) -> Job:
    return Job(id=uuid4(), status=status, job_type=JobType.CAD_OUTLINE_REVIEW, payload={})


def _stub_reviews(monkeypatch: pytest.MonkeyPatch, rows: list[Job]) -> AsyncMock:
    monkeypatch.setattr(outline_review, "reviews_of", AsyncMock(return_value=rows))
    queue = AsyncMock(return_value=Job(id=uuid4()))
    monkeypatch.setattr(jobs, "enqueue", queue)
    return queue


@pytest.mark.parametrize("scope", ["matched", "foreign_project", "foreign_revision", "other_view"])
async def test_review_is_limited_to_pilot(scope: str, monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = _pilot()
    walls = _walls(pilot, scope)
    settings = _settings(pilot)
    queue = _stub_reviews(monkeypatch, [])
    matched = pilot_floor_for(walls, settings)
    assert review_available(walls, settings) is (scope == "matched")
    if scope != "matched":
        assert matched is None
        with pytest.raises(DomainError):
            await enqueue_for_walls(AsyncMock(), walls, settings)
        queue.assert_not_awaited()
        return
    assert matched is not None
    await enqueue_for_walls(AsyncMock(), walls, settings)
    queue.assert_awaited_once()
    request = queue.call_args.kwargs
    assert request["job_type"] == JobType.CAD_OUTLINE_REVIEW
    assert request["workspace_id"] == walls.workspace_id
    assert request["payload"]["walls_job_id"] == str(walls.id)
    assert request["payload"]["pdf_page"] == 81
    assert request["payload"]["sources"] == pilot.sources
    assert request["idempotency_key"].startswith("cad-outline-review:v2:")
    assert request["idempotency_key"].endswith(":1")


def test_review_unavailable_without_pilot_or_unfinished_walls() -> None:
    pilot = _pilot()
    walls = _walls(pilot)
    # SSH настраивается у исполнителя CAD, API о нём не знает: доступность - только пилот.
    assert review_available(walls, Settings(cad_review_pilot=pilot.model_dump_json()))
    assert not review_available(walls, Settings())
    walls.status = JobStatus.RUNNING
    assert not review_available(walls, _settings(pilot))


async def test_running_review_is_returned_without_enqueue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pilot = _pilot()
    running = _review(JobStatus.RUNNING)
    queue = _stub_reviews(monkeypatch, [running, _review(JobStatus.FAILED)])
    result = await enqueue_for_walls(AsyncMock(), _walls(pilot), _settings(pilot))
    assert result is running
    queue.assert_not_awaited()


async def test_repeat_after_failed_review_gets_new_key(monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = _pilot()
    queue = _stub_reviews(monkeypatch, [_review(JobStatus.FAILED)])
    await enqueue_for_walls(AsyncMock(), _walls(pilot), _settings(pilot))
    queue.assert_awaited_once()
    assert queue.call_args.kwargs["idempotency_key"].endswith(":2")


def test_verdict_requires_coverage_of_all_four_sources() -> None:
    duplicate_sources = [
        {
            "role": "project",
            "applicability": "applicable",
            "reference": "лист 32",
            "observation": "План 14-го этажа",
        }
    ] * 4
    with pytest.raises(ValidationError, match="четырёх источников"):
        OutlineReport.model_validate(
            {
                "verdict": "ready_for_human_review",
                "sources": duplicate_sources,
                "findings": [],
                "limitations": [],
            }
        )
