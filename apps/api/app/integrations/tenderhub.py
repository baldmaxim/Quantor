"""Клиент TenderHUB.

Читает тендеры по ключу доступа. Только чтение: ключ выдан на просмотр, и портал
ничего не пишет на ту сторону.

Три правила, которые здесь важнее остального:

- **Ключ уходит единственным заголовком `X-API-Key`.** `Authorization: Bearer` — это
  путь сессии человека; исправный ключ, посланный так, получает `401` и уводит
  диагностику в ложном направлении.
- **Ключ не попадает никуда, кроме заголовка.** Ни в лог, ни в сообщение об ошибке,
  ни в ответ API. В журнал пишется адрес и код ответа, не более.
- **Отказ внешней системы — это отказ внешней системы.** Он превращается в свой код
  ошибки, а не в общий «что-то пошло не так»: пользователю нужно понимать, чинить ли
  ключ, ждать ли снятия лимита или звать администратора.

Сметные строки отсюда не читаются: на Stage 1 портал не считает объёмы и не ведёт смету
(см. границы этапа в CLAUDE.md). Берётся только то, что делает тендер проектом, —
номер, название и заказчик.
"""

from __future__ import annotations

from typing import Any, Final, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.logging import get_logger
from app.errors import DomainError, ErrorCode

log = get_logger(__name__)

# Список тендеров, доступный ключу. Маршрут /api/v1/tenders — под сессией человека,
# ключу он не открыт, и подставлять его вместо этого бессмысленно.
TENDERS_BRIEF: Final = "/api/v1/tenders/brief"
TENDER_OVERVIEW: Final = "/api/v1/tenders/{tender_id}/overview"


class TenderBrief(BaseModel):
    """Строка списка тендеров.

    extra='ignore': на той стороне поля добавляют, и новое поле не должно ронять портал.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    tender_number: str | None = None
    title: str = Field(default="")
    client_name: str | None = None
    version: int | None = None
    is_archived: bool = False
    construction_scope: str | None = None
    submission_deadline: str | None = None
    updated_at: str | None = None


class TenderHubClient:
    """Тонкая обёртка над HTTP. Живёт на время запроса и закрывается вместе с ним."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not settings.tenderhub_enabled:
            raise DomainError(ErrorCode.TENDERHUB_DISABLED)

        self._client = httpx.AsyncClient(
            transport=transport,
            base_url=settings.tenderhub_api_url.rstrip("/"),
            timeout=settings.tenderhub_timeout_seconds,
            headers={
                "X-API-Key": settings.tenderhub_api_token.get_secret_value(),
                "Accept": "application/json",
            },
            follow_redirects=False,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def list_tenders(self, *, search: str | None = None) -> list[TenderBrief]:
        params: dict[str, str] = {"is_archived": "false"}
        if search:
            params["search"] = search

        payload = await self._get(TENDERS_BRIEF, params=params)
        rows = payload if isinstance(payload, list) else []
        return [TenderBrief.model_validate(row) for row in rows if isinstance(row, dict)]

    async def get_tender(self, tender_id: str) -> TenderBrief:
        payload = await self._get(TENDER_OVERVIEW.format(tender_id=tender_id))
        if not isinstance(payload, dict):
            raise DomainError(ErrorCode.TENDERHUB_UNAVAILABLE, "Ответ TenderHUB не разобран")
        return TenderBrief.model_validate(payload)

    async def _get(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as error:
            raise DomainError(ErrorCode.TENDERHUB_UNAVAILABLE, "TenderHUB не ответил") from error
        except httpx.HTTPError as error:
            # Текст httpx безопасен: он содержит адрес, но не заголовки.
            raise DomainError(ErrorCode.TENDERHUB_UNAVAILABLE, str(error)) from error

        if response.status_code >= 400:
            raise _failure(response, path)

        return _envelope(response)


def _failure(response: httpx.Response, path: str) -> DomainError:
    """Переводит отказ TenderHUB в код портала.

    Разбор кодов взят из документации ключа: 401 с разным текстом означает две разные
    поломки, и путать их дорого — в одном случае чинится способ передачи, в другом нужен
    новый ключ.
    """
    code = _upstream_code(response)
    log.warning(
        "tenderhub_request_failed",
        path=path,
        status=response.status_code,
        upstream_code=code,
    )

    match response.status_code:
        case 401:
            return DomainError(ErrorCode.TENDERHUB_AUTH_FAILED)
        case 403:
            return DomainError(ErrorCode.TENDERHUB_FORBIDDEN)
        case 404:
            return DomainError(ErrorCode.TENDERHUB_TENDER_NOT_FOUND)
        case 429:
            return DomainError(ErrorCode.TENDERHUB_RATE_LIMITED)
        case _:
            return DomainError(ErrorCode.TENDERHUB_UNAVAILABLE)


def _upstream_code(response: httpx.Response) -> str | None:
    """Код ошибки в формате RFC 7807. Нужен только журналу — наружу он не уходит."""
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("code") if isinstance(body, dict) else None


def _envelope(response: httpx.Response) -> Any:
    """Разворачивает конверт `{"data": …}`.

    Ответ не-JSON означает, что вместо TenderHUB ответил прокси, — это отдельная поломка,
    и молча отдавать пустой список нельзя.
    """
    try:
        body = response.json()
    except ValueError as error:
        raise DomainError(
            ErrorCode.TENDERHUB_UNAVAILABLE, "TenderHUB ответил не JSON — проверьте адрес"
        ) from error

    return body.get("data") if isinstance(body, dict) and "data" in body else body
