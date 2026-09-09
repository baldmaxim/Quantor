"""Строки обмера и измерения (ADR-0019).

Проверяется разделение обязанностей: база держит форму данных, сервис — согласованность
между таблицами. Часть тестов бьёт по базе напрямую сырым SQL — иначе неизвестно, доехал
ли CHECK до схемы или остался намерением в модели.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    MAX_MEASUREMENT_POINTS,
    UNIT_BY_GEOMETRY,
    DocumentKind,
    GeometryStatus,
    GeometryType,
    LengthUnit,
    MeasurementSource,
    ProcessingStatus,
    QuantityUnit,
)
from app.errors import DomainError, ErrorCode
from app.models import Document, Measurement, PageGeometry, Project, Sheet, TakeoffItem, Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import scale as scale_service
from app.services import takeoff as takeoff_service

A1_WIDTH = Decimal("2384.0000")
A1_HEIGHT = Decimal("1684.0000")
FINGERPRINT = "e" * 64


async def _sheet(session: AsyncSession, *, project: Project, with_geometry: bool = True) -> Sheet:
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
        source_sha256="f" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY,
    )
    sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1", rotation=0)
    session.add(sheet)
    await session.flush()

    if with_geometry:
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
                source_sha256="f" * 64,
                geometry_fingerprint=FINGERPRINT,
                extracted_at=datetime.now(UTC),
            )
        )
        await session.flush()

    return sheet


class TestPointValidation:
    """Форма геометрии. Без базы: это чистая проверка."""

    @pytest.mark.parametrize(
        ("geometry_type", "count", "ok"),
        [
            (GeometryType.COUNT, 1, True),
            (GeometryType.COUNT, 2, False),
            (GeometryType.COUNT, 0, False),
            (GeometryType.LINE, 2, True),
            (GeometryType.LINE, 3, False),
            (GeometryType.POLYLINE, 2, True),
            (GeometryType.POLYLINE, 5, True),
            (GeometryType.POLYLINE, 1, False),
            (GeometryType.POLYGON, 3, True),
            (GeometryType.POLYGON, 8, True),
            (GeometryType.POLYGON, 2, False),
        ],
    )
    def test_point_count_matches_type(
        self, geometry_type: GeometryType, count: int, ok: bool
    ) -> None:
        """Многоугольник из двух точек не имеет площади."""
        points = [[0.1 * index, 0.2] for index in range(count)]

        if ok:
            assert len(takeoff_service.validate_points(geometry_type, points)) == count
        else:
            with pytest.raises(DomainError):
                takeoff_service.validate_points(geometry_type, points)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_coordinate_is_refused(self, bad: float) -> None:
        """NaN прошёл бы JSON и превратил любую величину по этой геометрии в бессмыслицу."""
        with pytest.raises(DomainError):
            takeoff_service.validate_points(GeometryType.LINE, [[bad, 0.5], [0.5, 0.5]])

    @pytest.mark.parametrize("bad", [-0.001, 1.001])
    def test_point_outside_the_sheet_is_refused(self, bad: float) -> None:
        with pytest.raises(DomainError):
            takeoff_service.validate_points(GeometryType.LINE, [[bad, 0.5], [0.5, 0.5]])

    def test_sheet_corners_are_allowed(self) -> None:
        """Обмер по краю чертежа — обычное дело."""
        points = takeoff_service.validate_points(GeometryType.LINE, [[0.0, 0.0], [1.0, 1.0]])

        assert points == [[0.0, 0.0], [1.0, 1.0]]

    def test_polygon_is_not_closed_by_repeating_the_first_point(self) -> None:
        """Замыкание — свойство типа, а не данных: дублирующая точка ломала бы счёт вершин."""
        source = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]

        points = takeoff_service.validate_points(GeometryType.POLYGON, source)

        assert points == source
        assert len(points) == 3

    def test_point_order_is_preserved(self) -> None:
        """Порядок — это то, что пользователь видит и может отредактировать."""
        source = [[0.9, 0.9], [0.1, 0.1], [0.5, 0.2]]

        assert takeoff_service.validate_points(GeometryType.POLYGON, source) == source

    def test_too_many_vertices_are_refused(self) -> None:
        """Многоугольник из ста тысяч точек — способ положить сервер одним запросом."""
        points = [[0.5, 0.5]] * (MAX_MEASUREMENT_POINTS + 1)

        with pytest.raises(DomainError):
            takeoff_service.validate_points(GeometryType.POLYGON, points)

    def test_malformed_point_is_refused(self) -> None:
        with pytest.raises(DomainError):
            takeoff_service.validate_points(GeometryType.LINE, [[0.5], [0.5, 0.5]])


def test_unit_is_derived_from_geometry_type() -> None:
    """Единица не задаётся снаружи: свободное поле показало бы площадь в метрах."""
    assert UNIT_BY_GEOMETRY[GeometryType.COUNT] is QuantityUnit.PCS
    assert UNIT_BY_GEOMETRY[GeometryType.LINE] is QuantityUnit.M
    assert UNIT_BY_GEOMETRY[GeometryType.POLYLINE] is QuantityUnit.M
    assert UNIT_BY_GEOMETRY[GeometryType.POLYGON] is QuantityUnit.M2


def test_region_is_not_a_measurement() -> None:
    """Три понятия остаются разными сущностями (ADR-0008)."""
    from app.models import Region

    assert not hasattr(Region, "takeoff_item_id")
    assert not hasattr(Region, "version")
    assert not hasattr(Measurement, "external_block_id")
    assert Measurement.__tablename__ != Region.__tablename__


class TestItems:
    async def test_created_item_derives_its_unit(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Обмеры"
        )

        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )

        assert item.display_unit is QuantityUnit.PCS
        assert item.archived_at is None

    async def test_items_get_sequential_order(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Порядок"
        )

        first = await takeoff_service.create_item(
            db_session, project=project, name="Первая", geometry_type=GeometryType.COUNT
        )
        second = await takeoff_service.create_item(
            db_session, project=project, name="Вторая", geometry_type=GeometryType.LINE
        )

        assert second.ordinal == first.ordinal + 1

    async def test_blank_name_is_refused(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Пустое имя"
        )

        with pytest.raises(DomainError):
            await takeoff_service.create_item(
                db_session, project=project, name="   ", geometry_type=GeometryType.COUNT
            )

    async def test_archived_item_disappears_from_the_list(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Архивация, а не удаление: строка остаётся объяснением посчитанных чисел."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Архив"
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Старая", geometry_type=GeometryType.COUNT
        )

        await takeoff_service.archive_item(db_session, item=item)

        active = await takeoff_service.list_items(
            db_session, workspace_id=workspace_id, project_id=project.id
        )
        everything = await takeoff_service.list_items(
            db_session, workspace_id=workspace_id, project_id=project.id, include_archived=True
        )

        assert active == []
        assert [row.id for row in everything] == [item.id]

    async def test_database_refuses_unit_that_contradicts_the_type(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """CHECK доехал до схемы, а не остался намерением в модели."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Мимо сервиса"
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "insert into takeoff_items (id, project_id, name, geometry_type,"
                    " display_unit, color_key, ordinal, created_at, updated_at)"
                    " values (gen_random_uuid(), :p, 'Площадь в метрах', 'polygon',"
                    " 'm', 'accent', 0, now(), now())"
                ),
                {"p": project.id},
            )
        await db_session.rollback()


