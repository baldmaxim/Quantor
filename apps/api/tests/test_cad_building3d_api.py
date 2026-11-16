"""Общий вид здания для 3D: маршрут, границы доступа, этажи проекта, пропуск сбойных листов."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType, Role
from app.main import create_app
from app.models import DocumentRevision, Job, SheetPassport, Workspace
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import PARAMS, _ready_sheet, walls_settings
from tests.test_cad_floor3d_api import BASE, FLOOR_STUB, SECTION
from tests.test_cad_mep import _parent


@pytest.fixture
def floor_tools(tmp_path: Path) -> Path:
    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_walls.py").write_text(FLOOR_STUB, encoding="utf-8")
    return root


def _url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/building3d"


def _codes(body: dict[str, object]) -> list[str]:
    warnings = body["warnings"]
    assert isinstance(warnings, list)
    return [w["code"] for w in warnings]


def test_route_is_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/cad/building3d"]) == {"get"}


async def test_route_is_closed_when_the_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(
        make_context(), settings=walls_settings(floor_tools, tmp_path, flag=False)
    ) as api:
        response = await api.get(_url(str(uuid.uuid4())))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_unknown_project_is_404_and_foreign_workspace_sees_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings) as api:
        assert (await api.get(_url(str(uuid.uuid4())))).status_code == 404
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(_url(project_id))).status_code == 404


async def test_floor_of_a_ready_sheet_follows_project_levels_for_viewer(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        await api.put(
            f"/api/v1/projects/{project_id}/cad/levels",
            json={"slab_thickness_mm": 250, "slab_source_ref": SECTION},
        )
    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=settings) as reader:
        response = await reader.get(_url(project_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["units"] == "mm" and body["warnings"] == [] and body["service_sheets"] == []
    (floor,) = body["floors"]
    assert (floor["job_id"], floor["revision_id"]) == (job_id, revision_id)
    assert (floor["page_index"], floor["view"]) == (0, 1)
    assert floor["document_id"] is not None and "лист 1" in floor["label"]
    assert (floor["elevation_known"], floor["base_z_mm"]) == (True, BASE)
    assert (floor["floor_height_mm"], floor["slab_thickness_mm"]) == (3000, 250)
    assert (floor["floor_height_source"], floor["typical_of"]) == (None, None)
    assert floor["outline_source"] == "slab"
    assert floor["outline"] == [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]
    assert floor["bbox"] == [0.0, 0.0, 6000.0, 4000.0]
    # Заглушка не пишет заголовок плана и оси: здание без корпуса, этаж не совмещён.
    assert (floor["corps"], floor["section"]) == (None, None)
    assert (floor["group_key"], floor["group_label"]) == ("none", "Корпус не указан")
    assert (floor["alignment"], floor["offset_mm"], floor["alignment_axes"]) == (
        "none",
        [0.0, 0.0],
        [],
    )
    assert floor["alignment_message"] == (
        "в группе нет этажа с осями в обоих направлениях; "
        "лист: оси не распознаны: пересчитайте конструкции листа"
    )
    assert body["groups"] == [
        {
            "key": "none",
            "label": "Корпус не указан",
            "floor_count": 1,
            "aligned_count": 0,
            "placement": "reference",
            "site_offset_mm": [0.0, 0.0],
            "site_rotation_deg": 0.0,
            "placement_share": None,
            "placement_axes": [],
            "placement_anchor": None,
            "placement_message": None,
        }
    ]


async def test_sheet_without_walls_is_skipped_with_warning(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _base = await _parent(api, db_session, fake_storage)
        body = (await api.get(_url(project_id))).json()
    assert body["floors"] == []
    assert _codes(body) == ["walls_not_ready"]


async def test_unreadable_walls_file_does_not_fail_the_response(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        for key in [k for k in fake_storage.objects if k.endswith("/walls.json")]:
            fake_storage.objects[key] = b"{not json"
        broken = (await api.get(_url(project_id))).json()
        assert broken["floors"] == [] and _codes(broken) == ["walls_unreadable"]
        for key in [k for k in fake_storage.objects if k.endswith("/walls.json")]:
            fake_storage.objects[key] = b'{"schema": "x"}'
        invalid = (await api.get(_url(project_id))).json()
        assert invalid["floors"] == [] and _codes(invalid) == ["walls_invalid"]


async def test_axes_in_walls_file_make_the_single_floor_a_reference(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        for key in [k for k in fake_storage.objects if k.endswith("/walls.json")]:
            raw = json.loads(fake_storage.objects[key])
            raw["heights"]["title"] = {"corps": "9", "section": "3", "floors": [1], "text": None}
            raw["axes"] = {
                "status": "found",
                "message": None,
                "diameter_pt": 12.0,
                "items": [
                    {"label": "3.1", "orient": "vertical", "pos_pt": 110.0, "bubbles_pt": []},
                    {"label": "А", "orient": "horizontal", "pos_pt": 10.0, "bubbles_pt": []},
                ],
                "conflicts": [],
                "rejected": 0,
            }
            fake_storage.objects[key] = json.dumps(raw).encode()
        body = (await api.get(_url(project_id))).json()
    (floor,) = body["floors"]
    assert (floor["group_key"], floor["group_label"]) == ("k9-s3", "Корп. 9 · сек. 3")
    assert floor["alignment"] == "reference" and floor["alignment_message"] is None
    assert body["groups"] == [
        {
            "key": "k9-s3",
            "label": "Корп. 9 · сек. 3",
            "floor_count": 1,
            "aligned_count": 1,
            "placement": "reference",
            "site_offset_mm": [0.0, 0.0],
            "site_rotation_deg": 0.0,
            "placement_share": None,
            "placement_axes": [],
            "placement_anchor": None,
            "placement_message": None,
        }
    ]


async def test_walls_query_adds_construction_rings_and_default_stays_light(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        light = (await api.get(_url(project_id))).json()
        full = (await api.get(_url(project_id), params={"walls": "true"})).json()
    (light_floor,) = light["floors"]
    (floor,) = full["floors"]
    assert light_floor["walls"] is None
    assert floor["walls"], "стены не вернулись"
    assert all(w["kind"] != "floor_slab" and len(w["shell"]) >= 3 for w in floor["walls"])
    assert all(isinstance(w["id"], str) and w["id"] for w in floor["walls"])
    assert all(isinstance(v, int) for w in floor["walls"] for p in w["shell"] for v in p)


async def test_plans_by_passports_without_cad_are_named_in_warnings(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    """План по паспорту листа без DXF: название листа и код последней конвертации."""
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        revision = await db_session.get(DocumentRevision, uuid.UUID(revision_id))
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert revision is not None and parent is not None
        rows = (
            (0, "floor_plan", "План 1 этажа", "candidate"),  # лист в 3D есть
            (3, "floor_plan", "План 4 этажа", "candidate"),
            (4, "section", "Разрез 1-1", "candidate"),
            (5, "floor_plan", "План 6 этажа", "rejected"),
            (6, "floor_plan", None, "confirmed"),
        )
        for page, kind, title, status in rows:
            db_session.add(
                SheetPassport(
                    project_id=uuid.UUID(project_id),
                    revision_id=revision.id,
                    page_index=page,
                    file_name=revision.source_filename,
                    sheet_kind=kind,
                    title=title,
                    status=status,
                )
            )
        views = [{"view": 1, "status": "needs_review", "scale_status": "needs_review"}]
        db_session.add(
            Job(
                job_type=JobType.CAD_PDF_CONVERT,
                workspace_id=parent.workspace_id,
                project_id=parent.project_id,
                status=JobStatus.FAILED,
                error_code="CAD_ENGINE_FAILED",
                payload={
                    "revision_id": revision_id,
                    "params": {"pages": [3]},
                    "cad_result": {"attempt": 1, "pages": [{"index": 3, "views": views}]},
                },
            )
        )
        await db_session.commit()
        body = (await api.get(_url(project_id))).json()
    name = revision.source_filename
    assert [w["message"] for w in body["warnings"] if w["code"] == "floor_missing"] == [
        f"{name} · лист 4 «План 4 этажа»: плана этажа нет в 3D - последняя конвертация листа "
        "в DXF: needs_review.",
        f"{name} · лист 7: плана этажа нет в 3D - конвертация листа в DXF не запускалась.",
    ]
    assert len(body["floors"]) == 1 and body["service_sheets"] == []


async def test_section_sheet_by_passport_is_a_service_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        revision = await db_session.get(DocumentRevision, uuid.UUID(revision_id))
        assert revision is not None
        db_session.add(
            SheetPassport(
                project_id=uuid.UUID(project_id),
                revision_id=revision.id,
                page_index=0,
                file_name=revision.source_filename,
                sheet_kind="section",
                status="candidate",
            )
        )
        await db_session.commit()
        body = (await api.get(_url(project_id))).json()
    assert body["floors"] == [] and body["groups"] == []
    (service,) = body["service_sheets"]
    assert (service["job_id"], service["page_index"], service["reason"]) == (job_id, 0, "not_plan")
    assert service["message"].endswith("не план этажа: по паспорту листа - разрез.")
