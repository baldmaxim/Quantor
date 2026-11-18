"""MCP-сервер портала: протокол JSON-RPC, инструменты по токену, права областей, отказ cookie и анонимам.

Настоящий путь: вход по паролю, выпуск токена, запросы к /api/v1/mcp с Authorization: Bearer; инструменты
вызывают адреса портала тем же токеном.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import Role
from app.services import projects as projects_service
from tests.conftest import clean_settings
from tests.test_api_tokens import TOKENS, _csrf
from tests.test_local_auth import _approved_user, _login

MCP = "/api/v1/mcp"


def _settings() -> Settings:
    return clean_settings(
        auth_mode="local",
        environment="test",
        feature_flags="tender.exchange=true,model.import=true",
    )


async def _token(build_api: Callable[..., AsyncClient], scopes: list[str]) -> str:
    async with build_api(settings=_settings()) as client:
        assert await _login(client) == 200
        created = await client.post(
            TOKENS, json={"name": "агент", "scopes": scopes}, headers=_csrf(client)
        )
        assert created.status_code == 201, created.text
        return str(created.json()["token"])


def _rpc(method: str, params: dict[str, Any] | None = None, message_id: int = 1) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


async def _call(client: AsyncClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(MCP, json=_rpc("tools/call", {"name": name, "arguments": arguments}))
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


async def test_initialize_and_tools_list(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    token = await _token(build_api, ["read"])
    async with build_api(settings=_settings()) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        init = await client.post(MCP, json=_rpc("initialize", {"protocolVersion": "2025-03-26"}))
        assert init.status_code == 200
        result = init.json()["result"]
        assert result["protocolVersion"] == "2025-03-26"
        assert result["serverInfo"]["name"] == "quantor" and "координационный" in result["instructions"]
        listed = (await client.post(MCP, json=_rpc("tools/list", message_id=2))).json()["result"]
        names = {tool["name"] for tool in listed["tools"]}
        assert {"find_projects", "get_coordination", "send_ifc_to_3d", "model_status"} <= names
        send = next(t for t in listed["tools"] if t["name"] == "send_ifc_to_3d")
        assert send["annotations"]["readOnlyHint"] is False
        assert send["inputSchema"]["required"] == ["project", "filename", "content"]


async def test_read_tools_work_by_project_name(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    await projects_service.create_project(db_session, workspace_id=DEV_WORKSPACE_ID, name="341. Капельский")
    token = await _token(build_api, ["read"])
    async with build_api(settings=_settings()) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        found = await _call(client, "find_projects", {"search": "Капельский"})
        assert found["isError"] is False
        assert [p["name"] for p in found["structuredContent"]["projects"]] == ["341. Капельский"]
        status = await _call(client, "model_status", {"project": "341. Капельский"})
        assert status["isError"] is False and "Сборок ещё не было" in status["content"][0]["text"]
        coordination = await _call(client, "get_coordination", {"project": "341. Капельский"})
        assert coordination["isError"] is True and "Выпустить базу" in coordination["content"][0]["text"]
        missing = await _call(client, "model_status", {"project": "Нет такого"})
        assert missing["isError"] is True and "не найден" in missing["content"][0]["text"]


async def test_send_ifc_needs_upload_scope_and_makes_a_revision(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    project = await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="Объект КР"
    )
    ifc = "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
    read_token = await _token(build_api, ["read"])
    upload_token = await _token(build_api, ["upload"])
    async with build_api(settings=_settings()) as client:
        client.headers["Authorization"] = f"Bearer {read_token}"
        denied = await _call(
            client,
            "send_ifc_to_3d",
            {"project": str(project.id), "filename": "KR.ifc", "content": ifc, "build": False},
        )
        assert denied["isError"] is True and "403" in denied["content"][0]["text"]

        client.headers["Authorization"] = f"Bearer {upload_token}"
        first = await _call(
            client,
            "send_ifc_to_3d",
            {"project": str(project.id), "filename": "KR.ifc", "content": ifc, "build": False},
        )
        assert first["isError"] is False, first
        assert "новый документ" in first["content"][0]["text"]
        second = await _call(
            client,
            "send_ifc_to_3d",
            {"project": "Объект КР", "filename": "KR.ifc", "content": ifc + "/* v2 */\n", "build": False},
        )
        assert second["isError"] is False, second
        assert "новая ревизия документа" in second["content"][0]["text"]
        assert second["structuredContent"]["document_id"] == first["structuredContent"]["document_id"]
        bad = await _call(
            client, "send_ifc_to_3d", {"project": "Объект КР", "filename": "KR.pdf", "content": ifc}
        )
        assert bad["isError"] is True and ".ifc" in bad["content"][0]["text"]


async def test_protocol_errors_and_notifications(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    token = await _token(build_api, ["read"])
    async with build_api(settings=_settings()) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        note = await client.post(MCP, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert note.status_code == 202 and note.content == b""
        unknown = (await client.post(MCP, json=_rpc("resources/list"))).json()
        assert unknown["error"]["code"] == -32601
        no_tool = (await client.post(MCP, json=_rpc("tools/call", {"name": "rm_rf"}))).json()
        assert no_tool["error"]["code"] == -32602
        batch = await client.post(MCP, json=[_rpc("ping", message_id=7), {"jsonrpc": "2.0", "method": "x"}])
        assert batch.json() == [{"jsonrpc": "2.0", "id": 7, "result": {}}]
        broken = await client.post(MCP, content=b"{not json", headers={"Content-Type": "application/json"})
        assert broken.status_code == 400 and broken.json()["error"]["code"] == -32700
        assert (await client.get(MCP)).status_code == 405
        foreign = await client.post(MCP, json=_rpc("ping"), headers={"Origin": "https://evil.example"})
        assert foreign.status_code == 403


async def test_cookie_session_and_anonymous_are_refused(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    async with build_api(settings=_settings()) as client:
        assert await _login(client) == 200
        by_cookie = await client.post(MCP, json=_rpc("ping"), headers=_csrf(client))
        assert by_cookie.status_code == 403
        assert "токену" in by_cookie.json()["detail"]["message"]
    async with build_api(settings=_settings()) as anonymous:
        assert (await anonymous.post(MCP, json=_rpc("ping"))).status_code == 401
