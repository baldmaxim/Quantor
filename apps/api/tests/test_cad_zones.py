"""Зоны листа во вкладке CAD: CRUD, величины по калибровке, границы доступа и валидация."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CadZone, ScaleCalibration, Workspace
from tests.conftest import make_context
from tests.test_cad_qa import (
    A3_HEIGHT,
    A3_WIDTH,
    BROKEN_PDF,
    _upload,
    _upload_calibrated,
    cad_settings,
)

# Прямоугольник 0,2 x 0,3 листа.
RECT = [[0.1, 0.2], [0.3, 0.2], [0.3, 0.5], [0.1, 0.5]]
BOW_TIE = [[0.1, 0.1], [0.4, 0.4], [0.4, 0.1], [0.1, 0.4]]


def _room(revision_id: str, **patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "revision_id": revision_id,
        "page_index": 0,
        "kind": "room_apartment",
        "apartment_no": "0042",
        "room_mark": "3-1/6",
        "points": RECT,
    }
    body.update(patch)
    return body


def _door(revision_id: str, **patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "revision_id": revision_id,
        "page_index": 0,
        "kind": "door",
        "points": [[0.1, 0.5], [0.2, 0.5]],
        "door_height_mm": 2100,
    }
    body.update(patch)
    return body


async def _factor(db_session: AsyncSession) -> float:
    calibration = (await db_session.scalars(select(ScaleCalibration))).one()
    return float(calibration.mm_per_pt)


async def test_crud_and_server_side_measures(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/zones"
        factor = await _factor(db_session)
        width_pt, height_pt = float(A3_WIDTH), float(A3_HEIGHT)

        assert (await api.get(f"{url}?revision_id={revision_id}")).json() == []

        created = await api.post(url, json=_room(revision_id))
        assert created.status_code == 201, created.text
        room = created.json()
        assert (room["kind"], room["apartment_no"], room["room_mark"]) == (
            "room_apartment",
            "0042",
            "3-1/6",
        )
        assert room["calibration_missing"] is False and room["geometry_issue"] is None
        # Независимый пересчёт: стороны 0,2 и 0,3 листа в мм, затем в м и м².
        side_x = 0.2 * width_pt * factor
        side_y = 0.3 * height_pt * factor
        assert room["area_m2"] == pytest.approx(side_x * side_y / 1e6)
        assert room["perimeter_m"] == pytest.approx(2 * (side_x + side_y) / 1e3)
        assert room["width_m"] is None

        door = (await api.post(url, json=_door(revision_id))).json()
        assert door["width_m"] == pytest.approx(0.1 * width_pt * factor / 1e3)
        assert door["area_m2"] is None and door["perimeter_m"] is None
        assert door["door_height_mm"] == 2100

        mop = await api.post(url, json=_room(revision_id, kind="room_mop", apartment_no=None))
        assert mop.status_code == 201, mop.text

        listed = (await api.get(f"{url}?revision_id={revision_id}&page_index=0")).json()
        assert len(listed) == 3
        assert (await api.get(f"{url}?revision_id={revision_id}&page_index=1")).json() == []

        renamed = await api.patch(
            f"/api/v1/cad/zones/{room['id']}", json={"name": "Кухня", "room_mark": None}
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == "Кухня" and renamed.json()["room_mark"] is None
        assert renamed.json()["apartment_no"] == "0042"
        assert renamed.json()["area_m2"] == room["area_m2"]

        moved = await api.patch(
            f"/api/v1/cad/zones/{room['id']}",
            json={"points": [[0.1, 0.2], [0.5, 0.2], [0.5, 0.5], [0.1, 0.5]]},
        )
        assert moved.json()["area_m2"] == pytest.approx(2 * room["area_m2"])

        # Смена вида сбрасывает № квартиры: МОП его не имеет.
        switched = await api.patch(f"/api/v1/cad/zones/{room['id']}", json={"kind": "room_mop"})
        assert switched.status_code == 200 and switched.json()["apartment_no"] is None

        assert (await api.delete(f"/api/v1/cad/zones/{room['id']}")).status_code == 204
        assert (await api.delete(f"/api/v1/cad/zones/{room['id']}")).status_code == 404
        count = await db_session.scalar(select(func.count()).select_from(CadZone))
        assert count == 2
        stored = (await db_session.scalars(select(CadZone).where(CadZone.kind == "door"))).one()
        assert stored.created_by is not None and stored.points == [[0.1, 0.5], [0.2, 0.5]]


async def test_without_calibration_values_are_null_not_zero(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/zones"
        for body in (_room(revision_id), _door(revision_id)):
            created = await api.post(url, json=body)
            assert created.status_code == 201, created.text
            zone = created.json()
            assert zone["calibration_missing"] is True
            assert zone["area_m2"] is None and zone["perimeter_m"] is None
            assert zone["width_m"] is None


async def test_validation_by_kind(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/zones"
        bad: list[dict[str, Any]] = [
            _room(revision_id, points=[[0.1, 0.1], [0.4, 0.4]]),  # помещение из двух точек
            _room(revision_id, points=BOW_TIE),  # самопересечение
            _room(revision_id, apartment_no=None),  # квартира без номера
            _room(revision_id, apartment_no="  "),
            _room(revision_id, kind="room_mop", apartment_no="1"),  # МОП с номером квартиры
            _room(revision_id, door_height_mm=2100),  # высота не двери
            _room(revision_id, points=[[0.1, 0.1], [1.5, 0.4], [0.4, 0.9]]),  # вне листа
            _door(revision_id, door_height_mm=None),  # дверь без высоты
            _door(revision_id, door_height_mm=1000),
            _door(revision_id, door_height_mm=4000),
            _door(revision_id, points=[[0.1, 0.5], [0.2, 0.5], [0.3, 0.5]]),  # три точки
            _door(revision_id, points=[[0.1, 0.5], [0.1, 0.5]]),  # нулевая длина
            _door(revision_id, apartment_no="1"),
            _room(revision_id, kind="window"),
            _room(revision_id, page_index=-1),
        ]
        for body in bad:
            response = await api.post(url, json=body)
            assert response.status_code == 422, (body, response.text)
        assert (await api.post(url, json=_room(revision_id, points=BOW_TIE))).json()["detail"][
            "code"
        ] == "GEOMETRY_INVALID"
        assert await db_session.scalar(select(func.count()).select_from(CadZone)) == 0

        # Правка тоже проверяется целиком.
        room = (await api.post(url, json=_room(revision_id))).json()
        for patch in ({"points": BOW_TIE}, {"apartment_no": None}, {"kind": "door"}):
            response = await api.patch(f"/api/v1/cad/zones/{room['id']}", json=patch)
            assert response.status_code == 422, (patch, response.text)


async def test_flag_off_closes_every_zone_route(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        zone = (
            await api.post(f"/api/v1/projects/{project_id}/cad/zones", json=_room(revision_id))
        ).json()
    async with build_api(make_context(), settings=cad_settings(tmp_path, flag=False)) as api:
        url = f"/api/v1/projects/{project_id}/cad/zones"
        calls = [
            await api.get(f"{url}?revision_id={revision_id}"),
            await api.post(url, json=_room(revision_id)),
            await api.patch(f"/api/v1/cad/zones/{zone['id']}", json={"name": "x"}),
            await api.delete(f"/api/v1/cad/zones/{zone['id']}"),
        ]
        for response in calls:
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"
    assert await db_session.scalar(select(func.count()).select_from(CadZone)) == 1


async def test_foreign_workspace_and_wrong_revision_get_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/zones"
        zone = (await api.post(url, json=_room(revision_id))).json()
        # Ревизия другого проекта своего пространства.
        _, other_revision = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        assert (await api.get(f"{url}?revision_id={other_revision}")).status_code == 404
        assert (await api.post(url, json=_room(other_revision))).status_code == 404
        assert (await api.get(f"{url}?revision_id={uuid.uuid4()}")).status_code == 404

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(f"{url}?revision_id={revision_id}")).status_code == 404
        assert (await foreign.post(url, json=_room(revision_id))).status_code == 404
        zone_url = f"/api/v1/cad/zones/{zone['id']}"
        assert (await foreign.patch(zone_url, json={"name": "чужая"})).status_code == 404
        assert (await foreign.delete(zone_url)).status_code == 404
    stored = (await db_session.scalars(select(CadZone))).one()
    assert stored.name is None
