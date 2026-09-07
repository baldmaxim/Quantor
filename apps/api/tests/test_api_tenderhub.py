"""Интеграция с TenderHUB.

Сеть здесь не используется: транспорт подменяется, и проверяется ровно то, что портал
делает с чужими ответами — как разбирает конверт, как переводит отказы в свои коды и
как не пускает ключ дальше заголовка.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_tenderhub_client
from app.core.config import Settings
from app.core.features import resolve
from app.db.session import get_session
from app.domain import ProjectSource
from app.errors import DomainError, ErrorCode
from app.integrations.tenderhub import TenderHubClient
from app.main import create_app
from app.services import projects as projects_service

# Не секрет: значение живёт только в этом файле и никуда не уходит.
TOKEN = "thk_test_key"

TENDER: dict[str, Any] = {
    "id": "11111111-1111-4111-8111-111111111111",
    "tender_number": "ТН-0042",
    "title": "ЖК «Северный», корпус 3",
    "client_name": "ООО «Заказчик»",
    "version": 2,
    "is_archived": False,
    "construction_scope": "монолит",
    "submission_deadline": "2026-10-01",
    "updated_at": "2026-09-01T10:00:00Z",
}


def settings_with_key() -> Settings:
    return Settings(tenderhub_api_token=TOKEN)  # type: ignore[arg-type]


def make_client(handler: Any) -> TenderHubClient:
    return TenderHubClient(settings_with_key(), transport=httpx.MockTransport(handler))


def answer(status: int, payload: Any = None, *, text: str | None = None) -> Any:
    def handler(_: httpx.Request) -> httpx.Response:
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload)

    return handler


class TestKeyHandling:
    """Ключ уходит одним заголовком и больше нигде не появляется."""

    async def test_key_goes_in_x_api_key_only(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, json={"data": [TENDER]})

        async with make_client(handler) as client:
            await client.list_tenders()

        assert seen["x-api-key"] == TOKEN
        # Ключ в Authorization: Bearer уходит в ветку сессии и даёт 401 при исправном ключе.
        assert "authorization" not in seen

    async def test_missing_key_disables_integration(self) -> None:
        with pytest.raises(DomainError) as error:
            TenderHubClient(Settings(tenderhub_api_token=""))  # type: ignore[arg-type]

        assert error.value.code is ErrorCode.TENDERHUB_DISABLED

    def test_feature_flag_follows_the_key(self) -> None:
        assert resolve(tenderhub_configured=False)["integrations.tenderhub"] is False
        assert resolve(tenderhub_configured=True)["integrations.tenderhub"] is True


class TestResponseParsing:
    async def test_envelope_is_unwrapped(self) -> None:
        async with make_client(answer(200, {"data": [TENDER]})) as client:
            tenders = await client.list_tenders()

        assert [tender.tender_number for tender in tenders] == ["ТН-0042"]

    async def test_unknown_fields_do_not_break_import(self) -> None:
        row = {**TENDER, "totally_new_field": {"nested": 1}}

        async with make_client(answer(200, {"data": [row]})) as client:
            tenders = await client.list_tenders()

        assert tenders[0].id == TENDER["id"]

    async def test_archived_filter_is_sent(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.url.params)
            return httpx.Response(200, json={"data": []})

        async with make_client(handler) as client:
            await client.list_tenders(search="север")

        assert seen == {"is_archived": "false", "search": "север"}

    async def test_non_json_answer_is_not_silently_empty(self) -> None:
        async with make_client(answer(200, text="<html>proxy</html>")) as client:
            with pytest.raises(DomainError) as error:
                await client.list_tenders()

        assert error.value.code is ErrorCode.TENDERHUB_UNAVAILABLE


class TestUpstreamFailures:
    """Отказ внешней системы должен объяснять, что именно чинить."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, ErrorCode.TENDERHUB_AUTH_FAILED),
            (403, ErrorCode.TENDERHUB_FORBIDDEN),
            (404, ErrorCode.TENDERHUB_TENDER_NOT_FOUND),
            (429, ErrorCode.TENDERHUB_RATE_LIMITED),
            (503, ErrorCode.TENDERHUB_UNAVAILABLE),
        ],
    )
    async def test_status_maps_to_code(self, status: int, expected: ErrorCode) -> None:
        async with make_client(answer(status, {"code": "SOMETHING"})) as client:
            with pytest.raises(DomainError) as error:
                await client.list_tenders()

        assert error.value.code is expected

    async def test_timeout_is_reported_as_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("слишком долго", request=request)

        async with make_client(handler) as client:
            with pytest.raises(DomainError) as error:
                await client.list_tenders()

        assert error.value.code is ErrorCode.TENDERHUB_UNAVAILABLE

    async def test_key_never_appears_in_the_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("сеть недоступна", request=request)

        async with make_client(handler) as client:
            with pytest.raises(DomainError) as error:
                await client.list_tenders()

        assert TOKEN not in str(error.value)
        assert TOKEN not in error.value.detail


