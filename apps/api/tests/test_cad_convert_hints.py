"""Подсказки замечаний в преобразование PDF -> DXF: перевод, параметры, идемпотентность."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_convert_hints import CadConvertHints
from app.domain import JobStatus
from app.models import CadRemark, Job
from app.services import cad_views
from app.services.cad_convert_hints import hints_from_remarks
from tests.conftest import make_context
from tests.test_cad_qa import BROKEN_PDF, _upload_calibrated, cad_settings
from tests.test_cad_remarks import QUERY, _body


def _remark(
    key: str,
    kind: str = "missing_wall",
    status: str = "open",
    bbox: tuple[float, float, float, float] = (30.0, 50.0, 10.0, 20.0),
    comment: str = "к замечанию",
) -> CadRemark:
    now = datetime.now(UTC)
    return CadRemark(
        remark_key=key,
        type=kind,
        comment=comment,
        status=status,
        bbox_x0=bbox[0],
        bbox_y0=bbox[1],
        bbox_x1=bbox[2],
        bbox_y1=bbox[3],
        created_at=now,
        updated_at=now,
    )


def test_hints_from_remarks_filters_and_normalizes() -> None:
    long_comment = "я" * 900
    remarks = [
        _remark("a", "missing_wall", comment=long_comment),
        _remark("b", "missing_door", bbox=(1, 2, 3, 4)),
        _remark("c", "false_wall"),
        _remark("d", "missing_wall", status="resolved"),
        _remark("e", "missing_wall", bbox=(5, 5, 5, 9)),
    ]
    hints = hints_from_remarks(remarks, 3)
    assert hints is not None
    assert hints.page == 3
    assert [h.id for h in hints.hints] == ["a", "b"]
    assert tuple(hints.hints[0].bbox_pt) == (10.0, 20.0, 30.0, 50.0)
    assert len(hints.hints[0].comment) == 500
    params = hints.to_params()
    assert params["schema"] == "quantor.cad_convert_hints.v1"
    assert params["page"] == 3


def test_hints_from_remarks_none_without_suitable() -> None:
    assert hints_from_remarks([_remark("c", "false_wall")], 1) is None
    assert hints_from_remarks([], 1) is None


@pytest.mark.parametrize(
    "hint",
    [
        {"id": "", "type": "missing_wall", "bbox_pt": [0, 0, 1, 1]},
        {"id": "a", "type": "other", "bbox_pt": [0, 0, 1, 1]},
        {"id": "a", "type": "missing_wall", "bbox_pt": [1, 0, 0, 1]},
        {"id": "a", "type": "missing_wall", "bbox_pt": [0, 0, float("inf"), 1]},
        {"id": "a", "type": "missing_wall", "bbox_pt": [0, 0, 1]},
    ],
)
def test_contract_rejects_bad_hint(hint: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CadConvertHints.model_validate({"page": 1, "hints": [hint]})


def test_contract_rejects_duplicate_ids() -> None:
    hint = {"id": "a", "type": "missing_wall", "bbox_pt": [0, 0, 1, 1]}
    with pytest.raises(ValidationError):
        CadConvertHints.model_validate({"page": 1, "hints": [hint, hint]})


def test_checks_from_reports_hints_applied() -> None:
    checks = cad_views.checks_from(
        {},
        {
            "hints_applied": [
                {"id": "a", "type": "missing_wall", "status": "applied", "added": 2, "reason": ""},
                {"id": 5},
            ]
        },
    )
    assert checks is not None and checks.hints_applied is not None
    assert [(h.id, h.status, h.added) for h in checks.hints_applied] == [("a", "applied", 2)]
    plain = cad_views.checks_from({}, {})
    assert plain is not None and plain.hints_applied is None


async def _succeeded_job(api: AsyncClient, db_session: AsyncSession) -> tuple[str, str, str, str]:
    project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
    base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
    created = await api.post(base, json={"pages": [0]})
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    job = await db_session.get(Job, uuid.UUID(job_id))
    assert job is not None
    payload = dict(job.payload)
    payload["cad_result"] = {
        "attempt": 1,
        "result_status": "succeeded",
        "artifacts": [],
        "pages": [{"index": 0, "views": [{"view": 1, "status": "succeeded"}]}],
    }
    await db_session.execute(
        update(Job)
        .where(Job.id == job.id)
        .values(attempt=1, status=JobStatus.SUCCEEDED, payload=payload)
    )
    await db_session.commit()
    return project_id, revision_id, job_id, base


async def test_reconvert_copies_params_adds_hints_and_is_idempotent(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        _, _, job_id, base = await _succeeded_job(api, db_session)
        url = f"{base}/{job_id}/views/0/1/reconvert-by-remarks"

        # Без замечаний - отказ с понятным текстом.
        empty = await api.post(url)
        assert empty.status_code == 422, empty.text

        key = str(uuid.uuid4())
        saved = await api.put(f"{base}/{job_id}/remarks/{key}?{QUERY}", json=_body())
        assert saved.status_code == 200, saved.text
        await api.put(
            f"{base}/{job_id}/remarks/{uuid.uuid4()}?{QUERY}",
            json=_body(type="false_wall"),
        )

        first = await api.post(url)
        assert first.status_code == 202, first.text
        new_id = first.json()["job_id"]
        assert new_id != job_id

        source = await db_session.get(Job, uuid.UUID(job_id))
        created = await db_session.get(Job, uuid.UUID(new_id))
        assert source is not None and created is not None
        await db_session.refresh(created)
        params = created.payload["params"]
        old = source.payload["params"]
        assert params["pages"] == [0]
        assert params["scales"] == old["scales"]
        assert params["limits"] == old["limits"]
        assert params["convert_hints"]["page"] == 1
        assert [h["id"] for h in params["convert_hints"]["hints"]] == [key]
        assert params["convert_hints"]["hints"][0]["bbox_pt"] == [10.0, 20.0, 110.0, 120.0]
        assert created.payload["revision_id"] == source.payload["revision_id"]
        assert "convert_hints" not in old

        # Те же замечания - то же задание, без дубля.
        again = await api.post(url)
        assert again.status_code == 202, again.text
        assert again.json()["job_id"] == new_id
        jobs = list(await db_session.scalars(select(Job.id).where(Job.id == uuid.UUID(new_id))))
        assert len(jobs) == 1

        # Новое замечание - новые параметры и новое задание.
        await api.put(
            f"{base}/{job_id}/remarks/{uuid.uuid4()}?{QUERY}", json=_body(type="missing_door")
        )
        third = await api.post(url)
        assert third.status_code == 202, third.text
        assert third.json()["job_id"] != new_id


async def test_reconvert_requires_ready_result(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
        created = await api.post(base, json={"pages": [0]})
        job_id = created.json()["job_id"]
        response = await api.post(f"{base}/{job_id}/views/0/1/reconvert-by-remarks")
        assert response.status_code == 409, response.text
