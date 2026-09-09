"""API ручного обмера (промт 08).

Проверяется наблюдаемое поведение через HTTP: границы арендатора, злонамеренные сочетания
идентификаторов, конфликт версий, предел пакета и отсутствие обхода по строкам.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth.context import AuthContext
from app.domain import (
    DocumentKind,
    GeometryStatus,
    GeometryType,
    LengthUnit,
    ProcessingStatus,
    Role,
)
from app.models import Document, PageGeometry, Project, Sheet, Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import scale as scale_service
from app.services import takeoff as takeoff_service
from tests.conftest import make_context
from tests.test_performance import count_queries

A1_WIDTH = Decimal("2384.0000")
A1_HEIGHT = Decimal("1684.0000")


async def _sheet(session: AsyncSession, *, project: Project) -> Sheet:
    document = Document(
        project_id=project.id, display_name="План.pdf", document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()

    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=uuid.uuid4(),
        source_filename="План.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256="a" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY,
    )
    sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1", rotation=0)
    session.add(sheet)
    await session.flush()

    session.add(
        PageGeometry(
            sheet_id=sheet.id,
            display_width_pt=A1_WIDTH,
            display_height_pt=A1_HEIGHT,
            pdf_rotation=0,
            media_box=[],
            crop_box=[],
            parser_name="pypdf",
            parser_version="6.18.0",
            source_sha256="a" * 64,
            geometry_fingerprint="b" * 64,
            extracted_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return sheet


def _engineer(workspace_id: uuid.UUID) -> AuthContext:
    return make_context(Role.ENGINEER, workspace_id=workspace_id)


class TestItemsApi:
    async def test_create_and_list(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Через API"
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/projects/{project.id}/takeoff-items",
                json={"name": "Двери", "geometry_type": "count"},
            )
            listed = await client.get(f"/api/v1/projects/{project.id}/takeoff-items")

        assert created.status_code == 201
        # Единица выводится сервером, а не приходит от клиента.
        assert created.json()["display_unit"] == "pcs"
        assert [row["name"] for row in listed.json()] == ["Двери"]

    async def test_archived_item_leaves_the_default_list(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Архивация"
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Старая", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            archived = await client.post(f"/api/v1/takeoff-items/{item.id}/archive")
            active = await client.get(f"/api/v1/projects/{project.id}/takeoff-items")
            everything = await client.get(
                f"/api/v1/projects/{project.id}/takeoff-items",
                params={"include_archived": True},
            )

        assert archived.status_code == 200
        assert active.json() == []
        assert len(everything.json()) == 1

    async def test_geometry_type_cannot_be_changed(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Сменить тип у строки с измерениями значило бы объявить точки площадями."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Тип"
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.patch(
                f"/api/v1/takeoff-items/{item.id}",
                json={"name": "Двери", "geometry_type": "polygon"},
            )

        assert response.status_code == 200
        # Поле просто не входит в контракт: тип остался прежним.
        assert response.json()["geometry_type"] == "count"
        assert response.json()["display_unit"] == "pcs"


class TestMeasurementsApi:
    async def test_create_and_list_for_sheet(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Измерения"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={"takeoff_item_id": str(item.id), "points": [[0.1, 0.1], [0.9, 0.1]]},
            )
            listed = await client.get(f"/api/v1/sheets/{sheet.id}/measurements")

        assert created.status_code == 201
        assert created.json()["source"] == "manual"
        assert created.json()["version"] == 1
        assert len(listed.json()) == 1

    async def test_default_calibration_is_attached(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Действующая калибровка листа — умолчание, а не обязательство."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="С масштабом"
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
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={"takeoff_item_id": str(item.id), "points": [[0.1, 0.1], [0.9, 0.1]]},
            )

        assert created.json()["scale_calibration_id"] == str(calibration.id)

    async def test_batch_is_atomic(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Одна негодная геометрия отменяет весь пакет.

        Частичный результат заставил бы клиента выяснять, какие из меток сохранились, —
        а он их уже нарисовал.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Пакет"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            broken = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements/batch",
                json={
                    "takeoff_item_id": str(item.id),
                    # Третья точка вне листа: пакет обязан отмениться целиком.
                    "items": [[[0.1, 0.1]], [[0.2, 0.2]], [[5.0, 0.3]]],
                },
            )
            listed = await client.get(f"/api/v1/sheets/{sheet.id}/measurements")

        assert broken.status_code == 422
        assert listed.json() == []

    async def test_batch_creates_everything_at_once(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Счёт"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        points = [[[0.1 + index * 0.01, 0.5]] for index in range(10)]
        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements/batch",
                json={"takeoff_item_id": str(item.id), "items": points},
            )

        assert created.status_code == 201
        assert len(created.json()) == 10

    async def test_batch_size_is_bounded(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Пакет без предела — способ положить сервер, а не удобство."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Предел"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        oversized = [[[0.5, 0.5]]] * (takeoff_service.MAX_BATCH_SIZE + 1)
        async with build_api(_engineer(workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements/batch",
                json={"takeoff_item_id": str(item.id), "items": oversized},
            )

        assert response.status_code == 422

    async def test_stale_version_is_refused(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Клиент, открывший лист десять минут назад, не перетирает чужую правку молча."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Версии"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        measurement = await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.1, 0.1], [0.9, 0.1]]
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            first = await client.patch(
                f"/api/v1/measurements/{measurement.id}",
                json={"points": [[0.2, 0.2], [0.8, 0.2]], "version": 1},
            )
            stale = await client.patch(
                f"/api/v1/measurements/{measurement.id}",
                json={"points": [[0.3, 0.3], [0.7, 0.3]], "version": 1},
            )

        assert first.status_code == 200
        assert first.json()["version"] == 2
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "MEASUREMENT_VERSION_CONFLICT"

    async def test_delete_is_soft(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Удаление"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        measurement = await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.5, 0.5]]
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            deleted = await client.delete(f"/api/v1/measurements/{measurement.id}")
            listed = await client.get(f"/api/v1/sheets/{sheet.id}/measurements")
            again = await client.delete(f"/api/v1/measurements/{measurement.id}")

        assert deleted.status_code == 204
        assert listed.json() == []
        # Повторное удаление — уже не найдено: удалённое из чтений исчезло.
        assert again.status_code == 404


class TestMaliciousCombinations:
    """Злонамеренные сочетания идентификаторов."""

    async def test_item_from_another_project(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Строка проекта A на листе проекта B сложила бы чужие объёмы в свой итог."""
        first = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Проект A"
        )
        second = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Проект B"
        )
        sheet = await _sheet(db_session, project=second)
        item = await takeoff_service.create_item(
            db_session, project=first, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={"takeoff_item_id": str(item.id), "points": [[0.5, 0.5]]},
            )

        assert response.status_code == 422

    async def test_calibration_from_another_sheet(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Чужая калибровка"
        )
        target = await _sheet(db_session, project=project)
        other = await _sheet(db_session, project=project)
        calibration = await scale_service.create_manual(
            db_session,
            sheet=other,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{target.id}/measurements",
                json={
                    "takeoff_item_id": str(item.id),
                    "points": [[0.1, 0.1], [0.9, 0.1]],
                    "scale_calibration_id": str(calibration.id),
                },
            )

        assert response.status_code == 422

    async def test_foreign_workspace_measurement_is_not_found(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        theirs = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Соседский"
        )
        sheet = await _sheet(db_session, project=theirs)
        item = await takeoff_service.create_item(
            db_session, project=theirs, name="Их двери", geometry_type=GeometryType.COUNT
        )
        measurement = await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.5, 0.5]]
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            read = await client.patch(
                f"/api/v1/measurements/{measurement.id}",
                json={"points": [[0.4, 0.4]], "version": 1},
            )
            listed = await client.get(f"/api/v1/sheets/{sheet.id}/measurements")

        # 404, а не 403: 403 подтвердил бы существование объекта.
        assert read.status_code == 404
        assert listed.status_code == 404

    async def test_archived_item_refuses_measurements(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Архив"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Убрана", geometry_type=GeometryType.COUNT
        )
        await takeoff_service.archive_item(db_session, item=item)
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={"takeoff_item_id": str(item.id), "points": [[0.5, 0.5]]},
            )

        assert response.status_code == 422

    async def test_source_cannot_be_forged(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """`source=ai` через ручной эндпоинт выдал бы обмер за проверенный автоматикой."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Подделка источника"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={
                    "takeoff_item_id": str(item.id),
                    "points": [[0.5, 0.5]],
                    "source": "ai",
                },
            )

        assert response.status_code == 201
        assert response.json()["source"] == "manual"

    async def test_viewer_cannot_write(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Только чтение"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(make_context(Role.VIEWER, workspace_id=workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={"takeoff_item_id": str(item.id), "points": [[0.5, 0.5]]},
            )
            listed = await client.get(f"/api/v1/sheets/{sheet.id}/measurements")

        assert created.status_code == 403
        assert listed.status_code == 200


class TestNoQueryGrowth:
    async def test_measurement_list_does_not_grow_with_rows(
        self,
        db_session: AsyncSession,
        db_engine: AsyncEngine,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Число запросов не растёт вместе с числом измерений на листе."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Без обхода"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        for index in range(3):
            await takeoff_service.create_measurement(
                db_session, item=item, sheet=sheet, points=[[0.1 + index * 0.01, 0.5]]
            )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            with count_queries(db_engine) as few:
                await client.get(f"/api/v1/sheets/{sheet.id}/measurements")

            for index in range(20):
                await takeoff_service.create_measurement(
                    db_session, item=item, sheet=sheet, points=[[0.3 + index * 0.01, 0.5]]
                )
            await db_session.commit()

            with count_queries(db_engine) as many:
                response = await client.get(f"/api/v1/sheets/{sheet.id}/measurements")

        assert len(response.json()) == 23
        assert len(many) == len(few), (
            f"на 23 измерениях {len(many)} запросов против {len(few)} на трёх — "
            "появился обход по строкам"
        )
