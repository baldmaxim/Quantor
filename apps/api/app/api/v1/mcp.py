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

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, require
from app.auth.context import CredentialKind
from app.auth.permissions import Permission
from app.core.middleware import REQUEST_ID_HEADER
from app.core.request_context import get_request_id
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
async def mcp_endpoint(
    request: Request, context: AuthDep, settings: SettingsDep, session: SessionDep
) -> Response:
    if context.credential is not CredentialKind.API_TOKEN:
        raise http_error(
            ErrorCode.PERMISSION_DENIED,
            message="MCP работает только по личному токену: Authorization: Bearer qtk_…",
        )
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origins:
        raise http_error(ErrorCode.PERMISSION_DENIED, message="Запрос к MCP с чужой страницы")
    # Только JSON: тогда тело ограничено пределом JsonBodyLimitMiddleware (4 МБ), а не памятью.
    if not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": mcp_server.INVALID_REQUEST,
                    "message": "Нужен Content-Type: application/json",
                },
            },
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    body = await request.body()
    if len(body) > settings.max_json_body_bytes:
        raise http_error(ErrorCode.UPLOAD_TOO_LARGE)
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": mcp_server.PARSE_ERROR, "message": "Тело не JSON"},
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    # Соединение с базой этого запроса (им проверяли токен) отпускаем до вызовов инструментов:
    # каждый внутренний вызов берёт своё, а пул на процесс маленький - иначе параллельные вызовы MCP
    # занимали бы по два соединения и упирались в пул.
    await session.close()
    client_host = request.client.host if request.client else "127.0.0.1"
    client_port = request.client.port if request.client else 0
    async with httpx.AsyncClient(
        # raise_app_exceptions=False: сбой внутреннего адреса - ответ 500, а не исключение,
        # он превращается в isError инструмента. client - настоящий адрес агента для журнала.
        transport=httpx.ASGITransport(
            app=request.app, raise_app_exceptions=False, client=(client_host, client_port)
        ),
        base_url=INTERNAL_BASE_URL,
        headers={
            "Authorization": request.headers.get("authorization", ""),
            "User-Agent": f"{request.headers.get('user-agent', 'MCP')} (via quantor-mcp)",
            REQUEST_ID_HEADER: get_request_id() or "",
        },
        timeout=INTERNAL_TIMEOUT_SECONDS,
    ) as client:
        answer = await mcp_server.dispatch(payload, mcp_server.Caller(client))
    if answer is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(answer)


@router.get(
    "/mcp", include_in_schema=False, dependencies=[require(Permission.WORKSPACE_READ)]
)
async def mcp_without_stream() -> Response:
    """Потока событий сервер не держит: всё - ответами на POST."""
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST"})
