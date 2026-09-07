"""Защита от подделки межсайтового запроса.

Двойной токен: одно и то же значение лежит в доступной сценарию cookie и присылается
заголовком. Чужая страница может заставить браузер отправить cookie, но прочитать её
и повторить заголовком — нет.

Почему не хватает `SameSite=Lax`. Портал на `localhost:3000` и API на `localhost:8000` —
это **один site**: порт в его определение не входит. То же верно для `app.example.ru`
и `api.example.ru`. То есть запрос между ними не межсайтовый, и `SameSite` его не
отсекает. Полагаться здесь на него значит защищаться от угрозы, которой в этой топологии
нет, и не защищаться от той, которая есть.

Проверка касается только сеансов в cookie. Запрос с `Authorization: Bearer` браузер сам
не подписывает, подделывать нечего.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Final

from app.errors import DomainError, ErrorCode

CSRF_HEADER: Final = "X-CSRF-Token"

# Методы, не меняющие состояние. HEAD и OPTIONS входят: их шлёт браузер сам, в том числе
# предварительным запросом CORS.
SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

_TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(_TOKEN_BYTES)


def verify(method: str, cookie_value: str | None, header_value: str | None) -> None:
    """Проверяет подтверждение небезопасного запроса.

    Сравнение через `compare_digest`: обычное `==` завершается на первом несовпавшем байте
    и по времени ответа выдаёт, сколько символов угадано.
    """
    if method.upper() in SAFE_METHODS:
        return
    if not cookie_value or not header_value:
        raise DomainError(
            ErrorCode.CSRF_FAILED,
            f"Небезопасный запрос требует заголовка {CSRF_HEADER}",
        )
    if not hmac.compare_digest(cookie_value, header_value):
        raise DomainError(ErrorCode.CSRF_FAILED)
