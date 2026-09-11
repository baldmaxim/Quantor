"""Укрепление границ обмера (промт 14).

Здесь проверяется не «работает ли», а «выдержит ли». Разделено на две группы намеренно:
проверки формы запроса не требуют базы и потому идут всегда, а проверки границ арендатора
и журнала — требуют, потому что дыра в них видна только на настоящих строках.

Отдельная тема — **где** запрос умирает. Отвергнутый схемой многоугольник в сто тысяч
вершин не разобран; отвергнутый сервисом — уже оплачен памятью. Разница не видна в коде
ответа, поэтому проверяется явно.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from app.auth.context import AuthContext
from app.core.config import get_settings
from app.core.middleware import JsonBodyLimitMiddleware
from app.domain import (
    COORDINATES_PER_POINT,
    MAX_MEASUREMENT_BATCH,
    MAX_MEASUREMENT_POINTS,
    AuditAction,
    DocumentKind,
    GeometryStatus,
    GeometryType,
    ProcessingStatus,
    Role,
)
from app.main import create_app
from app.models import Document, PageGeometry, Project, Sheet, Workspace
from app.schemas import MeasurementBatchCreate, MeasurementCreate, MeasurementUpdate
from app.services import audit as audit_service
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import takeoff as takeoff_service
from tests.conftest import make_context

A1_WIDTH = Decimal("2384.0000")
A1_HEIGHT = Decimal("1684.0000")


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


class TestGeometryIsBoundedAtTheContract:
    """Форма запроса. Базы не требует: это разбор, а не работа с данными."""

    def test_hundred_thousand_point_polygon_is_refused_by_the_schema(self) -> None:
        """Отказ обязан случиться на разборе, а не в сервисе.

        Сервисный предел тоже есть и остаётся: сервис вызывается не только из HTTP. Но
        запрос, дошедший до него, уже разобран, и память под сто тысяч пар координат уже
        занята — то есть ровно то, ради чего такой запрос и посылают.
        """
        oversized = [[0.5, 0.5] for _ in range(100_000)]

        with pytest.raises(ValueError, match="at most"):
            MeasurementCreate(takeoff_item_id=uuid.uuid4(), points=oversized)

    def test_point_limit_is_the_declared_one(self) -> None:
        exact = [[0.5, 0.5] for _ in range(MAX_MEASUREMENT_POINTS)]
        assert len(MeasurementCreate(takeoff_item_id=uuid.uuid4(), points=exact).points) == (
            MAX_MEASUREMENT_POINTS
        )

        with pytest.raises(ValueError, match="at most"):
            MeasurementCreate(takeoff_item_id=uuid.uuid4(), points=[*exact, [0.5, 0.5]])

    def test_a_single_point_cannot_be_a_million_numbers(self) -> None:
        """Иначе предел на число точек обходится одной «точкой».

        Список из миллиона чисел прошёл бы проверку «точек не больше десяти тысяч»,
        потому что точка тут одна.
        """
        with pytest.raises(ValueError, match="at most"):
            MeasurementCreate(takeoff_item_id=uuid.uuid4(), points=[[0.5] * 1_000_000])

    def test_point_is_exactly_a_pair(self) -> None:
        assert COORDINATES_PER_POINT == 2
        for broken in ([[0.5]], [[0.5, 0.5, 0.5]]):
            with pytest.raises(ValueError, match=r"at least|at most"):
                MeasurementCreate(takeoff_item_id=uuid.uuid4(), points=broken)

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_coordinate_never_becomes_a_float(self, bad: str) -> None:
        """JSON пропускает NaN и бесконечность, а величина по такой геометрии — бессмыслица.

        Проверяется через разбор JSON, а не через готовый `float('nan')`: важно, что
        значение отвергается на границе, куда его и присылают.
        """
        payload = f'{{"takeoff_item_id": "{uuid.uuid4()}", "points": [[{bad}, 0.5]]}}'
        # Сам Python такой JSON принимает — отсюда и нужна проверка.
        assert math.isnan(json.loads(payload)["points"][0][0]) or math.isinf(
            json.loads(payload)["points"][0][0]
        )

        with pytest.raises(ValueError, match=r"finite|infinit|nan"):
            MeasurementCreate.model_validate_json(payload)

    def test_batch_is_bounded_before_parsing(self) -> None:
        oversized = [[[0.5, 0.5]] for _ in range(MAX_MEASUREMENT_BATCH + 1)]

        with pytest.raises(ValueError, match="at most"):
            MeasurementBatchCreate(takeoff_item_id=uuid.uuid4(), items=oversized)

    def test_update_carries_the_same_bounds(self) -> None:
        """Правка — та же геометрия. Предел, забытый на одном из путей, не предел."""
        with pytest.raises(ValueError, match="at most"):
            MeasurementUpdate(
                points=[[0.5, 0.5] for _ in range(MAX_MEASUREMENT_POINTS + 1)], version=1
            )

    def test_coordinate_range_stays_a_domain_rule(self) -> None:
        """Схема не проверяет попадание в лист — и это осознанно.

        Проверка диапазона на контракте сделала бы бессодержательной проверку атомарности
        пакета: негодная точка отсеивалась бы до транзакции, и «пакет отменяется целиком»
        стало бы нечего доказывать. Диапазон остаётся правилом сервиса.
        """
        outside = MeasurementCreate(takeoff_item_id=uuid.uuid4(), points=[[5.0, 0.3]])
        assert outside.points == [[5.0, 0.3]]

        from app.errors import DomainError

        with pytest.raises(DomainError):
            takeoff_service.validate_points(GeometryType.COUNT, outside.points)


class TestBodySizeLimit:
    """Предел тела запроса. Приложение поднимается без базы — обращений к ней здесь нет."""

    async def test_oversized_json_never_reaches_the_router(self) -> None:
        """Тело больше предела обрывается до разбора.

        Маршрут выбран несуществующий намеренно: обычно он дал бы 404, и 413 вместо него
        доказывает, что отказ случился раньше маршрутизации.
        """
        settings = get_settings()
        app = create_app()
        payload = b'{"filler": "' + b"x" * (settings.max_json_body_bytes + 1024) + b'"}'

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nothing-here",
                content=payload,
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"

    async def test_normal_json_passes_through(self) -> None:
        """Предел не должен мешать обычной работе."""
        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nothing-here",
                json={"filler": "x"},
            )

        assert response.status_code == 404

    async def test_lying_content_length_does_not_help(self) -> None:
        """Заголовок подделывается — считаются фактические байты.

        Заявлено мало, прислано много. Проверка идёт на игрушечном приложении, которое
        тело действительно читает: настоящий маршрут с неизвестным путём отвечает 404,
        не притронувшись к телу, и счётчик байтов там просто не участвует.
        """
        limit = 4096
        consumed: list[int] = []

        async def echo(scope: Scope, receive: Receive, send: Send) -> None:
            body = b""
            while True:
                message = await receive()
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            consumed.append(len(body))
            await send({"type": "http.response.start", "status": 200, "headers": [(b"x-ok", b"1")]})
            await send({"type": "http.response.body", "body": b"{}"})

        guarded = JsonBodyLimitMiddleware(echo, max_bytes=limit)
        payload = b'{"filler": "' + b"x" * (limit * 2) + b'"}'

        transport = ASGITransport(app=guarded)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/anything",
                content=payload,
                headers={"Content-Type": "application/json", "Content-Length": "12"},
            )

        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "UPLOAD_TOO_LARGE"
        # Приложение так и не получило целого тела: чтение оборвано на пределе.
        assert consumed == []

    async def test_upload_route_is_not_squeezed_by_the_json_limit(self) -> None:
        """Загрузка файла идёт не как JSON и живёт по своему, куда большему пределу."""
        settings = get_settings()
        assert settings.max_upload_size_bytes > settings.max_json_body_bytes

        app = create_app()
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/nothing-here",
                content=b"x" * (settings.max_json_body_bytes + 1024),
                headers={"Content-Type": "application/octet-stream"},
            )

        # Не 413: предел JSON к потоку файлов не применяется.
        assert response.status_code == 404


@pytest.mark.usefixtures("takeoff_manual_enabled")
class TestTenantBoundariesUnderAttack:
    """Границы арендатора на злонамеренных сочетаниях. Требует базы."""

    async def test_batch_cannot_cross_workspaces(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Строка своя, лист чужой — пакет обязан не найти лист.

        Пакетный путь отдельный от одиночного, и дыра, закрытая в одном, в другом
        остаётся открытой, пока не проверена.
        """
        mine = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Мой"
        )
        item = await takeoff_service.create_item(
            db_session, project=mine, name="Двери", geometry_type=GeometryType.COUNT
        )

        stranger = Workspace(slug="stranger-batch", name="Чужие")
        db_session.add(stranger)
        await db_session.flush()
        theirs = await projects_service.create_project(
            db_session, workspace_id=stranger.id, name="Чужой"
        )
        foreign_sheet = await _sheet(db_session, project=theirs)
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.post(
                f"/api/v1/sheets/{foreign_sheet.id}/measurements/batch",
                json={
                    "takeoff_item_id": str(item.id),
                    "items": [[[0.1, 0.1]], [[0.2, 0.2]]],
                },
            )

        # 404, а не 403: существование чужого листа — тоже сведения.
        assert response.status_code == 404

    async def test_version_cannot_be_bypassed_by_a_larger_number(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Версия из будущего — не пропуск.

        Проверка «версия совпадает» и проверка «версия не меньше» выглядят похоже, но
        вторая пропускает клиента, который не видел последнюю правку.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Версии"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        measurement = await takeoff_service.create_measurement(
            db_session, item=item, sheet=sheet, points=[[0.1, 0.1], [0.2, 0.2]]
        )
        await db_session.commit()

        async with build_api(_engineer(workspace_id)) as client:
            response = await client.patch(
                f"/api/v1/measurements/{measurement.id}",
                json={"points": [[0.3, 0.3], [0.4, 0.4]], "version": 999},
            )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "MEASUREMENT_VERSION_CONFLICT"

    async def test_creator_cannot_be_forged(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Автора ставит сервер по сеансу, а не клиент по своему желанию."""
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Автор"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Двери", geometry_type=GeometryType.COUNT
        )
        await db_session.commit()

        impostor = uuid.uuid4()
        context = _engineer(workspace_id)
        async with build_api(context) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={
                    "takeoff_item_id": str(item.id),
                    "points": [[0.5, 0.5]],
                    "created_by": str(impostor),
                    "source": "ai",
                    "version": 42,
                },
            )

        assert created.status_code == 201
        body = created.json()
        assert body["created_by"] != str(impostor)
        assert body["source"] == "manual"
        assert body["version"] == 1


@pytest.mark.usefixtures("takeoff_manual_enabled")
class TestAuditDoesNotLeak:
    """Журнал обязан объяснять действие, не пересказывая данные."""

    async def test_audit_records_no_geometry(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """В журнале отпечаток и число точек, а не координаты.

        Тысяча пар чисел раздула бы журнал и ничего бы не объяснила, а сам журнал читают
        не те, кто видит чертёж.
        """
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Журнал"
        )
        sheet = await _sheet(db_session, project=project)
        item = await takeoff_service.create_item(
            db_session, project=project, name="Стены", geometry_type=GeometryType.LINE
        )
        await db_session.commit()

        secret = [[0.123456, 0.654321], [0.222222, 0.777777]]
        async with build_api(_engineer(workspace_id)) as client:
            created = await client.post(
                f"/api/v1/sheets/{sheet.id}/measurements",
                json={"takeoff_item_id": str(item.id), "points": secret},
            )
        assert created.status_code == 201

        events = (await db_session.scalars(audit_service.scoped(workspace_id))).all()
        relevant = [
            event for event in events if event.action == AuditAction.MEASUREMENT_CREATED.value
        ]
        assert relevant, "создание измерения обязано попасть в журнал"

        recorded = json.dumps(
            [[event.before_summary, event.after_summary] for event in relevant],
            ensure_ascii=False,
            sort_keys=True,
        )
        assert "0.123456" not in recorded
        assert "0.654321" not in recorded
        assert "point_count" in recorded
        assert "geometry_digest" in recorded
