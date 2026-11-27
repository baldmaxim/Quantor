"""Листы CAD проекта, которым нужен масштаб: GET /projects/{id}/cad/scale-needed."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from app.models import Job, ScaleCalibration, Sheet
from tests.conftest import FakeObjectStorage, make_context
from tests.doc_questions_support import add_pdf, make_project
from tests.test_cad_queue import BASE, add_job, queue_settings
from tests.test_cad_summary import add_sheets


def url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/scale-needed"


def convert(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    page: int,
    status: JobStatus,
    minutes: int = 0,
    error_code: str | None = None,
    scale_status: str | None = "passed",
    scale_source: str | None = None,
    deviation: float | None = None,
    pages: list[int] | None = None,
    unconfirmed: list[int] | None = None,
) -> Job:
    payload: dict[str, Any] = {
        "revision_id": str(revision_id),
        "params": {"pages": pages if pages is not None else [page]},
        "cad_attempts": [{"outcome": "x" * 50}],
    }
    if status is JobStatus.SUCCEEDED:
        row: dict[str, Any] = {"view": 0}
        if scale_status is not None:
            row["scale_status"] = scale_status
        if scale_source is not None:
            row["scale_source"] = scale_source
        if deviation is not None:
            row["scale_deviation"] = deviation
        payload["cad_result"] = {"attempt": 1, "pages": [{"index": page, "views": [row]}]}
    elif status is JobStatus.FAILED and unconfirmed is not None:
        payload["cad_result"] = {"attempt": 1, "unconfirmed_pages": unconfirmed}
    return add_job(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        status=status,
        minutes=minutes,
        job_type=JobType.CAD_PDF_CONVERT,
        payload=payload,
        attempt=1,
        error_code=error_code,
    )


async def test_scale_needed_is_closed_when_the_flag_is_off(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=queue_settings(flag=False)) as api:
        response = await api.get(url(str(uuid.uuid4())))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_scale_needed_lists_failed_and_scale_less_sheets(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["Лист 0", "Лист 1", "Лист 2", "Лист 3", "Лист 4"])
        common = {"workspace_id": workspace_id, "project_id": pid, "revision_id": revision.id}
        # 0: отказ, затем отменённое задание (не скрывает отказ); 1: автомасштаб не подтверждён;
        # 2: масштаб вида не принят; 3: в очереди после отказа (исключается); 4: всё в порядке.
        convert(
            db_session,
            **common,
            page=0,
            status=JobStatus.FAILED,
            error_code="CAD_AUTO_SCALE_UNCONFIRMED",
        )
        convert(db_session, **common, page=0, status=JobStatus.CANCELLED, minutes=5)
        convert(
            db_session,
            **common,
            page=1,
            status=JobStatus.FAILED,
            error_code="CAD_AUTO_SCALE_UNCONFIRMED",
        )
        bad = convert(
            db_session, **common, page=2, status=JobStatus.SUCCEEDED, scale_status="failed"
        )
        convert(
            db_session,
            **common,
            page=3,
            status=JobStatus.FAILED,
            error_code="CAD_AUTO_SCALE_UNCONFIRMED",
        )
        convert(db_session, **common, page=3, status=JobStatus.QUEUED, minutes=5)
        convert(db_session, **common, page=4, status=JobStatus.SUCCEEDED)
        await db_session.commit()

        body = (await api.get(url(project_id))).json()
        assert body["total"] == 3
        rows = {item["page_index"]: item for item in body["items"]}
        assert sorted(rows) == [0, 1, 2]
        assert rows[0]["reason"] == "auto_scale_unconfirmed"
        assert rows[0]["view"] is None
        assert rows[0]["page_label"] == "Лист 0"
        assert rows[0]["document_title"]
        assert rows[1]["reason"] == "auto_scale_unconfirmed"
        assert rows[2]["reason"] == "scale_missing"
        assert rows[2]["view"] == "0"
        assert rows[2]["sheet_position"] == 3
        assert rows[2]["convert_job_id"] == str(bad.id)
        assert rows[2]["revision_id"] == str(revision.id)


async def test_scale_needed_uses_zone_error_when_scale_status_is_unknown(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["Лист 0", "Лист 1"])
        common = {"workspace_id": workspace_id, "project_id": pid, "revision_id": revision.id}
        for page, message in ((0, "scale.json: no positive scale"), (1, "другая ошибка")):
            parent = convert(
                db_session, **common, page=page, status=JobStatus.SUCCEEDED, scale_status=None
            )
            await db_session.flush()
            add_job(
                db_session,
                workspace_id=workspace_id,
                project_id=pid,
                status=JobStatus.FAILED,
                minutes=1,
                job_type=JobType.CAD_ZONES,
                payload={
                    "revision_id": str(revision.id),
                    "parent_job_id": str(parent.id),
                    "page_index": page,
                    "view": 0,
                },
                attempt=1,
                error_code="CAD_INPUT_INVALID",
                error_message=message,
            )
        await db_session.commit()

        body = (await api.get(url(project_id))).json()
        assert [item["page_index"] for item in body["items"]] == [0]
        assert body["items"][0]["reason"] == "scale_missing"


async def calibrate(
    db_session: AsyncSession, revision_id: uuid.UUID, page: int, *, minutes: int
) -> None:
    sheet_id = await db_session.scalar(
        select(Sheet.id).where(Sheet.revision_id == revision_id, Sheet.page_index == page)
    )
    assert sheet_id is not None
    db_session.add(
        ScaleCalibration(
            sheet_id=sheet_id,
            point_a_x=Decimal("0"),
            point_a_y=Decimal("0"),
            point_b_x=Decimal("1"),
            point_b_y=Decimal("0"),
            input_value=Decimal("10000"),
            input_unit="mm",
            known_distance_mm=Decimal("10000"),
            page_distance_pt=Decimal("1000"),
            mm_per_pt=Decimal("10"),
            page_geometry_fingerprint="a" * 64,
            is_default=True,
            created_at=BASE + timedelta(minutes=minutes),
        )
    )


async def test_scale_needed_marks_only_unconfirmed_pages_of_a_failed_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["Лист 0", "Лист 1", "Лист 2", "Лист 3"])
        common = {"workspace_id": workspace_id, "project_id": pid, "revision_id": revision.id}
        code = "CAD_AUTO_SCALE_UNCONFIRMED"
        # Структурный список: из страниц 0 и 1 не подтверждена только 1.
        convert(
            db_session,
            **common,
            page=0,
            pages=[0, 1],
            status=JobStatus.FAILED,
            error_code=code,
            unconfirmed=[1],
        )
        # Старое задание без списка: помечаются все его страницы.
        convert(
            db_session, **common, page=2, pages=[2, 3], status=JobStatus.FAILED, error_code=code
        )
        await db_session.commit()

        body = (await api.get(url(project_id))).json()
        assert sorted(item["page_index"] for item in body["items"]) == [1, 2, 3]


async def test_scale_needed_reports_rerun_after_later_calibration(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["Лист 0", "Лист 1", "Лист 2"])
        common = {"workspace_id": workspace_id, "project_id": pid, "revision_id": revision.id}
        # 0: отказ, калибровка позже; 1: вид без масштаба, калибровка позже;
        # 2: отказ, калибровка была раньше преобразования.
        for page in (0, 2):
            convert(
                db_session,
                **common,
                page=page,
                minutes=10,
                status=JobStatus.FAILED,
                error_code="CAD_AUTO_SCALE_UNCONFIRMED",
            )
        convert(
            db_session,
            **common,
            page=1,
            minutes=10,
            status=JobStatus.SUCCEEDED,
            scale_status="failed",
        )
        await db_session.flush()
        await calibrate(db_session, revision.id, 0, minutes=20)
        await calibrate(db_session, revision.id, 1, minutes=20)
        await calibrate(db_session, revision.id, 2, minutes=5)
        await db_session.commit()

        body = (await api.get(url(project_id))).json()
        rows = {item["page_index"]: item for item in body["items"]}
        assert rows[0]["reason"] == "rerun_needed"
        assert rows[1]["reason"] == "rerun_needed"
        assert rows[1]["view"] == "0"
        assert rows[2]["reason"] == "auto_scale_unconfirmed"


async def test_scale_needed_checks_operator_scale_against_the_limit(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    async with build_api(make_context(), settings=queue_settings()) as api:
        project_id = await make_project(api)
        pid = uuid.UUID(project_id)
        revision = await add_pdf(db_session, fake_storage, project_id, "АР План.pdf")
        add_sheets(db_session, revision.id, ["Лист 0", "Лист 1", "Лист 2"])
        common = {"workspace_id": workspace_id, "project_id": pid, "revision_id": revision.id}
        # 0: расхождение 3 % (больше допуска 2 %); 1: 1,5 % (в допуске); 2: подбора нет.
        for page, deviation in ((0, 0.03), (1, 0.015), (2, None)):
            convert(
                db_session,
                **common,
                page=page,
                status=JobStatus.SUCCEEDED,
                scale_status="needs_review",
                scale_source="operator_calibration",
                deviation=deviation,
            )
        await db_session.commit()

        body = (await api.get(url(project_id))).json()
        assert [item["page_index"] for item in body["items"]] == [0]
        assert body["items"][0]["reason"] == "scale_missing"
