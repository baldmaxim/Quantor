"""Величины через API (закрытие гейтов MANUAL_LENGTH, MANUAL_AREA, PROVENANCE).

Движок расчёта проверен отдельно и на аналитических случаях (`test_quantity_engine.py`).
Здесь проверяется другое: что посчитанное доходит до клиента целиком, с основанием, и не
пересекает границу арендатора.

Страница подобрана так, чтобы ответы были круглыми: 1000×1000 pt при 10 мм/pt — лист ровно
10×10 метров. Ожидания получены из этого, а не из вывода программы.
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
from app.models import Document, PageGeometry, Project, ScaleCalibration, Sheet, Workspace
from app.schemas import MeasurementQuantityRead, SheetQuantitiesRead
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import scale as scale_service
from app.services import takeoff as takeoff_service
from tests.conftest import make_context
from tests.test_performance import count_queries

# Лист 10 × 10 метров: доли страницы переводятся в метры в уме.
PAGE_SIDE = Decimal("1000.0000")
FINGERPRINT = "d" * 64


def _engineer(workspace_id: uuid.UUID) -> AuthContext:
    return make_context(Role.ENGINEER, workspace_id=workspace_id)


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
            display_width_pt=PAGE_SIDE,
            display_height_pt=PAGE_SIDE,
            pdf_rotation=0,
            media_box=[],
            crop_box=[],
            parser_name="pypdf",
            parser_version="6.18.0",
            source_sha256="a" * 64,
            geometry_fingerprint=FINGERPRINT,
            extracted_at=datetime.now(UTC),
        )
    )
    await session.flush()
    return sheet


async def _calibrate(session: AsyncSession, *, sheet: Sheet) -> ScaleCalibration:
    """Калибровка на всю ширину листа: 10 000 мм на 1000 pt — ровно 10 мм/pt."""
    return await scale_service.create_manual(
        session,
        sheet=sheet,
        point_a=(Decimal("0"), Decimal("0.5")),
        point_b=(Decimal("1"), Decimal("0.5")),
        input_value=Decimal("10000"),
        input_unit=LengthUnit.MM,
        created_by=None,
        make_default=True,
    )


class TestQuantitiesReachTheClient:
    async def test_line_across_the_sheet_is_ten_metres(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Известное заранее число: вся ширина листа — 10 метров."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Величины"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        measurement = await takeoff_service.create_measurement(
            db_session,
            item=item,
            sheet=sheet,
            points=[[0.0, 0.5], [1.0, 0.5]],
            calibration=calibration,
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        assert response.status_code == 200
        body = SheetQuantitiesRead.model_validate(response.json())
        assert len(body.measurements) == 1

        quantity = body.measurements[0]
        assert quantity.measurement_id == measurement.id
        assert quantity.state.value == "ready"
        assert quantity.value == Decimal(10)
        assert quantity.unit.value == "m"
        assert quantity.canonical_value == Decimal(10000)
        assert quantity.canonical_unit == "mm"

    async def test_polygon_over_the_whole_sheet_is_a_hundred_square_metres(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Лист 10 × 10 метров — 100 м². Число из геометрии, а не из программы."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Площадь"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Полы", geometry_type=GeometryType.POLYGON
        )
        await takeoff_service.create_measurement(
            db_session,
            item=item,
            sheet=sheet,
            points=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            calibration=calibration,
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        body = SheetQuantitiesRead.model_validate(response.json())
        assert body.measurements[0].value == Decimal(100)
        assert body.measurements[0].unit.value == "m2"

    async def test_provenance_is_complete(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Цепочка объяснения замкнута: измерение → строка → лист → ревизия → геометрия →
        калибровка → правило с версией.

        Величина, которую нельзя объяснить этой цепочкой, показываться не должна (ADR-0008),
        поэтому проверяется каждое звено, а не наличие числа.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Происхождение"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        measurement = await takeoff_service.create_measurement(
            db_session,
            item=item,
            sheet=sheet,
            points=[[0.0, 0.5], [1.0, 0.5]],
            calibration=calibration,
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        body = SheetQuantitiesRead.model_validate(response.json())
        quantity = body.measurements[0]

        assert body.sheet_id == sheet.id
        assert body.revision_id == sheet.revision_id
        assert body.page_geometry_fingerprint == FINGERPRINT
        assert quantity.measurement_id == measurement.id
        assert quantity.takeoff_item_id == item.id
        assert quantity.page_geometry_fingerprint == FINGERPRINT
        assert quantity.scale_calibration_id == calibration.id
        assert quantity.rule_key == "length.v1"
        assert quantity.rule_version == "v1"
        assert len(quantity.input_fingerprint) == 64
        assert quantity.verification_state.value == "unverified"

    async def test_without_scale_the_length_is_unavailable_not_zero(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Ноль — это утверждение о величине, и ложное.

        Строка сметы с нулём выглядит посчитанной; строка с прочерком видна сразу.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Без масштаба"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.0, 0.5], [1.0, 0.5]]
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        body = SheetQuantitiesRead.model_validate(response.json())
        quantity = body.measurements[0]

        assert quantity.state.value == "unavailable_no_scale"
        assert quantity.value is None
        assert quantity.canonical_value is None
        # Правило всё равно названо: известно, чем считали бы, когда масштаб появится.
        assert quantity.rule_key == "length.v1"

    async def test_total_counts_ready_and_reports_the_rest(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Итог складывает готовые, недоступные считает отдельно.

        Итог, в котором половина измерений «стоила ноль», невозможно ни заметить, ни
        объяснить.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Итог"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        # Две линии по 10 метров с масштабом и одна без него.
        for _ in range(2):
            await takeoff_service.create_measurement(
                db_session,
                item=item,
                sheet=sheet,
                points=[[0.0, 0.5], [1.0, 0.5]],
                calibration=calibration,
            )
        await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.0, 0.2], [1.0, 0.2]]
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        body = SheetQuantitiesRead.model_validate(response.json())
        assert len(body.totals) == 1

        total = body.totals[0]
        assert total.takeoff_item_id == item.id
        assert total.value == Decimal(20)
        assert total.measurement_count == 2
        assert total.unavailable_count == 1

    async def test_measurement_keeps_its_own_calibration(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Новая действующая калибровка не переписывает уже посчитанное.

        Молчаливая перепривязка означала бы, что величина, показанная заказчику вчера,
        сегодня другая, и никто этого не заметил (ADR-0018). Это шаг 13 живой приёмки,
        проверенный здесь через API.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Две калибровки"
        )
        sheet = await _sheet(db_session, project=project)
        first = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        await takeoff_service.create_measurement(
            db_session,
            item=item,
            sheet=sheet,
            points=[[0.0, 0.5], [1.0, 0.5]],
            calibration=first,
        )

        # Вторая калибровка вдвое крупнее: та же ширина листа объявлена 20 метрами.
        second = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0"), Decimal("0.5")),
            point_b=(Decimal("1"), Decimal("0.5")),
            input_value=Decimal("20000"),
            input_unit=LengthUnit.MM,
            created_by=None,
            make_default=True,
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        body = SheetQuantitiesRead.model_validate(response.json())
        quantity = body.measurements[0]

        assert quantity.scale_calibration_id == first.id
        assert quantity.scale_calibration_id != second.id
        # Десять метров, а не двадцать: измерение считается по своей калибровке.
        assert quantity.value == Decimal(10)


class TestQuantitiesObeyTheBoundary:
    async def test_foreign_sheet_is_not_found(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """404, а не 403: существование чужого листа тоже сведения."""
        stranger = Workspace(slug="stranger-quantities", name="Чужие")
        db_session.add(stranger)
        await db_session.flush()
        theirs = await projects_service.create_project(
            db_session, workspace_id=stranger.id, name="Чужой"
        )
        foreign_sheet = await _sheet(db_session, project=theirs)
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{foreign_sheet.id}/quantities")

        assert response.status_code == 404

    async def test_viewer_may_read_quantities(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Читатель видит величины: величина без основания непроверяема, а проверять — его
        работа."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Чтение"
        )
        sheet = await _sheet(db_session, project=project)
        await db_session.commit()

        async with build_api(make_context(Role.VIEWER, workspace_id=workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        assert response.status_code == 200


class TestNoQueryGrowth:
    async def test_quantities_do_not_grow_with_measurements(
        self,
        db_session: AsyncSession,
        db_engine: AsyncEngine,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Число запросов не зависит от числа измерений.

        Загружать калибровку на каждое измерение было бы тем самым N+1, который на листе
        с сотней меток превращается в сотню лишних обращений.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Запросы"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            with count_queries(db_engine) as few:
                await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

            await takeoff_service.create_measurements_batch(
                db_session,
                item=item,
                sheet=sheet,
                batch=[[[0.1 + index * 0.001, 0.5]] for index in range(50)],
                calibration=calibration,
            )
            await db_session.commit()

            with count_queries(db_engine) as many:
                await client.get(f"/api/v1/sheets/{sheet.id}/quantities")

        assert len(many) == len(few)


def test_contract_carries_every_link_of_the_chain() -> None:
    """Статическая проверка контракта: происхождение нельзя потерять правкой схемы.

    Идёт без базы намеренно: поле, выпавшее из ответа, обязано ломать сборку у всех, а не
    только там, где поднят PostgreSQL.
    """
    fields = set(MeasurementQuantityRead.model_fields)

    assert {
        "measurement_id",
        "takeoff_item_id",
        "rule_key",
        "rule_version",
        "page_geometry_fingerprint",
        "scale_calibration_id",
        "input_fingerprint",
        "verification_state",
    } <= fields

    # Показ и канон рядом: обратный пересчёт из округлённых метров исходного не даст.
    assert {"value", "unit", "canonical_value", "canonical_unit"} <= fields

    # Лист и ревизия — на уровне ответа: все величины относятся к одной странице.
    assert {"sheet_id", "revision_id"} <= set(SheetQuantitiesRead.model_fields)
