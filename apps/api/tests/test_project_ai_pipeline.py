"""Этапы ИИ-проверки проекта (S3-A): сводка по листам и запуск этапов Claude."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_ai_review import AiLoopPilot, AiReviewResult
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.models import CadRemark, Job, Sheet
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.doc_questions_support import add_pdf, make_project
from tests.test_cad_queue import add_job
from tests.test_cad_summary import child_job, convert_job

DXF = "d" * 64


def _settings(project_id: str, *, max_iterations: int = 3) -> Settings:
    pilot = AiLoopPilot(
        project_id=uuid.UUID(project_id),
        max_iterations=max_iterations,
        sources={"vor": "/pilot/vor.md"},
    )
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true",
        cad_ai_loop=pilot.model_dump_json(),
    )


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/ai-pipeline{tail}"


class _Plan:
    """Проект с одной ревизией: на каждой странице преобразование и успешные конструкции."""

    def __init__(self) -> None:
        self.walls: list[Job] = []
        self.convert: list[Job] = []
        self.revision_id = uuid.uuid4()
        self.project_id = ""


async def _plan(
    session: AsyncSession,
    storage: FakeObjectStorage,
    api: AsyncClient,
    workspace_id: uuid.UUID,
    pages: int,
) -> _Plan:
    plan = _Plan()
    plan.project_id = await make_project(api)
    revision = await add_pdf(session, storage, plan.project_id, "АР План.pdf")
    plan.revision_id = revision.id
    pid = uuid.UUID(plan.project_id)
    for index in range(pages):
        session.add(
            Sheet(
                revision_id=revision.id,
                page_index=index,
                page_label=f"План {index + 1} этажа",
                rotation=0,
            )
        )
        convert = convert_job(
            session,
            workspace_id=workspace_id,
            project_id=pid,
            revision_id=revision.id,
            pages=[index],
            status=JobStatus.SUCCEEDED,
        )
        await session.flush()
        walls = child_job(
            session,
            parent=convert,
            job_type=JobType.CAD_WALLS,
            page_index=index,
            status=JobStatus.SUCCEEDED,
        )
        await session.flush()
        walls.payload = {
            **walls.payload,
            "parent_attempt": 1,
            "view": 0,
            "cad_result": {"attempt": 1, "page_index": index, "view": 0, "dxf_sha256": DXF},
        }
        plan.convert.append(convert)
        plan.walls.append(walls)
    await session.commit()
    return plan


def _result(
    walls: Job, role: str, verdict: str, *, cost: float | None = None, findings: int = 0
) -> dict[str, Any]:
    report = {
        "verdict": verdict,
        "findings": [
            {
                "type": "missing_wall",
                "priority": "major" if verdict == "needs_correction" else "minor",
                "bbox_px": [1.0, 1.0, 5.0, 5.0],
                "construction_ids": [],
                "observation": "нет стены",
                "evidence": "чертёж",
                "suggested_fix": "добавить",
            }
            for _ in range(findings)
        ],
        "props": [],
        "vor_check": [],
        "limitations": [],
    }
    return AiReviewResult.model_validate(
        {
            "walls_job_id": str(walls.id),
            "walls_attempt": 1,
            "cad_job_id": walls.payload["parent_job_id"],
            "revision_id": walls.payload["revision_id"],
            "page_index": walls.payload["page_index"],
            "view": 0,
            "role": role,
            "iteration": 1,
            "model": "claude-test",
            "input_sha256": "a" * 64,
            "walls_sha256": "b" * 64,
            "dxf_sha256": DXF,
            "prompt_sha256": "c" * 64,
            "bundle_sha256": "e" * 64,
            "sources": {},
            "usage": {"cost_usd": cost, "duration_ms": 1000 if cost is not None else None},
            "render": {"clip": [0, 0, 10, 10], "zoom": 1.0},
            "remark_keys": [],
            "report": report,
        }
    ).model_dump(mode="json")


def _review(
    session: AsyncSession,
    walls: Job,
    role: str,
    status: JobStatus,
    *,
    verdict: str = "needs_correction",
    cost: float | None = None,
    findings: int = 1,
    minutes: int = 1,
    attempt: int = 1,
) -> Job:
    payload: dict[str, Any] = {
        "walls_job_id": str(walls.id),
        "walls_attempt": attempt,
        "role": role,
    }
    if status is JobStatus.SUCCEEDED:
        payload["ai_review"] = _result(walls, role, verdict, cost=cost, findings=findings)
    assert walls.workspace_id is not None
    return add_job(
        session,
        workspace_id=walls.workspace_id,
        project_id=walls.project_id,
        status=status,
        minutes=minutes,
        job_type=JobType.CAD_AI_REVIEW,
        payload=payload,
        attempt=1,
    )


async def test_summary_counts_stages_costs_and_rows(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as probe:
        plan = await _plan(db_session, fake_storage, probe, workspace_id, 4)
    async with build_api(make_context(), settings=_settings(plan.project_id)) as api:
        w0, w1, w2, w3 = plan.walls
        # Стр. 0: правщик готов (0.5 $), проверщик идёт.
        _review(
            db_session,
            w0,
            "corrector",
            JobStatus.SUCCEEDED,
            verdict="ready_for_human_review",
            cost=0.5,
            findings=0,
            minutes=1,
        )
        _review(db_session, w0, "verifier", JobStatus.RUNNING, minutes=2)
        # Стр. 1: правщик нашёл 2 замечания.
        _review(db_session, w1, "corrector", JobStatus.SUCCEEDED, cost=0.25, findings=2)
        # Стр. 2: вердикт дан по старой попытке конструкций.
        _review(
            db_session,
            w2,
            "corrector",
            JobStatus.SUCCEEDED,
            verdict="ready_for_human_review",
            findings=0,
            attempt=0,
        )
        # Стр. 3: последний круг упал.
        _review(db_session, w3, "corrector", JobStatus.FAILED)
        db_session.add(
            CadRemark(
                workspace_id=workspace_id,
                project_id=uuid.UUID(plan.project_id),
                revision_id=plan.revision_id,
                job_id=plan.convert[1].id,
                attempt=1,
                page_index=1,
                view=0,
                remark_key="k1",
                type="missing_wall",
                comment="x",
                status="open",
                bbox_x0=0,
                bbox_y0=0,
                bbox_x1=1,
                bbox_y1=1,
            )
        )
        await db_session.commit()

        response = await api.get(_url(plan.project_id))
        assert response.status_code == 200, response.text
        body = response.json()

    assert body["available"] is True
    assert body["max_iterations"] == 3
    assert body["active"] is True
    stages = {item["stage"]: item for item in body["stages"]}
    assert stages[1]["total"] == 4 and stages[1]["done"] == 4 and stages[1]["status"] == "done"
    assert stages[2]["total"] == 4
    assert (stages[2]["done"], stages[2]["running"], stages[2]["failed"]) == (0, 1, 1)
    assert stages[2]["cost_usd"] == 0.75
    assert stages[2]["duration_ms"] == 2000
    assert stages[2]["status"] == "running"
    assert stages[3]["total"] == 4 and stages[3]["running"] == 1
    assert stages[3]["cost_usd"] is None
    assert stages[4]["total"] == 4 and stages[4]["done"] == 0
    rows = {row["page_index"]: row for row in body["sheets"]}
    assert rows[0]["stage2"]["state"] == "running"
    assert rows[0]["stage2"]["last_verdict"] == "ready_for_human_review"
    assert rows[0]["stage3"]["claude_running"] is True
    assert rows[1]["stage2"]["last_findings"] == 2
    assert rows[1]["stage2"]["rounds_done"] == 1
    assert rows[1]["stage4"]["open_remarks"] == 1
    assert rows[2]["stage2"]["verdict_stale"] is True
    assert rows[2]["stage2"]["state"] == "not_started"
    assert rows[3]["stage2"]["state"] == "failed"
    assert rows[0]["sheet_position"] == 1 and rows[3]["sheet_position"] == 4
    assert rows[0]["walls_job_id"] == str(w0.id)


async def test_project_without_pilot_has_no_ai_stages(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    settings = clean_settings(environment="test", feature_flags="cad.export=true")
    async with build_api(make_context(), settings=settings) as api:
        plan = await _plan(db_session, fake_storage, api, workspace_id, 1)
        body = (await api.get(_url(plan.project_id))).json()
        denied = await api.post(_url(plan.project_id, "/stages/review/run"))
    assert body["available"] is False
    stages = {item["stage"]: item for item in body["stages"]}
    assert stages[2]["total"] == 0 and stages[2]["status"] == "not_started"
    assert stages[4]["total"] == 1
    assert denied.json() == {"queued": 0, "skipped": []}


async def test_run_is_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as api:
        response = await api.get(_url(str(uuid.uuid4())))
    assert response.status_code == 403


async def test_run_review_skips_running_exhausted_and_done_views(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as probe:
        plan = await _plan(db_session, fake_storage, probe, workspace_id, 4)
    async with build_api(
        make_context(), settings=_settings(plan.project_id, max_iterations=2)
    ) as api:
        fresh, busy, spent, done = plan.walls
        _review(db_session, busy, "corrector", JobStatus.RUNNING)
        _review(db_session, spent, "corrector", JobStatus.SUCCEEDED, minutes=1)
        _review(db_session, spent, "corrector", JobStatus.FAILED, minutes=2)
        _review(
            db_session,
            done,
            "corrector",
            JobStatus.SUCCEEDED,
            verdict="ready_for_human_review",
            findings=0,
        )
        await db_session.commit()

        response = await api.post(_url(plan.project_id, "/stages/review/run"))
        assert response.status_code == 202, response.text
        body = response.json()
        again = (await api.post(_url(plan.project_id, "/stages/review/run"))).json()

    assert body["queued"] == 1
    reasons = {item["page_index"]: item["reason"] for item in body["skipped"]}
    assert set(reasons) == {1, 2, 3}
    assert "уже идёт" in reasons[1]
    assert "лимит" in reasons[2]
    assert "уже пройдена" in reasons[3]
    created = list(
        await db_session.scalars(
            select(Job).where(
                Job.job_type == JobType.CAD_AI_REVIEW,
                Job.payload["walls_job_id"].astext == str(fresh.id),
            )
        )
    )
    assert len(created) == 1 and created[0].payload["role"] == "corrector"
    # Повтор не дублирует: у вида уже идёт проверка.
    assert again["queued"] == 0


async def test_run_verify_needs_a_ready_corrector_verdict(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as probe:
        plan = await _plan(db_session, fake_storage, probe, workspace_id, 3)
    async with build_api(make_context(), settings=_settings(plan.project_id)) as api:
        ready, pending, verified = plan.walls
        _review(
            db_session,
            ready,
            "corrector",
            JobStatus.SUCCEEDED,
            verdict="ready_for_human_review",
            findings=0,
        )
        _review(db_session, pending, "corrector", JobStatus.SUCCEEDED)
        _review(
            db_session,
            verified,
            "corrector",
            JobStatus.SUCCEEDED,
            verdict="ready_for_human_review",
            findings=0,
            minutes=1,
        )
        _review(
            db_session,
            verified,
            "verifier",
            JobStatus.SUCCEEDED,
            verdict="ready_for_human_review",
            findings=0,
            minutes=2,
        )
        await db_session.commit()

        body = (await api.post(_url(plan.project_id, "/stages/verify/run"))).json()
        missing = await api.post(_url(plan.project_id, "/stages/other/run"))

    assert body["queued"] == 1
    reasons = {item["page_index"]: item["reason"] for item in body["skipped"]}
    assert set(reasons) == {1, 2}
    assert "Правщик" in reasons[1]
    assert "Проверщик" in reasons[2]
    assert missing.status_code == 422
    created = list(
        await db_session.scalars(
            select(Job).where(
                Job.job_type == JobType.CAD_AI_REVIEW,
                Job.payload["walls_job_id"].astext == str(ready.id),
                Job.payload["role"].astext == "verifier",
            )
        )
    )
    assert len(created) == 1


async def test_sheet_row_shows_style_classes_and_applied_regions(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as probe:
        plan = await _plan(db_session, fake_storage, probe, workspace_id, 3)
    async with build_api(make_context(), settings=_settings(plan.project_id)) as api:
        # Стр. 0: оформление дало 2 класса, движок взял 5 + 3 региона. Стр. 1: оформление идёт.
        # Стр. 2: оформление упало. Страница без заданий оформления - без поля.
        style = {
            "cad_job_id": str(plan.convert[0].id),
            "cad_attempt": 1,
            "revision_id": str(plan.revision_id),
            "page_index": 0,
            "view": 0,
            "model": "claude-test",
            "input_sha256": "a" * 64,
            "signatures_sha256": "b" * 64,
            "prompt_sha256": "c" * 64,
            "bundle_sha256": "d" * 64,
            "usage": {},
            "sources": {},
            "classes": [
                {
                    "signature_id": f"s{n}",
                    "class_name": "monolith",
                    "confidence": "high",
                    "evidence": "легенда",
                    "color": [0.1, 0.1, 0.1],
                    "pen_pt": 0.3,
                    "angle_deg": 45.0,
                    "pitch_pt": 3.0 + n,
                }
                for n in range(2)
            ],
            "dropped": [],
            "limitations": [],
        }
        for page, status in (
            (0, JobStatus.SUCCEEDED),
            (1, JobStatus.RUNNING),
            (2, JobStatus.FAILED),
        ):
            payload: dict[str, Any] = {
                "role": "style",
                "revision_id": str(plan.revision_id),
                "page_index": page,
                "view": 0,
            }
            if status is JobStatus.SUCCEEDED:
                payload["ai_style"] = style
            add_job(
                db_session,
                workspace_id=workspace_id,
                project_id=uuid.UUID(plan.project_id),
                status=status,
                minutes=1,
                job_type=JobType.CAD_AI_REVIEW,
                payload=payload,
                attempt=1,
                error_message="Claude не ответил" if status is JobStatus.FAILED else None,
            )
        plan.convert[0].payload = {
            **plan.convert[0].payload,
            "cad_result": {
                **plan.convert[0].payload["cad_result"],
                "hatch_applied": [
                    {
                        "page_index": 0,
                        "view": 0,
                        "classes": [{"added": 5, "status": "applied"}, {"added": 3}],
                    }
                ],
            },
        }
        await db_session.commit()
        body = (await api.get(_url(plan.project_id))).json()
    rows = sorted(body["sheets"], key=lambda row: row["page_index"])
    assert rows[0]["style"] == {
        "state": "ok",
        "classes_found": 2,
        "regions_applied": 8,
        "error_message": None,
    }
    assert rows[1]["style"]["state"] == "running" and rows[1]["style"]["classes_found"] is None
    assert rows[2]["style"]["state"] == "failed"
    assert rows[2]["style"]["error_message"] == "Claude не ответил"
    assert body["active"] is True
    # Нумерация этапов прежняя: оформление - поле вида, а не пятый этап.
    assert [item["stage"] for item in body["stages"]] == [1, 2, 3, 4]


async def test_sheet_without_style_jobs_has_no_style_field(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=clean_settings(environment="test")) as probe:
        plan = await _plan(db_session, fake_storage, probe, workspace_id, 1)
    async with build_api(make_context(), settings=_settings(plan.project_id)) as api:
        body = (await api.get(_url(plan.project_id))).json()
    assert body["sheets"][0]["style"] is None
