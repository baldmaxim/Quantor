"""Копирование реестра стояков с другого листа (ADR-0041): сопоставление шахт и API черновика."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import CadSheetRisers, Job, Workspace
from app.services import cad as cad_service
from app.services.cad_risers_copy import ShaftPoint, map_shafts, parse_shafts
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload, _upload_calibrated, cad_settings

OV = frozenset({"ОВ"})
VK = frozenset({"ВК"})


def _p(shaft_id: str, x: float, y: float, systems: frozenset[str] = OV) -> ShaftPoint:
    return ShaftPoint(id=shaft_id, systems=systems, x=x, y=y)


GRID = [(0.0, 0.0), (5000.0, 0.0), (10000.0, 1000.0), (2000.0, 7000.0)]


def _plan(shift: tuple[float, float] = (0, 0), first: int = 1) -> list[ShaftPoint]:
    return [_p(f"S{first + i:02d}", x + shift[0], y + shift[1]) for i, (x, y) in enumerate(GRID)]


# ------------------------------------------------------------------ map_shafts


def test_same_plan_with_shift_matches_all() -> None:
    mapping = map_shafts(_plan(), _plan(shift=(-100, 0)))
    assert mapping.shift == (-100, 0)
    assert {k: v.target_id for k, v in mapping.matches.items()} == {
        "S01": "S01",
        "S02": "S02",
        "S03": "S03",
        "S04": "S04",
    }
    assert all(v.distance_mm == 0 for v in mapping.matches.values())


def test_other_numbers_at_same_positions_are_transferred() -> None:
    mapping = map_shafts(_plan(), _plan(first=11))
    assert mapping.shift == (0, 0)
    assert {k: v.target_id for k, v in mapping.matches.items()} == {
        "S01": "S11",
        "S02": "S12",
        "S03": "S13",
        "S04": "S14",
    }


def test_different_systems_do_not_match() -> None:
    target = [_p(s.id, s.x, s.y, VK) for s in _plan()]
    mapping = map_shafts(_plan(), target)
    assert mapping.shift is None and mapping.matches == {}


def test_shaft_absent_on_target_is_not_found() -> None:
    mapping = map_shafts(_plan(), _plan()[:3])
    assert mapping.shift == (0, 0)
    assert set(mapping.matches) == {"S01", "S02", "S03"}


def test_two_source_shafts_in_one_target_keep_the_nearer() -> None:
    source = [*_plan(), _p("S09", 200, 0)]
    mapping = map_shafts(source, _plan())
    assert mapping.shift == (0, 0)
    assert mapping.matches["S01"].target_id == "S01"
    assert "S09" not in mapping.matches


def test_too_few_votes_means_no_shift() -> None:
    mapping = map_shafts(_plan()[:2], _plan()[:2])
    assert mapping.shift is None and mapping.matches == {}


def test_parse_shafts_skips_invalid_items() -> None:
    raw = {
        "shafts": [
            {"id": "S01", "systems": ["ОВ"], "centroid_dxf_mm": [10, 20], "extra": 1},
            {"id": "bad", "systems": ["ОВ"], "centroid_dxf_mm": [10, 20]},
            {"id": "S02", "systems": ["ОВ"]},
            {"id": "S01", "systems": ["ВК"], "centroid_dxf_mm": [1, 1]},
            "junk",
        ]
    }
    assert parse_shafts(raw) == [_p("S01", 10, 20)]
    assert parse_shafts({"shafts": 5}) == [] and parse_shafts([]) == []


# ------------------------------------------------------------------ HTTP


def _riser(**patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"system": "V1", "mark": "В1.1.1", "dn_mm": 50, "role": "own"}
    body.update(patch)
    return body


def _query(revision_id: str, page_index: int = 0, view: int = 1) -> str:
    return f"?revision_id={revision_id}&page_index={page_index}&view={view}"


def _copy_url(project_id: str, revision_id: str, *, target: int = 1, source: int = 0) -> str:
    return (
        f"/api/v1/projects/{project_id}/cad/risers/copy{_query(revision_id, target)}"
        f"&source_page_index={source}&source_view=1"
    )


async def _put(api: AsyncClient, project_id: str, revision_id: str, page: int, body: Any) -> None:
    url = f"/api/v1/projects/{project_id}/cad/risers{_query(revision_id, page)}"
    assert (await api.put(url, json={"risers": body})).status_code == 200


async def _route_job(
    session: AsyncSession,
    storage: FakeObjectStorage,
    *,
    project_id: str,
    revision_id: str,
    page_index: int,
    shafts: list[dict[str, Any]],
) -> None:
    """Успешное `cad_mep_route` листа с candidate.json, как его оставил бы исполнитель."""
    job_id = uuid.uuid4()
    name = f"{cad_service.view_folder(page_index, 1)}/candidate.json"
    key = cad_service.artifact_storage_key(uuid.UUID(revision_id), job_id, 1, name)
    await storage.put_bytes(
        key, json.dumps({"shafts": shafts}).encode(), content_type="application/json"
    )
    session.add(
        Job(
            id=job_id,
            project_id=uuid.UUID(project_id),
            workspace_id=DEV_WORKSPACE_ID,
            job_type=JobType.CAD_MEP_ROUTE,
            status=JobStatus.SUCCEEDED,
            attempt=1,
            payload={
                "revision_id": revision_id,
                "page_index": page_index,
                "view": 1,
                "cad_result": {"attempt": 1, "artifacts": [{"name": name, "key": key}]},
            },
        )
    )
    await session.commit()


def _shafts(shift: int = 0, first: int = 1) -> list[dict[str, Any]]:
    return [
        {"id": f"S{first + i:02d}", "systems": ["ОВ"], "centroid_dxf_mm": [int(x) + shift, int(y)]}
        for i, (x, y) in enumerate(GRID)
    ]


def test_copy_routes_are_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    sheets = paths["/api/v1/projects/{project_id}/cad/risers/sheets"]["get"]
    copy = paths["/api/v1/projects/{project_id}/cad/risers/copy"]["get"]
    assert sheets["operationId"] == "list_cad_risers_sheets"
    assert copy["operationId"] == "draft_cad_risers_copy"


async def test_lists_sheets_with_nonempty_registry(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        await _put(api, project_id, revision_id, 2, [_riser(), _riser(mark="В1.2")])
        await _put(api, project_id, revision_id, 0, [_riser()])
        await _put(api, project_id, revision_id, 1, [])
        response = await api.get(
            f"/api/v1/projects/{project_id}/cad/risers/sheets?revision_id={revision_id}"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["revision_id"] == revision_id
        assert [(s["page_index"], s["view"], s["risers_count"]) for s in body["sheets"]] == [
            (0, 1, 1),
            (2, 1, 2),
        ]
        assert all(s["updated_at"] for s in body["sheets"])


async def test_copy_transfers_shaft_ids_by_position(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        await _put(
            api,
            project_id,
            revision_id,
            0,
            [
                _riser(shaft_id="S02"),
                _riser(mark="В1.2", shaft_id="S04"),
                _riser(mark="В1.3"),
            ],
        )
        # На цели шахты сдвинуты и пронумерованы иначе, шахты S04 источника там нет.
        await _route_job(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            page_index=0,
            shafts=_shafts(),
        )
        await _route_job(
            db_session,
            fake_storage,
            project_id=project_id,
            revision_id=revision_id,
            page_index=1,
            shafts=_shafts(shift=-100, first=11)[:3],
        )
        stored_before = (await db_session.scalars(select(CadSheetRisers))).all()
        response = await api.get(_copy_url(project_id, revision_id))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["shafts"] == "matched" and body["shift_mm"] == [-100, 0]
        assert (body["page_index"], body["view"]) == (1, 1)
        assert (body["source_page_index"], body["source_view"]) == (0, 1)
        assert [r["shaft_id"] for r in body["risers"]] == ["S12", None, None]
        assert [r["mark"] for r in body["risers"]] == ["В1.1.1", "В1.2", "В1.3"]
        assert body["rows"] == [
            {
                "index": 0,
                "source_shaft_id": "S02",
                "shaft_id": "S12",
                "status": "matched",
                "distance_mm": 0,
            },
            {
                "index": 1,
                "source_shaft_id": "S04",
                "shaft_id": None,
                "status": "not_found",
                "distance_mm": None,
            },
            {
                "index": 2,
                "source_shaft_id": None,
                "shaft_id": None,
                "status": "no_shaft",
                "distance_mm": None,
            },
        ]
        # Только чтение: реестр цели не записан.
        count = await db_session.scalar(select(func.count()).select_from(CadSheetRisers))
        assert count == len(stored_before) == 1


async def test_copy_without_route_jobs_is_unknown_and_unverified(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        await _put(api, project_id, revision_id, 0, [_riser(shaft_id="S02"), _riser(mark="В1.2")])
        response = await api.get(_copy_url(project_id, revision_id))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["shafts"] == "unknown" and body["shift_mm"] is None
        assert [r["shaft_id"] for r in body["risers"]] == ["S02", None]
        assert [(r["status"], r["distance_mm"]) for r in body["rows"]] == [
            ("unverified", None),
            ("unverified", None),
        ]


async def test_copy_to_the_same_sheet_is_422_and_empty_source_is_404(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        await _put(api, project_id, revision_id, 0, [_riser()])
        same = await api.get(_copy_url(project_id, revision_id, target=0, source=0))
        assert same.status_code == 422
        assert same.json()["detail"]["code"] == "VALIDATION_FAILED"
        empty = await api.get(_copy_url(project_id, revision_id, target=0, source=3))
        assert empty.status_code == 404
        assert "Реестр стояков листа-источника" in empty.json()["detail"]["message"]


async def test_copy_flag_off_and_foreign_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        await _put(api, project_id, revision_id, 0, [_riser()])
        _, other_revision = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        assert (await api.get(_copy_url(project_id, other_revision))).status_code == 404
    sheets_url = f"/api/v1/projects/{project_id}/cad/risers/sheets?revision_id={revision_id}"
    async with build_api(make_context(), settings=cad_settings(tmp_path, flag=False)) as api:
        for response in (
            await api.get(_copy_url(project_id, revision_id)),
            await api.get(sheets_url),
        ):
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"
    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(_copy_url(project_id, revision_id))).status_code == 404
        assert (await foreign.get(sheets_url)).status_code == 404


@pytest.mark.parametrize("missing", ["source_page_index", "source_view"])
async def test_copy_requires_source_params(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    tmp_path: Path,
    missing: str,
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = _copy_url(project_id, revision_id).replace(f"&{missing}=", "&x=")
        assert (await api.get(url)).status_code == 422
