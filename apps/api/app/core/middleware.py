"""HTTP-middleware: предел размера тела, сквозной request id и лог доступа."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger
from app.core.request_context import set_client, set_request_id
from app.errors import STATUS_CODES, ErrorCode

REQUEST_ID_HEADER = "X-Request-ID"

log = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Проставляет request id (принимает клиентский, иначе генерирует) и пишет access-лог."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        set_request_id(request_id)
        # Не в лог: адрес и клиент нужны журналу административных действий, а писать их
        # в каждую строку access-лога значит собирать сведения о людях без повода.
        set_client(
            request.client.host if request.client else None,
            request.headers.get("User-Agent"),
        )

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class _BodyTooLargeError(Exception):
    """Тело превысило предел. Внутреннее: наружу уходит обычный отказ 413."""


class JsonBodyLimitMiddleware:
    """Обрывает слишком большое JSON-тело до того, как его кто-нибудь разберёт.

    Ограничение стоит здесь, а не только в схеме: схема получает уже разобранный объект,
    то есть память под него уже потрачена. Многоугольник на сто тысяч вершин — это
    не ошибка ввода, а способ занять процесс.

    Проверяется и заявленный `Content-Length`, и фактически принятые байты: заголовок
    подделывается, как и при загрузке файлов.

    Загрузок это не касается — они приходят не как JSON и ограничиваются потоком с
    собственным пределом, куда большим (`max_upload_size_bytes`).

    Чистое ASGI-middleware, а не `BaseHTTPMiddleware`: тот читает тело целиком, чтобы
    передать дальше, и предел, поставленный после чтения, ничего бы не сберёг.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not headers.get("content-type", "").startswith("application/json"):
            await self.app(scope, receive, send)
            return

        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._refuse(send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        async def watched_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, watched_send)
        except _BodyTooLargeError:
            # Если ответ уже начался, менять его поздно: соединение просто обрывается.
            # Такого быть не должно — тело читают до формирования ответа.
            if not started:
                await self._refuse(send)

    async def _refuse(self, send: Send) -> None:
        code = ErrorCode.UPLOAD_TOO_LARGE
        response = JSONResponse(
            status_code=STATUS_CODES[code],
            content={
                "detail": {
                    "code": code.value,
                    "message": f"Тело запроса больше {self.max_bytes} байт",
                }
            },
        )
        await response({"type": "http"}, _no_receive, send)


async def _no_receive() -> Message:
    """Отказ тела не читает: получатель ему не нужен."""
    return {"type": "http.disconnect"}
