"""Liveness и readiness."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.api import health


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
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(ok))

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert {component["name"] for component in payload["components"]} == {
        "database",
        "object_storage",
    }


async def test_readiness_degraded_when_storage_is_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> None:
        return None

    async def fail() -> None:
        raise ConnectionError("storage refused connection to bucket quantor-dev")

    monkeypatch.setattr(health, "ping_database", ok)
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(fail))

    response = await client.get("/health/ready")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    statuses = {component["name"]: component["status"] for component in payload["components"]}
    assert statuses == {"database": "ok", "object_storage": "unavailable"}
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
    monkeypatch.setattr(health, "get_object_storage", lambda: _FakeStorage(ok))
    monkeypatch.setattr(health.get_settings(), "readiness_timeout_seconds", 0.05)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    statuses = {c["name"]: c["status"] for c in response.json()["components"]}
    assert statuses["database"] == "unavailable"


class _FakeStorage:
    """Подмена объектного хранилища: тесты оболочки не поднимают MinIO."""

    def __init__(self, check: Callable[[], Awaitable[None]]) -> None:
        self._check = check

    @property
    def bucket(self) -> str:
        return "test-bucket"

    async def check_available(self) -> None:
        await self._check()
