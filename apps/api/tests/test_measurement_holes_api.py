"""Отверстия и недействительный контур через HTTP и базу (промт 05, ADR-0026).

Политика записи: недействительный многоугольник не сохраняется — 422 `GEOMETRY_INVALID` с
уточнением, что и где не так. Строка, попавшая в базу мимо сервиса, получает в величинах
`invalid_geometry`, а не 0 м².
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import MAX_POLYGON_HOLES, GeometryType, LengthUnit
from app.services import projects as projects_service
from app.services import scale as scale_service
from app.services import takeoff as takeoff_service
from tests.test_takeoff_api import _engineer, _sheet

pytestmark = pytest.mark.usefixtures("takeoff_manual_enabled")

OUTER = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
HOLE = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]
BOW_TIE = [[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]


async def _setup(
    session: AsyncSession, workspace_id: uuid.UUID, geometry_type: GeometryType
) -> tuple[uuid.UUID, uuid.UUID]:
    project = await projects_service.create_project(
        session, workspace_id=workspace_id, name=f"Отверстия {uuid.uuid4().hex[:6]}"
    )
    sheet = await _sheet(session, project=project)
    item = await takeoff_service.create_item(
        session, project=project, name="Плита", geometry_type=geometry_type
    )
    await session.commit()
    return sheet.id, item.id


class TestWrite:
    async def test_polygon_with_hole_round_trips(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYGON)

        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={"takeoff_item_id": str(item_id), "points": OUTER, "holes": [HOLE]},
            )
            listed = await client.get(f"/api/v1/sheets/{sheet_id}/measurements")

        assert created.status_code == 201
        assert created.json()["holes"] == [HOLE]
        assert listed.json()[0]["holes"] == [HOLE]

    async def test_polygon_without_holes_reads_empty_list(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYGON)

        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={"takeoff_item_id": str(item_id), "points": OUTER},
            )

        assert created.status_code == 201
        assert created.json()["holes"] == []

    async def test_self_intersection_is_refused_with_issue(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYGON)

        async with build_api(_engineer(workspace_id)) as client:
            refused = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={"takeoff_item_id": str(item_id), "points": BOW_TIE},
            )
            listed = await client.get(f"/api/v1/sheets/{sheet_id}/measurements")

        assert refused.status_code == 422
        detail = refused.json()["detail"]
        assert detail["code"] == "GEOMETRY_INVALID"
        assert detail["issue"]["code"] == "self_intersection"
        assert detail["issue"]["ring"] == 0
        assert listed.json() == []

    async def test_hole_outside_is_refused(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYGON)
        outside = [[0.92, 0.92], [0.99, 0.92], [0.99, 0.99]]

        async with build_api(_engineer(workspace_id)) as client:
            refused = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={"takeoff_item_id": str(item_id), "points": OUTER, "holes": [outside]},
            )

        assert refused.status_code == 422
        assert refused.json()["detail"]["issue"]["code"] == "hole_outside_outer"
        assert refused.json()["detail"]["issue"]["ring"] == 1

    async def test_holes_on_a_line_are_refused(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYLINE)

        async with build_api(_engineer(workspace_id)) as client:
            refused = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={
                    "takeoff_item_id": str(item_id),
                    "points": [[0.1, 0.1], [0.9, 0.1]],
                    "holes": [HOLE],
                },
            )

        assert refused.status_code == 422

    async def test_hole_count_is_bounded(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYGON)

        async with build_api(_engineer(workspace_id)) as client:
            refused = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={
                    "takeoff_item_id": str(item_id),
                    "points": OUTER,
                    "holes": [HOLE] * (MAX_POLYGON_HOLES + 1),
                },
            )

        assert refused.status_code == 422

    async def test_update_keeps_holes_and_checks_them_against_the_new_outline(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet_id, item_id = await _setup(db_session, workspace_id, GeometryType.POLYGON)
        moved = [[0.15, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
        shrunk = [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3]]

        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet_id}/measurements",
                json={"takeoff_item_id": str(item_id), "points": OUTER, "holes": [HOLE]},
            )
            measurement_id = created.json()["id"]
            dragged = await client.patch(
                f"/api/v1/measurements/{measurement_id}",
                json={"points": moved, "version": 1},
            )
            orphaned = await client.patch(
                f"/api/v1/measurements/{measurement_id}",
                json={"points": shrunk, "version": 2},
            )
            cleared = await client.patch(
                f"/api/v1/measurements/{measurement_id}",
                json={"points": shrunk, "holes": [], "version": 2},
            )

        assert dragged.status_code == 200
        assert dragged.json()["holes"] == [HOLE]
        assert orphaned.status_code == 422
        assert orphaned.json()["detail"]["code"] == "GEOMETRY_INVALID"
        assert cleared.status_code == 200
        assert cleared.json()["holes"] == []


class TestQuantities:
    async def test_area_with_holes_and_legacy_invalid_row(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Величины с отверстиями"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Плита", geometry_type=GeometryType.POLYGON
        )
        await takeoff_service.create_measurement(
            db_session,
            item=item,
            sheet=sheet,
            points=OUTER,
            holes=[HOLE],
            calibration=calibration,
        )
        # Строка из времени до политики: самопересечение легло в базу мимо сервиса.
        await db_session.execute(
            text(
                "insert into measurements (id, takeoff_item_id, sheet_id, geometry_type,"
                " points, holes, source, scale_calibration_id, version, measurement_metadata,"
                " created_at, updated_at)"
                " values (gen_random_uuid(), :item, :sheet, 'polygon', cast(:points as jsonb),"
                " '[]'::jsonb, 'manual', :calibration, 1, '{}'::jsonb, now(), now())"
            ),
            {
                "item": item.id,
                "sheet": sheet.id,
                "calibration": calibration.id,
                "points": "[[0.1,0.1],[0.9,0.9],[0.9,0.1],[0.1,0.9]]",
            },
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        assert response.status_code == 200
        body = response.json()
        by_state = {row["state"]: row for row in body["measurements"]}
        assert by_state["ready"]["rule_key"] == "area_with_holes.v1"
        invalid = by_state["invalid_geometry"]
        assert invalid["value"] is None
        assert invalid["geometry_issue"] == "self_intersection"
        total = body["totals"][0]
        assert total["invalid_count"] == 1
        assert total["unavailable_count"] == 1


class TestDatabase:
    @pytest.mark.parametrize(
        ("geometry_type", "points", "holes"),
        [
            ("polyline", "[[0.1,0.1],[0.9,0.1]]", "[[[0.4,0.4],[0.6,0.4],[0.6,0.6]]]"),
            ("polygon", "[[0.1,0.1],[0.9,0.1],[0.9,0.9]]", "[[[0.4,0.4],[0.6,0.4]]]"),
            ("polygon", "[[0.1,0.1],[0.9,0.1],[0.9,0.9]]", "[0.4]"),
            ("polygon", "[[0.1,0.1],[0.9,0.1],[0.9,0.9]]", "{}"),
        ],
    )
    async def test_database_refuses_malformed_holes(
        self,
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        geometry_type: str,
        points: str,
        holes: str,
    ) -> None:
        """CHECK доехал до схемы: отверстия только у многоугольника, кольцо — от трёх точек."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Мимо сервиса"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session,
            project=project,
            name="Фигура",
            geometry_type=GeometryType(geometry_type),
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "insert into measurements (id, takeoff_item_id, sheet_id, geometry_type,"
                    " points, holes, source, version, measurement_metadata, created_at,"
                    " updated_at)"
                    " values (gen_random_uuid(), :item, :sheet, :type,"
                    " cast(:points as jsonb), cast(:holes as jsonb), 'manual', 1, '{}'::jsonb,"
                    " now(), now())"
                ),
                {
                    "item": item.id,
                    "sheet": sheet.id,
                    "type": geometry_type,
                    "points": points,
                    "holes": holes,
                },
            )
        await db_session.rollback()

    async def test_database_accepts_well_formed_holes(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Форма годна"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Плита", geometry_type=GeometryType.POLYGON
        )
        await db_session.flush()

        await db_session.execute(
            text(
                "insert into measurements (id, takeoff_item_id, sheet_id, geometry_type,"
                " points, holes, source, version, measurement_metadata, created_at, updated_at)"
                " values (gen_random_uuid(), :item, :sheet, 'polygon',"
                " '[[0.1,0.1],[0.9,0.1],[0.9,0.9]]'::jsonb,"
                " '[[[0.5,0.3],[0.8,0.3],[0.8,0.6]]]'::jsonb, 'manual', 1, '{}'::jsonb,"
                " now(), now())"
            ),
            {"item": item.id, "sheet": sheet.id},
        )
        await db_session.rollback()
