"""Безопасные ответы при отказах.

Наружу должен уходить стабильный код, а не трассировка и не строка подключения.
База данных для этих проверок не нужна: отказ имитируется подменой зависимости.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.errors import DomainError, ErrorCode
from app.main import create_app

SECRETS = ("password", "asyncpg", "postgresql://", "Traceback", "quantor_dev")


async def _client_with_failing_session(error: Exception) -> AsyncClient:
    app = create_app()

    async def broken_session() -> AsyncIterator[AsyncSession]:
        raise error
        yield  # pragma: no cover — недостижимо, нужно лишь чтобы это был генератор

    app.dependency_overrides[get_session] = broken_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def test_unreachable_database_returns_503_with_stable_code() -> None:
    client = await _client_with_failing_session(
        ConnectionRefusedError("[WinError 1225] connection refused")
    )
    async with client:
        response = await client.get("/api/v1/projects")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == ErrorCode.DATABASE_UNAVAILABLE.value


async def test_failure_response_does_not_leak_connection_details() -> None:
    client = await _client_with_failing_session(
        ConnectionRefusedError("postgresql://quantor:password@localhost:5432/quantor")
    )
    async with client:
        response = await client.get("/api/v1/projects")

    body = response.text
    for secret in SECRETS:
        assert secret not in body, secret


async def test_domain_error_becomes_conflict_with_its_code() -> None:
    client = await _client_with_failing_session(
        DomainError(ErrorCode.JOB_TRANSITION_INVALID, "Переход running -> running недопустим")
    )
    async with client:
        response = await client.get("/api/v1/projects")

    assert response.status_code == 409
    payload = response.json()["detail"]
    assert payload["code"] == ErrorCode.JOB_TRANSITION_INVALID.value
    assert "running" in payload["message"]


@pytest.mark.parametrize("code", list(ErrorCode))
def test_every_error_code_has_russian_message(code: ErrorCode) -> None:
    from app.errors import MESSAGES

    assert MESSAGES[code]