class TestTenderRoutes:
    """Маршруты портала. Нужна база: тендер превращается в проект."""

    @staticmethod
    def portal(db_session: AsyncSession, handler: Any) -> AsyncClient:
        app = create_app()

        async def override_session() -> Any:
            yield db_session

        async def override_client() -> Any:
            async with make_client(handler) as client:
                yield client

        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_tenderhub_client] = override_client

        return AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    async def test_list_shows_tenders(self, db_session: AsyncSession) -> None:
        async with self.portal(db_session, answer(200, {"data": [TENDER]})) as api:
            body = (await api.get("/api/v1/integrations/tenderhub/tenders")).json()

        assert body[0]["tender_number"] == "ТН-0042"
        # Тендер ещё не подключён — интерфейс покажет кнопку создания, а не ссылку.
        assert body[0]["imported_project_id"] is None

    async def test_creates_project_from_tender(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        async with self.portal(db_session, answer(200, {"data": TENDER})) as api:
            response = await api.post(
                "/api/v1/integrations/tenderhub/projects", json={"tender_id": TENDER["id"]}
            )

        assert response.status_code == 201
        body = response.json()
        # Номер впереди: тендеры ищут по номеру, а названия соседних различаются в конце.
        assert body["name"] == "ТН-0042 · ЖК «Северный», корпус 3"
        assert body["source"] == "tenderhub"
        assert body["external_ref"] == "ТН-0042"

        project = await projects_service.find_by_external_id(
            db_session,
            workspace_id=workspace_id,
            source=ProjectSource.TENDERHUB,
            external_id=str(TENDER["id"]),
        )
        assert project is not None

    async def test_same_tender_is_not_imported_twice(self, db_session: AsyncSession) -> None:
        async with self.portal(db_session, answer(200, {"data": TENDER})) as api:
            first = await api.post(
                "/api/v1/integrations/tenderhub/projects", json={"tender_id": TENDER["id"]}
            )
            second = await api.post(
                "/api/v1/integrations/tenderhub/projects", json={"tender_id": TENDER["id"]}
            )

        assert first.status_code == 201
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == ErrorCode.TENDERHUB_ALREADY_LINKED.value

    async def test_imported_tender_is_marked_in_the_list(self, db_session: AsyncSession) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = TENDER if "overview" in request.url.path else [TENDER]
            return httpx.Response(200, json={"data": payload})

        async with self.portal(db_session, handler) as api:
            created = await api.post(
                "/api/v1/integrations/tenderhub/projects", json={"tender_id": TENDER["id"]}
            )
            body = (await api.get("/api/v1/integrations/tenderhub/tenders")).json()

        # Строка, уже ставшая проектом, ведёт в него, а не предлагает создать ещё один.
        assert body[0]["imported_project_id"] == created.json()["id"]

    async def test_upstream_refusal_reaches_the_client(self, db_session: AsyncSession) -> None:
        async with self.portal(db_session, answer(401, {"code": "invalid API key"})) as api:
            response = await api.get("/api/v1/integrations/tenderhub/tenders")

        assert response.status_code == 502
        assert response.json()["detail"]["code"] == ErrorCode.TENDERHUB_AUTH_FAILED.value
