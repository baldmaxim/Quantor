"""Пилот отправляет на внешнюю проверку только согласованные проект, ревизию и вид."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.cad_worker.outline_review import enqueue_after_walls
from app.contracts.cad_outline_review import SOURCE_ROLES, OutlinePilot, OutlineReport, PilotFloor
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.models import Job
from app.services import jobs


@pytest.mark.parametrize("scope", ["matched", "foreign_project", "foreign_revision", "other_view"])
async def test_review_queue_is_limited_to_pilot(
    scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot = OutlinePilot(
        project_id=uuid4(),
        revision_id=uuid4(),
        section=3,
        floors=[
            PilotFloor(floor=14, pdf_page=81, view=1),
            PilotFloor(floor=15, pdf_page=82, view=1),
        ],
        sources={role: f"/pilot/{role}.md" for role in SOURCE_ROLES},
    )
    walls = Job(
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
    queue = AsyncMock()
    monkeypatch.setattr(jobs, "enqueue", queue)
    session = AsyncMock()
    settings = Settings(cad_review_pilot=pilot.model_dump_json())
    await enqueue_after_walls(session, walls, settings)
    if scope != "matched":
        queue.assert_not_awaited()
        return
    queue.assert_awaited_once()
    request = queue.call_args.kwargs
    assert request["job_type"] == JobType.CAD_OUTLINE_REVIEW
    assert request["workspace_id"] == walls.workspace_id
    assert request["payload"]["walls_job_id"] == str(walls.id)
    assert request["payload"]["pdf_page"] == 81
    assert request["payload"]["sources"] == pilot.sources


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
