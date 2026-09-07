"""Liveness и readiness."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.api import health
from app.db.schema_version import SchemaOutdatedError, expected_revision


async def test_liveness_does_not_touch_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_liveness_returns_request_id_header(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.headers["X-Request-ID"]


async def test_liveness_echoes_incoming_request_id(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "trace-42"})

    assert response.headers["X-Request-ID"] == "trace-42"


async def test_readiness_ok_when_dependencies_answer(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    monkeypatch.setattr(health, "ping_database", ok)
    monkeypatch.setattr(health, "check_schema_current", ok)
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(ok))

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert {component["name"] for component in payload["components"]} == {
        "database",
        "database_schema",
        "object_storage",
    }
    assert payload["schema_revision"] == expected_revision()


async def test_readiness_degraded_when_storage_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def fail() -> None:
        raise ConnectionError("storage refused connection to bucket quantor-dev")

    monkeypatch.setattr(health, "ping_database", ok)
    monkeypatch.setattr(health, "check_schema_current", ok)
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(fail))

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    statuses = {component["name"]: component["status"] for component in payload["components"]}
    assert statuses == {
        "database": "ok",
        "database_schema": "ok",
        "object_storage": "unavailable",
    }
    # Наружу не должно уходить ничего, кроме безопасного статуса.
    assert "bucket" not in response.text
    assert "ConnectionError" not in response.text


async def test_readiness_survives_hanging_dependency(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def hang() -> None:
        await asyncio.sleep(60)

    monkeypatch.setattr(health, "ping_database", hang)
    monkeypatch.setattr(health, "check_schema_current", ok)
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(ok))
    monkeypatch.setattr(health.get_settings(), "readiness_timeout_seconds", 0.05)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    statuses = {c["name"]: c["status"] for c in response.json()["components"]}
    assert statuses["database"] == "unavailable"


async def test_outdated_schema_says_what_to_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отставшая база — самая частая поломка после git pull.

    Раньше она выглядела как «сервис не отвечает»: и приложение живо, и база отвечает,
    а любой запрос падает на несуществующей колонке. Теперь готовность прямо называет
    команду, которой это чинится.
    """

    async def ok() -> None:
        return None

    async def outdated() -> None:
        raise SchemaOutdatedError(
            "база на ревизии 0001_domain_stage1, коду нужна 0002_project_source"
        )

    monkeypatch.setattr(health, "ping_database", ok)
    monkeypatch.setattr(health, "check_schema_current", outdated)
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(ok))

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"

    schema = next(c for c in payload["components"] if c["name"] == "database_schema")
    # База жива — отдельный статус, а не общее «недоступно»: чинится другой командой.
    assert schema["status"] == "outdated"
    assert "pnpm db:migrate" in schema["detail"]
    assert "0002_project_source" in schema["detail"]


async def test_readiness_never_leaks_connection_details(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def fail() -> None:
        raise ConnectionError("postgresql://quantor:hunter2@db.internal:5432/quantor")

    monkeypatch.setattr(health, "ping_database", fail)
    monkeypatch.setattr(health, "check_schema_current", ok)
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(ok))

    response = await client.get("/health/ready")

    assert "hunter2" not in response.text
    assert "postgresql" not in response.text
    assert "db.internal" not in response.text


async def test_unreachable_database_is_not_reported_as_outdated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Недоступная база и отставшая схема — разные поломки с разной починкой."""
    from app.db import schema_version

    async def refuse() -> str | None:
        raise ConnectionRefusedError("сервер не принимает подключения")

    monkeypatch.setattr(schema_version, "current_revision", refuse)

    with pytest.raises(ConnectionRefusedError):
        await schema_version.check_schema_current()


def test_expected_revision_is_the_single_head() -> None:
    """Голова миграций читается из кода, а не задаётся строкой в двух местах."""
    assert expected_revision().strip()


class _FakeStorage:
    """Подмена объектного хранилища: тесты оболочки не поднимают MinIO."""

    def __init__(self, check: Callable[[], Awaitable[None]]) -> None:
        self._check = check

    @property
    def bucket(self) -> str:
        return "test-bucket"

    async def check_available(self) -> None:
        await self._check()
