"""MCP-сервер портала для ИИ-чатов и агентов: `POST /api/v1/mcp`.

Протокол и инструменты - `app.services.mcp_server`.
Только личный токен: у входа по cookie есть CSRF, а MCP-клиенты (Claude, ChatGPT, агенты) ходят с
заголовком `Authorization`. Запрос с чужим `Origin` (страница в браузере) отклоняется - защита от
подмены адреса из браузера, как требует спецификация MCP.
"""

from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.v1.deps import AuthDep, SettingsDep, require
from app.auth.context import CredentialKind
from app.auth.permissions import Permission
from app.errors import ErrorCode, http_error
from app.services import mcp_server

router = APIRouter(tags=["mcp"])

# Внутренние вызовы адресов портала идут в то же приложение (ASGI), без сети; имя хоста условное.
INTERNAL_BASE_URL = "http://quantor.internal"
INTERNAL_TIMEOUT_SECONDS = 120.0


@router.post(
    "/mcp",
    summary="MCP-сервер для ИИ-агентов (JSON-RPC 2.0), только по личному токену",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def mcp_endpoint(request: Request, context: AuthDep, settings: SettingsDep) -> Response:
    if context.credential is not CredentialKind.API_TOKEN:
        raise http_error(
            ErrorCode.PERMISSION_DENIED,
            message="MCP работает только по личному токену: Authorization: Bearer qtk_…",
        )
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        raise http_error(ErrorCode.PERMISSION_DENIED, message="Запрос к MCP с чужой страницы")
    try:
        payload = json.loads(await request.body())
    except ValueError:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": mcp_server.PARSE_ERROR, "message": "Тело не JSON"},
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=request.app),
        base_url=INTERNAL_BASE_URL,
        headers={"Authorization": request.headers.get("authorization", "")},
        timeout=INTERNAL_TIMEOUT_SECONDS,
    ) as client:
        answer = await mcp_server.dispatch(payload, mcp_server.Caller(client))
    if answer is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(answer)


@router.get("/mcp", include_in_schema=False)
async def mcp_without_stream() -> Response:
    """Потока событий сервер не держит: всё - ответами на POST."""
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})
