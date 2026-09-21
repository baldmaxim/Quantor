"""Выгрузка обмера листа в CSV.

Проверяется не формат ради формата, а два свойства: выгрузка совпадает с тем, что считает
движок величин, и объясняет каждое число. Отчёт, который нельзя сверить с экраном, в смете
бесполезен.

Страница та же, что в `test_quantity_api`: 1000×1000 pt при 10 мм/pt — лист ровно
10 × 10 метров, и ожидания берутся из геометрии, а не из вывода программы.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import scale as scale_service
from app.services import takeoff as takeoff_service
from tests.conftest import make_context

PAGE_SIDE = Decimal("1000.0000")
FINGERPRINT = "d" * 64
EXPORT = "/api/v1/sheets/{sheet_id}/takeoff-export.csv"


def _engineer(workspace_id: uuid.UUID) -> AuthContext:
    return make_context(Role.ENGINEER, workspace_id=workspace_id)


async def _sheet(session: AsyncSession, *, project: Project, label: str = "1") -> Sheet:
    document = Document(
        project_id=project.id, display_name="План 3 этажа.pdf", document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()

    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=uuid.uuid4(),
        source_filename="План 3 этажа.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256="a" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        # Обычный PDF: распознавания не было и не будет, а выгрузка обязана работать.
        processing_status=ProcessingStatus.UNPROCESSED,
        geometry_status=GeometryStatus.READY,
    )
    sheet = Sheet(revision_id=revision.id, page_index=0, page_label=label, rotation=0)
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
    """10 000 мм на всю ширину листа в 1000 pt — ровно 10 мм/pt."""
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


def _number(cell: str) -> Decimal:
    """Число из ячейки. Запятая — разделитель дробной части, а не потеря точности."""
    return Decimal(cell.replace(",", "."))


def _rows(body: str) -> list[dict[str, str]]:
    assert body.startswith("﻿"), "без метки Excel откроет кириллицу как мусор"
    return list(csv.DictReader(io.StringIO(body[1:]), delimiter=";"))


@pytest.mark.usefixtures("takeoff_manual_enabled")
class TestExport:
    async def test_export_repeats_the_numbers_of_the_engine(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Линия во всю ширину — 10 метров, и ровно это должно быть в файле."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Выгрузка"
        )
        sheet = await _sheet(db_session, project=project)
        calibration = await _calibrate(db_session, sheet=sheet)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены; перегородки", geometry_type=GeometryType.LINE
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
            response = await client.get(EXPORT.format(sheet_id=sheet.id))

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]

        rows = _rows(response.text)
        assert len(rows) == 1
        row = rows[0]

        # Запятая в дробной части — соглашение русского Excel; значение при этом не
        # округляется, поэтому сверяется само число, а не его запись.
        assert "," in row["Величина"]
        assert _number(row["Величина"]) == Decimal(10)
        assert row["Единица"] == "м"
        assert _number(row["Каноническая величина"]) == Decimal(10000)
        assert row["Каноническая единица"] == "mm"
        assert row["Состояние"] == "Посчитано"
        assert row["Код состояния"] == "ready"
        # Название с точкой с запятой не должно разорвать строку на два столбца.
        assert row["Строка обмера"] == "Стены; перегородки"
        assert row["Идентификатор измерения"] == str(measurement.id)
        assert row["Тип геометрии"] == "Линия"

    async def test_export_explains_every_number(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Цепочка прослеживаемости замкнута: проект → документ → ревизия → лист →
        строка → измерение → величина с правилом и калибровкой."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Происхождение"
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
            row = _rows((await client.get(EXPORT.format(sheet_id=sheet.id))).text)[0]

        assert row["Проект"] == "Происхождение"
        assert row["Документ"] == "План 3 этажа.pdf"
        assert row["Ревизия"] == "План 3 этажа.pdf"
        assert row["Идентификатор ревизии"] == str(sheet.revision_id)
        assert row["Лист"] == "1"
        assert row["Правило"] == "area.v1"
        assert row["Версия правила"] == "v1"
        assert row["Идентификатор калибровки"] == str(calibration.id)
        assert row["Отпечаток геометрии страницы"] == FINGERPRINT
        assert row["Отпечаток входа"] != ""
        # Лист 10 × 10 метров.
        assert _number(row["Величина"]) == Decimal(100)

    async def test_measurement_without_scale_is_not_a_zero(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Ноль в отчёте выглядит посчитанным. Пустая величина с причиной — нет."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Без масштаба"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.LINE
        )
        await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.0, 0.5], [1.0, 0.5]], calibration=None
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            row = _rows((await client.get(EXPORT.format(sheet_id=sheet.id))).text)[0]

        assert row["Величина"] == ""
        assert row["Код состояния"] == "unavailable_no_scale"
        assert row["Состояние"] == "Нет масштаба"
        assert row["Без масштаба"] == "1"

    async def test_count_needs_no_scale(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Счёт — это штуки: масштаб для него не нужен ни на экране, ни в файле."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Счёт"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Розетки", geometry_type=GeometryType.COUNT
        )
        for point in ([[0.2, 0.2]], [[0.4, 0.4]]):
            await takeoff_service.create_measurement(
                db_session, item=item, sheet=sheet, points=point, calibration=None
            )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            rows = _rows((await client.get(EXPORT.format(sheet_id=sheet.id))).text)

        assert len(rows) == 2
        assert [_number(row["Величина"]) for row in rows] == [Decimal(1), Decimal(1)]
        assert rows[0]["Единица"] == "шт"
        assert _number(rows[0]["Итог по строке на листе"]) == Decimal(2)
        assert rows[0]["Измерений в итоге"] == "2"

    async def test_archived_item_keeps_its_name_in_the_export(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Архив прячет строку из панели, но не из уже сделанных измерений."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Архив"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Старые двери", geometry_type=GeometryType.COUNT
        )
        await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.2, 0.2]], calibration=None
        )
        await takeoff_service.archive_item(db_session, item=item)
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            rows = _rows((await client.get(EXPORT.format(sheet_id=sheet.id))).text)

        assert rows[0]["Строка обмера"] == "Старые двери"

    async def test_empty_sheet_gives_headers_only(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Пусто"
        )
        sheet = await _sheet(db_session, project=project)
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(EXPORT.format(sheet_id=sheet.id))

        assert response.status_code == 200
        assert _rows(response.text) == []

    async def test_foreign_sheet_is_not_found(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        """Граница пространства та же, что у остальных маршрутов обмера."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Чужой"
        )
        sheet = await _sheet(db_session, project=project)
        await db_session.commit()

        async with build_api(_engineer(second_workspace.id)) as client:
            response = await client.get(EXPORT.format(sheet_id=sheet.id))

        assert response.status_code == 404


class TestExportFollowsTheFlag:
    async def test_disabled_pilot_closes_the_export(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Выгрузка — часть ручного обмера и закрыта тем же флагом (ADR-0023)."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Флаг"
        )
        sheet = await _sheet(db_session, project=project)
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.get(EXPORT.format(sheet_id=sheet.id))

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"
