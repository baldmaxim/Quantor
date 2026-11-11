"""Cookie сеанса: единое место, где задаются их атрибуты.

Выдаёт cookie и вход (`api/v1/auth.py`), и продление сеанса при активности
(`session_cookie.py`): атрибуты обязаны совпадать, иначе браузер заведёт вторую cookie
с тем же именем вместо обновления первой.
"""

from __future__ import annotations

from starlette.responses import Response

from app.core.config import Settings


def set_session_cookies(
    response: Response,
    settings: Settings,
    *,
    session_token: str,
    csrf_token: str | None,
    max_age: int,
) -> None:
    """Ставит cookie сеанса и, если токен задан, cookie подтверждения."""
    # Сеанс — HttpOnly: сценарию на странице он недоступен, и кража через XSS не даёт токен.
    response.set_cookie(
        settings.auth_cookie_name,
        session_token,
        httponly=True,
        domain=settings.auth_cookie_domain or None,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        max_age=max_age,
    )
    if csrf_token is None:
        return
    # Подтверждение — наоборот, читаемое: интерфейс обязан повторить его заголовком.
    response.set_cookie(
        settings.auth_csrf_cookie_name,
        csrf_token,
        httponly=False,
        domain=settings.auth_cookie_domain or None,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        max_age=max_age,
    )