class TestMeasurements:
    async def test_created_measurement_is_manual(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Источник не выбирается: подмена выдала бы ручной обмер за проверенный автоматикой."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Измерение"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )

        measurement = await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.1, 0.1], [0.9, 0.1]]
        )

        assert measurement.source is MeasurementSource.MANUAL
        assert measurement.geometry_type is GeometryType.LINE
        assert measurement.version == 1
        assert measurement.deleted_at is None

    async def test_archived_item_refuses_new_measurements(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Архивная строка"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Убрана", geometry_type=GeometryType.COUNT
        )
        await takeoff_service.archive_item(db_session, item=item)

        with pytest.raises(DomainError):
            await takeoff_service.create_measurement(
                db_session, item=item, sheet=sheet, points=[[0.5, 0.5]]
            )

    async def test_item_and_sheet_must_share_the_project(
        self,
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        """Строка и лист из разных проектов сложили бы чужие объёмы в свой итог."""
        mine = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Мой"
        )
        theirs = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Чужой"
        )
        foreign_sheet = await _sheet(db_session, project=theirs)
        item = await takeoff_service.create_item(
            db_session, project=mine, name="Двери", geometry_type=GeometryType.COUNT
        )

        with pytest.raises(DomainError):
            await takeoff_service.create_measurement(
                db_session, item=item, sheet=foreign_sheet, points=[[0.5, 0.5]]
            )

    async def test_calibration_must_belong_to_the_same_sheet(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Чужая калибровка"
        )
        first = await _sheet(db_session, project=project)
        second = await _sheet(db_session, project=project)
        calibration = await scale_service.create_manual(
            db_session,
            sheet=second,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )

        with pytest.raises(DomainError):
            await takeoff_service.create_measurement(
                db_session,
                item=item,
                sheet=first,
                points=[[0.1, 0.1], [0.9, 0.1]],
                calibration=calibration,
            )

    async def test_measurement_keeps_its_own_calibration(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Смена действующего масштаба не меняет уже посчитанное (ADR-0018)."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Своя калибровка"
        )
        sheet = await _sheet(db_session, project=project)
        first = await scale_service.create_manual(
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
        measurement = await takeoff_service.create_measurement(
            db_session,
            item=item,
            sheet=sheet,
            points=[[0.1, 0.1], [0.9, 0.1]],
            calibration=first,
        )

        # Появилась новая действующая калибровка листа.
        await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6200"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        await db_session.flush()

        assert measurement.scale_calibration_id == first.id

    async def test_version_conflict_is_explicit(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Двое, тянущие одну вершину, получают конфликт, а не молчаливую перезапись."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Конфликт"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        measurement = await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.1, 0.1], [0.9, 0.1]]
        )

        await takeoff_service.update_geometry(
            db_session,
            measurement=measurement,
            points=[[0.2, 0.2], [0.8, 0.2]],
            expected_version=1,
        )
        assert measurement.version == 2

        with pytest.raises(DomainError) as error:
            await takeoff_service.update_geometry(
                db_session,
                measurement=measurement,
                points=[[0.3, 0.3], [0.7, 0.3]],
                expected_version=1,
            )

        assert error.value.code is ErrorCode.MEASUREMENT_VERSION_CONFLICT

    async def test_soft_deleted_measurement_disappears_from_reads(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Мягкое удаление: строка остаётся объяснением вчерашнего числа."""
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

        await takeoff_service.soft_delete(db_session, measurement=measurement)

        visible = await takeoff_service.list_for_sheet(
            db_session, workspace_id=workspace_id, sheet_id=sheet.id
        )
        found = await takeoff_service.get_measurement(
            db_session, workspace_id=workspace_id, measurement_id=measurement.id
        )

        assert visible == []
        assert found is None
        # Запись на месте: удалена мягко.
        assert await db_session.get(Measurement, measurement.id) is not None

    async def test_database_refuses_a_polygon_of_two_points(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Проверка в приложении ловит ошибку пользователя, проверка в базе — программиста."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Мимо сервиса"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Пол", geometry_type=GeometryType.POLYGON
        )
        await db_session.flush()

        with pytest.raises(IntegrityError):
            await db_session.execute(
                text(
                    "insert into measurements (id, takeoff_item_id, sheet_id, geometry_type,"
                    " points, source, version, measurement_metadata, created_at, updated_at)"
                    " values (gen_random_uuid(), :item, :sheet, 'polygon',"
                    " '[[0,0],[1,1]]'::jsonb, 'manual', 1, '{}'::jsonb, now(), now())"
                ),
                {"item": item.id, "sheet": sheet.id},
            )
        await db_session.rollback()


class TestScopeAndIsolation:
    async def test_total_requires_an_explicit_scope(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Сложить две ревизии значило бы посчитать одни и те же двери дважды."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Область"
        )
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )

        with pytest.raises(DomainError):
            await takeoff_service.count_for_item(
                db_session, workspace_id=workspace_id, item_id=item.id
            )

    async def test_total_counts_only_the_named_sheet(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Два листа"
        )
        first = await _sheet(db_session, project=project)
        second = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await takeoff_service.create_measurement(
            db_session, item=item, sheet=first, points=[[0.2, 0.2]]
        )
        await takeoff_service.create_measurement(
            db_session, item=item, sheet=second, points=[[0.3, 0.3]]
        )

        only_first = await takeoff_service.count_for_item(
            db_session, workspace_id=workspace_id, item_id=item.id, sheet_id=first.id
        )

        assert only_first == 1

    async def test_foreign_item_is_not_found(
        self,
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        theirs = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Соседский"
        )
        item = await takeoff_service.create_item(
            db_session, project=theirs, name="Их двери", geometry_type=GeometryType.COUNT
        )

        found = await takeoff_service.get_item(
            db_session, workspace_id=workspace_id, item_id=item.id
        )

        assert found is None

    async def test_foreign_measurement_is_not_found(
        self,
        db_session: AsyncSession,
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

        found = await takeoff_service.get_measurement(
            db_session, workspace_id=workspace_id, measurement_id=measurement.id
        )

        assert found is None


def test_takeoff_item_has_no_hierarchy() -> None:
    """Дерева нет намеренно: придуманная иерархия на данных без единого измерения."""
    assert not hasattr(TakeoffItem, "parent_id")
    assert not hasattr(TakeoffItem, "children")
