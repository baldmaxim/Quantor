"""Калибровка масштаба чертежа (ADR-0018).

Главное, что здесь проверяется, — что коэффициент одинаково верен по обеим осям и по
диагонали. Прежний `units_per_normalized` этого не мог: на прямоугольной странице 0,1 по X
и 0,1 по Y — разные расстояния, и ошибка достигала полутора раз на листе A1.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    DocumentKind,
    GeometryStatus,
    LengthUnit,
    ProcessingStatus,
    Role,
    ScaleSource,
    VerificationState,
)
from app.errors import DomainError, ErrorCode
from app.models import Document, PageGeometry, Project, ScaleCalibration, Sheet, Workspace
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import scale as scale_service
from tests.conftest import make_context

# Страница A1 в точках PDF: намеренно прямоугольная. На квадратной странице ошибка
# старого контракта была бы незаметна.
A1_WIDTH = Decimal("2384.0000")
A1_HEIGHT = Decimal("1684.0000")
FINGERPRINT = "c" * 64


async def _sheet_with_geometry(
    session: AsyncSession,
    *,
    project: Project,
    width: Decimal = A1_WIDTH,
    height: Decimal = A1_HEIGHT,
    with_geometry: bool = True,
) -> Sheet:
    """Лист с канонической геометрией — то, без чего калибровать не от чего."""
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
        source_sha256="d" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY if with_geometry else GeometryStatus.PENDING,
    )

    sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1", rotation=0)
    session.add(sheet)
    await session.flush()

    if with_geometry:
        session.add(
            PageGeometry(
                sheet_id=sheet.id,
                display_width_pt=width,
                display_height_pt=height,
                pdf_rotation=0,
                media_box=["0", "0", str(width), str(height)],
                crop_box=["0", "0", str(width), str(height)],
                parser_name="pypdf",
                parser_version="6.18.0",
                source_sha256="d" * 64,
                geometry_fingerprint=FINGERPRINT,
                extracted_at=datetime.now(UTC),
            )
        )
        await session.flush()

    return sheet


class TestFactorMath:
    """Расчёт коэффициента. Ожидания известны заранее, а не сняты с реализации."""

    @staticmethod
    def _geometry(width: Decimal = A1_WIDTH, height: Decimal = A1_HEIGHT) -> PageGeometry:
        return PageGeometry(
            sheet_id=uuid.uuid4(),
            display_width_pt=width,
            display_height_pt=height,
            pdf_rotation=0,
            media_box=[],
            crop_box=[],
            parser_name="pypdf",
            parser_version="6.18.0",
            source_sha256="d" * 64,
            geometry_fingerprint=FINGERPRINT,
            extracted_at=datetime.now(UTC),
        )

    def test_horizontal_dimension(self) -> None:
        """Половина ширины листа A1 — 1192 pt. При 6000 мм это ровно 5,033… мм на точку."""
        distance, factor = scale_service.compute_factor(
            geometry=self._geometry(),
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            known_distance_mm=Decimal("6000"),
        )

        assert distance == Decimal("1192.000000")
        assert factor == (Decimal("6000") / Decimal("1192")).quantize(Decimal("0.000000000001"))

    def test_vertical_dimension_gives_the_same_factor(self) -> None:
        """Ключевая проверка этапа.

        Отрезок той же физической длины, но по вертикали, обязан дать тот же коэффициент.
        Старый `units_per_normalized` дал бы разные числа: доля страницы по вертикали
        соответствует другому расстоянию.
        """
        geometry = self._geometry()
        # 1192 pt по вертикали — это доля 1192/1684 высоты листа.
        share = Decimal("1192") / A1_HEIGHT

        _, horizontal = scale_service.compute_factor(
            geometry=geometry,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            known_distance_mm=Decimal("6000"),
        )
        vertical_distance, vertical = scale_service.compute_factor(
            geometry=geometry,
            point_a=(Decimal("0.5"), Decimal("0")),
            point_b=(Decimal("0.5"), share),
            known_distance_mm=Decimal("6000"),
        )

        assert vertical_distance == Decimal("1192.000000")
        assert vertical == horizontal

    def test_diagonal_dimension(self) -> None:
        """Диагональ 3-4-5 на подобранной странице даёт круглое расстояние."""
        distance, factor = scale_service.compute_factor(
            geometry=self._geometry(Decimal("3000"), Decimal("4000")),
            point_a=(Decimal("0"), Decimal("0")),
            point_b=(Decimal("1"), Decimal("1")),
            known_distance_mm=Decimal("10000"),
        )

        assert distance == Decimal("5000.000000")
        assert factor == Decimal("2.000000000000")

    @pytest.mark.parametrize(
        ("value", "unit"),
        [
            (Decimal("6000"), LengthUnit.MM),
            (Decimal("600"), LengthUnit.CM),
            (Decimal("6"), LengthUnit.M),
        ],
    )
    def test_units_converge_to_the_same_millimetres(self, value: Decimal, unit: LengthUnit) -> None:
        """6000 мм, 600 см и 6 м — одно и то же число внутри."""
        assert scale_service.to_millimetres(value, unit) == Decimal("6000.0000")

    def test_short_segment_is_refused(self) -> None:
        """На коротком отрезке промах курсора умножил бы все объёмы листа."""
        with pytest.raises(DomainError) as error:
            scale_service.compute_factor(
                geometry=self._geometry(),
                point_a=(Decimal("0.5"), Decimal("0.5")),
                point_b=(Decimal("0.5001"), Decimal("0.5")),
                known_distance_mm=Decimal("6000"),
            )

        assert error.value.code is ErrorCode.SCALE_SEGMENT_TOO_SHORT

    def test_zero_length_segment_is_refused(self) -> None:
        """Совпавшие точки дали бы деление на ноль."""
        with pytest.raises(DomainError) as error:
            scale_service.compute_factor(
                geometry=self._geometry(),
                point_a=(Decimal("0.5"), Decimal("0.5")),
                point_b=(Decimal("0.5"), Decimal("0.5")),
                known_distance_mm=Decimal("6000"),
            )

        assert error.value.code is ErrorCode.SCALE_SEGMENT_TOO_SHORT


class TestPersistence:
    async def test_manual_calibration_keeps_its_evidence(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Хранится не только коэффициент, но и то, из чего он получен."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Калибровка"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)
        actor = uuid.uuid4()

        calibration = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6"),
            input_unit=LengthUnit.M,
            created_by=actor,
        )

        assert calibration.source is ScaleSource.MANUAL
        assert calibration.verification_state is VerificationState.UNVERIFIED
        # Введённое сохранено в исходном виде: приведённое к миллиметрам уже не
        # расскажет, что именно набрал человек.
        assert calibration.input_value == Decimal("6.0000")
        assert calibration.input_unit is LengthUnit.M
        assert calibration.known_distance_mm == Decimal("6000.0000")
        assert calibration.page_distance_pt == Decimal("1192.000000")
        assert calibration.page_geometry_fingerprint == FINGERPRINT
        assert calibration.created_by == actor
        assert calibration.is_default is True

    async def test_calibration_requires_page_geometry(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Без канонической геометрии масштаб не к чему привязать."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Без геометрии"
        )
        sheet = await _sheet_with_geometry(db_session, project=project, with_geometry=False)

        with pytest.raises(DomainError) as error:
            await scale_service.create_manual(
                db_session,
                sheet=sheet,
                point_a=(Decimal("0.25"), Decimal("0.5")),
                point_b=(Decimal("0.75"), Decimal("0.5")),
                input_value=Decimal("6000"),
                input_unit=LengthUnit.MM,
                created_by=None,
            )

        assert error.value.code is ErrorCode.SCALE_GEOMETRY_REQUIRED

    async def test_second_calibration_does_not_change_the_first(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Калибровка неизменяема: исправление создаёт новую, старая остаётся.

        Это и есть воспроизводимость вчерашнего расчёта. Если бы строка менялась на месте,
        объяснить предъявленное заказчику число было бы нечем.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Две калибровки"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)

        first = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        first_factor = first.mm_per_pt

        second = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6200"),
            input_unit=LengthUnit.MM,
            created_by=None,
            supersedes=first,
        )

        assert second.id != first.id
        assert second.supersedes_id == first.id
        # Старый коэффициент не тронут.
        assert first.mm_per_pt == first_factor
        assert second.mm_per_pt != first_factor

    async def test_only_one_calibration_is_default(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """Два «основных» масштаба — это два разных ответа, сколько метров в стене."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Действующая"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)

        first = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        second = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.1"), Decimal("0.1")),
            point_b=(Decimal("0.9"), Decimal("0.1")),
            input_value=Decimal("12000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        await db_session.flush()
        await db_session.refresh(first)

        assert second.is_default is True
        assert first.is_default is False

        default = await scale_service.get_default(
            db_session, workspace_id=workspace_id, sheet_id=sheet.id
        )
        assert default is not None
        assert default.id == second.id

    async def test_sheet_keeps_several_calibrations(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        """План 1:100 и узел 1:20 на одном листе — обычное дело."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="План и узел"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)

        for known in (Decimal("6000"), Decimal("1200")):
            await scale_service.create_manual(
                db_session,
                sheet=sheet,
                point_a=(Decimal("0.25"), Decimal("0.5")),
                point_b=(Decimal("0.75"), Decimal("0.5")),
                input_value=known,
                input_unit=LengthUnit.MM,
                created_by=None,
                make_default=False,
            )

        rows = await scale_service.list_for_sheet(
            db_session, workspace_id=workspace_id, sheet_id=sheet.id
        )

        assert len(rows) == 2

    async def test_verification_is_the_only_mutable_part(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Подтверждение"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)
        calibration = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        factor = calibration.mm_per_pt
        reviewer = uuid.uuid4()

        await scale_service.set_verification(
            db_session,
            calibration=calibration,
            state=VerificationState.VERIFIED,
            actor=reviewer,
        )

        assert calibration.verification_state is VerificationState.VERIFIED
        assert calibration.verified_by == reviewer
        assert calibration.verified_at is not None
        # Коэффициент подтверждением не меняется.
        assert calibration.mm_per_pt == factor


class TestTenantIsolation:
    async def test_foreign_calibration_is_not_found(
        self,
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Чужой"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)
        calibration = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )

        found = await scale_service.get_calibration(
            db_session, workspace_id=workspace_id, calibration_id=calibration.id
        )

        assert found is None


@pytest.mark.usefixtures("takeoff_manual_enabled")
class TestApiAndPermissions:
    """Матрица прав: кто видит, кто вносит, кто подтверждает."""

    @staticmethod
    async def _sheet(session: AsyncSession, workspace_id: uuid.UUID) -> Sheet:
        project = await projects_service.create_project(
            session, workspace_id=workspace_id, name="Через API"
        )
        sheet = await _sheet_with_geometry(session, project=project)
        await session.commit()
        return sheet

    async def test_engineer_creates_calibration(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet = await self._sheet(db_session, workspace_id)

        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/scale-calibrations",
                json={
                    "point_a": ["0.25", "0.5"],
                    "point_b": ["0.75", "0.5"],
                    "known_distance": "6000",
                    "unit": "mm",
                },
            )

        assert response.status_code == 201
        body = response.json()
        assert body["source"] == "manual"
        assert body["is_default"] is True
        assert Decimal(str(body["page_distance_pt"])) == Decimal("1192.000000")

    async def test_viewer_cannot_create(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Читатель видит масштаб, но не задаёт его."""
        sheet = await self._sheet(db_session, workspace_id)

        async with build_api(make_context(Role.VIEWER, workspace_id=workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/scale-calibrations",
                json={
                    "point_a": ["0.25", "0.5"],
                    "point_b": ["0.75", "0.5"],
                    "known_distance": "6000",
                    "unit": "mm",
                },
            )
            listed = await client.get(f"/api/v1/sheets/{sheet.id}/scale-calibrations")

        assert created.status_code == 403
        assert listed.status_code == 200

    async def test_reviewer_verifies_but_does_not_create(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Разделение автора и проверяющего — смысл роли, а не формальность."""
        sheet = await self._sheet(db_session, workspace_id)
        calibration = await scale_service.create_manual(
            db_session,
            sheet=sheet,
            point_a=(Decimal("0.25"), Decimal("0.5")),
            point_b=(Decimal("0.75"), Decimal("0.5")),
            input_value=Decimal("6000"),
            input_unit=LengthUnit.MM,
            created_by=None,
        )
        await db_session.commit()

        async with build_api(make_context(Role.REVIEWER, workspace_id=workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/scale-calibrations",
                json={
                    "point_a": ["0.25", "0.5"],
                    "point_b": ["0.75", "0.5"],
                    "known_distance": "6000",
                    "unit": "mm",
                },
            )
            verified = await client.post(
                f"/api/v1/scale-calibrations/{calibration.id}/verification",
                json={"state": "verified"},
            )

        assert created.status_code == 403
        assert verified.status_code == 200
        assert verified.json()["verification_state"] == "verified"

    async def test_short_segment_is_refused_by_api(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        sheet = await self._sheet(db_session, workspace_id)

        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/scale-calibrations",
                json={
                    "point_a": ["0.5", "0.5"],
                    "point_b": ["0.5", "0.5"],
                    "known_distance": "6000",
                    "unit": "mm",
                },
            )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "SCALE_SEGMENT_TOO_SHORT"

    async def test_client_cannot_supply_the_factor(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Коэффициент считает сервер: присланный клиентом просто игнорируется контрактом."""
        sheet = await self._sheet(db_session, workspace_id)

        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{sheet.id}/scale-calibrations",
                json={
                    "point_a": ["0.25", "0.5"],
                    "point_b": ["0.75", "0.5"],
                    "known_distance": "6000",
                    "unit": "mm",
                    "mm_per_pt": "999",
                },
            )

        assert response.status_code == 201
        assert Decimal(str(response.json()["mm_per_pt"])) != Decimal("999")

    async def test_foreign_sheet_is_not_found(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Соседский"
        )
        sheet = await _sheet_with_geometry(db_session, project=project)
        await db_session.commit()

        async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
            response = await client.get(f"/api/v1/sheets/{sheet.id}/scale-calibrations")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_model_has_no_normalized_factor() -> None:
    """Прямая проверка того, что старая ошибка не вернулась."""
    assert not hasattr(ScaleCalibration, "units_per_normalized")
    assert hasattr(ScaleCalibration, "mm_per_pt")
