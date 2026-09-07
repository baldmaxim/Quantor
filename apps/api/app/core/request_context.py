"""Сведения о текущем запросе в contextvars: доступны логам, обработчикам ошибок и
журналу действий без проброса аргументом через весь сервисный слой."""

from __future__ import annotations

from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Адрес и клиент нужны журналу административных действий: разбор инцидента без них
# сводится к «кто-то что-то поменял».
_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)
_user_agent: ContextVar[str | None] = ContextVar("user_agent", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_client_ip() -> str | None:
    return _client_ip.get()


def get_user_agent() -> str | None:
    return _user_agent.get()


def set_client(ip: str | None, user_agent: str | None) -> None:
    _client_ip.set(ip)
    # Строка агента бывает длиннее колонки журнала; обрезаем здесь, а не при записи,
    # чтобы длина не зависела от места вызова.
    _user_agent.set(user_agent[:500] if user_agent else None)
