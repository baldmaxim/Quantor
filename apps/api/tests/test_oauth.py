"""Вход ИИ-чатов по OAuth 2.1 (ADR-0054): весь путь чата и его отказы.

Метаданные → регистрация (только белый список адресов возврата) → согласие человека в сеансе →
код с PKCE → доступ и обновление → MCP. Доступ чата - только для MCP; отзыв разрешения в списке
«Доступ» гасит его сразу; повтор кода отзывает разрешение.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

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
REGISTER = "/api/v1/auth/oauth/register"
TOKEN = "/api/v1/auth/oauth/token"
AUTHORIZE = "/api/v1/oauth/authorize"
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
ISSUER = "http://localhost:3000"


def _settings() -> Settings:
    return clean_settings(
        auth_mode="local",
        environment="test",
        feature_flags="tender.exchange=true,model.import=true",
    )


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _register(client: AsyncClient, redirect: str = CLAUDE_CALLBACK) -> str:
    response = await client.post(
        REGISTER,
        json={
            "client_name": "Claude",
            "redirect_uris": [redirect],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_endpoint_auth_method"] == "none" and "client_secret" not in body
    return str(body["client_id"])


def _params(client_id: str, challenge: str, **extra: str) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CLAUDE_CALLBACK,
        "state": "s-42",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "read upload offline_access",
        "resource": f"{ISSUER}/api/v1/mcp",
    }
    params.update(extra)
    return params


async def _authorize(
    client: AsyncClient, params: dict[str, str], *, approve: bool = True, scopes: list[str] | None
) -> dict[str, list[str]]:
    response = await client.post(
        AUTHORIZE,
        json={"params": params, "approve": approve, "scopes": scopes},
        headers=_csrf(client),
    )
    assert response.status_code == 200, response.text
    target = urlsplit(response.json()["redirect_to"])
    assert f"{target.scheme}://{target.netloc}{target.path}" == params["redirect_uri"]
    return parse_qs(target.query)


async def _connect(
    build_api: Callable[..., AsyncClient], scopes: list[str] | None = None
) -> tuple[str, str, dict[str, Any]]:
    """Регистрация, согласие и обмен кода: (client_id, verifier, ответ точки выдачи)."""
    verifier, challenge = _pkce()
    async with build_api(settings=_settings()) as client:
        client_id = await _register(client)
        assert await _login(client) == 200
        query = await _authorize(client, _params(client_id, challenge), scopes=scopes)
        assert query["state"] == ["s-42"] and query["iss"] == [ISSUER]
        code = query["code"][0]
        tokens = await client.post(
            TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CLAUDE_CALLBACK,
                "client_id": client_id,
                "code_verifier": verifier,
                "resource": f"{ISSUER}/api/v1/mcp",
            },
        )
        assert tokens.status_code == 200, tokens.text
        assert tokens.headers["cache-control"] == "no-store"
        return client_id, code, tokens.json()


async def test_metadata_and_mcp_challenge(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(settings=_settings()) as client:
        server = (await client.get("/api/v1/auth/oauth/metadata/authorization-server")).json()
        assert server["issuer"] == ISSUER
        assert server["authorization_endpoint"] == f"{ISSUER}/oauth/authorize"
        assert server["token_endpoint"] == f"{ISSUER}/api/v1/auth/oauth/token"
        assert server["registration_endpoint"] == f"{ISSUER}/api/v1/auth/oauth/register"
        assert server["code_challenge_methods_supported"] == ["S256"]
        assert "none" in server["token_endpoint_auth_methods_supported"]
        assert server["authorization_response_iss_parameter_supported"] is True
        assert "client_id_metadata_document_supported" not in server
        resource = (await client.get("/api/v1/auth/oauth/metadata/protected-resource")).json()
        assert resource["resource"] == f"{ISSUER}/api/v1/mcp"
        assert resource["authorization_servers"] == [ISSUER]
        assert resource["scopes_supported"] == ["read", "upload"]

        anonymous = await client.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert anonymous.status_code == 401
        challenge = anonymous.headers["www-authenticate"]
        assert challenge.startswith("Bearer ")
        expected = f"{ISSUER}/.well-known/oauth-protected-resource/api/v1/mcp"
        assert f'resource_metadata="{expected}"' in challenge
        # Чужие адреса API отказывают как раньше, без метаданных MCP.
        other = await client.get("/api/v1/projects")
        assert other.status_code == 401 and "resource_metadata" not in other.headers.get(
            "www-authenticate", ""
        )


async def test_registration_accepts_only_known_redirects(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(settings=_settings()) as client:
        evil = await client.post(
            REGISTER,
            json={"client_name": "Claude", "redirect_uris": ["https://evil.example/cb"]},
        )
        assert evil.status_code == 400 and evil.json()["error"] == "invalid_redirect_uri"
        plain_http = await client.post(
            REGISTER, json={"redirect_uris": ["http://claude.ai/api/mcp/auth_callback"]}
        )
        assert plain_http.status_code == 400
        not_json = await client.post(
            REGISTER, content=b"{", headers={"content-type": "application/json"}
        )
        assert not_json.status_code == 400
        chatgpt = await client.post(
            REGISTER,
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chatgpt.com/connector/oauth/abc123"],
                "token_endpoint_auth_method": "client_secret_post",
            },
        )
        assert chatgpt.status_code == 201, chatgpt.text
        assert chatgpt.json()["client_secret"].startswith("qos_")
        local = await client.post(
            REGISTER,
            json={
                "redirect_uris": ["http://localhost:53682/callback"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert local.status_code == 201 and local.json()["client_name"] == "ИИ-клиент"


async def test_full_flow_mcp_refresh_and_revoke(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="341. Капельский"
    )
    client_id, _code, tokens = await _connect(build_api)
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
    assert tokens["access_token"].startswith("qoa_")
    assert tokens["refresh_token"].startswith("qor_")
    assert tokens["scope"] == "read upload"

    async with build_api(settings=_settings()) as client:
        client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        found = await client.post(
            MCP,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "find_projects", "arguments": {"search": "Капельский"}},
            },
        )
        assert found.status_code == 200, found.text
        result = found.json()["result"]
        assert result["isError"] is False
        assert [p["name"] for p in result["structuredContent"]["projects"]] == ["341. Капельский"]
        # Доступ чата - только MCP: остальной API его не принимает.
        direct = await client.get("/api/v1/projects")
        assert direct.status_code == 401

    async with build_api(settings=_settings()) as client:
        refreshed = await client.post(
            TOKEN,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        fresh = refreshed.json()
        assert fresh["refresh_token"] != tokens["refresh_token"]
        # Повтор того же обновления сразу - гонка, а не кража: отказ без отзыва разрешения.
        replay = await client.post(
            TOKEN,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        ok = await client.post(
            MCP,
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            headers={"Authorization": f"Bearer {fresh['access_token']}"},
        )
        assert ok.status_code == 200

        assert await _login(client) == 200
        listed = (await client.get(TOKENS)).json()
        grant = next(row for row in listed if row["client_name"] == "Claude")
        assert grant["name"] == "Claude (чат)" and grant["scopes"] == ["read", "upload"]
        revoked = await client.delete(f"{TOKENS}/{grant['id']}", headers=_csrf(client))
        assert revoked.status_code == 204

    async with build_api(settings=_settings()) as client:
        dead = await client.post(
            MCP,
            json={"jsonrpc": "2.0", "id": 3, "method": "ping"},
            headers={"Authorization": f"Bearer {fresh['access_token']}"},
        )
        assert dead.status_code == 401
        assert 'error="invalid_token"' in dead.headers["www-authenticate"]
        no_refresh = await client.post(
            TOKEN,
            data={
                "grant_type": "refresh_token",
                "refresh_token": fresh["refresh_token"],
                "client_id": client_id,
            },
        )
        assert no_refresh.status_code == 400


async def test_code_replay_and_bad_verifier(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    client_id, code, tokens = await _connect(build_api)
    async with build_api(settings=_settings()) as client:
        replay = await client.post(
            TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "code_verifier": "x" * 50,
            },
        )
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        # Повтор кода отзывает всё, что по нему выдано.
        revoked = await client.post(
            MCP,
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert revoked.status_code == 401

        verifier, challenge = _pkce()
        assert await _login(client) == 200
        query = await _authorize(client, _params(client_id, challenge), scopes=["read"])
        wrong = await client.post(
            TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "client_id": client_id,
                "code_verifier": _pkce()[0],
            },
        )
        assert wrong.status_code == 400 and "PKCE" in wrong.json()["error_description"]
        unknown_client = await client.post(
            TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "client_id": "qoc_nope",
                "code_verifier": verifier,
            },
        )
        assert unknown_client.status_code == 401
        assert unknown_client.json()["error"] == "invalid_client"
        form_only = await client.post(TOKEN, json={"grant_type": "authorization_code"})
        assert form_only.status_code == 400 and form_only.json()["error"] == "invalid_request"


async def test_consent_check_deny_and_scope_choice(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    verifier, challenge = _pkce()
    async with build_api(settings=_settings()) as client:
        client_id = await _register(client)
        assert await _login(client) == 200
        info = await client.get(AUTHORIZE, params=_params(client_id, challenge))
        assert info.status_code == 200, info.text
        body = info.json()
        assert body["client_name"] == "Claude" and body["redirect_host"] == "claude.ai"
        assert body["scopes"] == ["read", "upload"] and body["error_redirect"] is None
        assert body["local_app"] is False and body["already_connected"] is False

        foreign = await client.get(
            AUTHORIZE,
            params=_params(client_id, challenge, redirect_uri="https://claude.com/api/mcp/x"),
        )
        assert foreign.status_code >= 400 and "Адрес возврата" in foreign.text
        no_pkce = await client.get(AUTHORIZE, params=_params(client_id, "short"))
        redirect = no_pkce.json()["error_redirect"]
        assert redirect.startswith(CLAUDE_CALLBACK) and "error=invalid_request" in redirect
        wrong_resource = await client.get(
            AUTHORIZE, params=_params(client_id, challenge, resource="https://other/mcp")
        )
        assert "error=invalid_target" in wrong_resource.json()["error_redirect"]

        denied = await _authorize(client, _params(client_id, challenge), approve=False, scopes=[])
        assert denied["error"] == ["access_denied"] and denied["state"] == ["s-42"]

        query = await _authorize(client, _params(client_id, challenge), scopes=["read"])
        tokens = await client.post(
            TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert tokens.json()["scope"] == "read"
        again = await client.get(AUTHORIZE, params=_params(client_id, challenge))
        assert again.json()["already_connected"] is True


async def test_tokens_cannot_grant_chat_access(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    _client_id, _code, tokens = await _connect(build_api)
    async with build_api(settings=_settings()) as client:
        assert await _login(client) == 200
        personal = await client.post(
            TOKENS, json={"name": "агент", "scopes": ["read"]}, headers=_csrf(client)
        )
        qtk = personal.json()["token"]
    async with build_api(settings=_settings()) as client:
        verifier, challenge = _pkce()
        client_id = await _register(client)
        del verifier
        for value in (qtk, tokens["access_token"]):
            check = await client.get(
                AUTHORIZE,
                params=_params(client_id, challenge),
                headers={"Authorization": f"Bearer {value}"},
            )
            assert check.status_code in (401, 403), check.text
