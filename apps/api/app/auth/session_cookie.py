"""Обновление cookie сеанса при скользящем сроке.

Резолвер продлевает сеанс в базе и кладёт в `scope["state"]` сведения для cookie. Здесь,
на старте ответа, они превращаются в заголовки Set-Cookie с новым `max_age`.

Чистое ASGI-middleware, а не `BaseHTTPMiddleware`: потоковые выгрузки не должны
буферизоваться ради добавления заголовка.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.cookies import set_session_cookies
from app.core.config import Settings

STATE_KEY = "session_cookie_refresh"


@dataclass(frozen=True, slots=True)
class SessionCookieRefresh:
    """Что обновить в cookie: токен сеанса и новый срок в секундах."""

    token: str
    max_age: int


class SessionCookieMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Словарь создаётся здесь, чтобы `request.state` ниже по стеку писал в тот же объект.
        state = scope.setdefault("state", {})

        async def send_with_cookies(message: Message) -> None:
            if message["type"] == "http.response.start":
                refresh = state.get(STATE_KEY)
                if isinstance(refresh, SessionCookieRefresh):
                    self._extend(scope, message, refresh)
            await send(message)

        await self.app(scope, receive, send_with_cookies)

    def _extend(self, scope: Scope, message: Message, refresh: SessionCookieRefresh) -> None:
        name = self.settings.auth_cookie_name.encode("latin-1")
        headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
        # Выход стирает cookie, вход выдаёт новую: их ответ не перебиваем.
        for key, value in headers:
            if key.lower() == b"set-cookie" and value.startswith(name + b"="):
                return

        raw_cookies = Headers(scope=scope).get("cookie")
        csrf_value = (
            cookie_parser(raw_cookies).get(self.settings.auth_csrf_cookie_name)
            if raw_cookies
            else None
        )
        carrier = Response()
        set_session_cookies(
            carrier,
            self.settings,
            session_token=refresh.token,
            csrf_token=csrf_value,
            max_age=refresh.max_age,
        )
        headers.extend(
            (key, value) for key, value in carrier.raw_headers if key.lower() == b"set-cookie"
        )
        message["headers"] = headers
