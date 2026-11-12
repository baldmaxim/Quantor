"""Короткий внутрипроцессный кэш разбора сеанса: личность, срок сеанса и членства.

Снимает с каждого запроса три SELECT (сеанс, пользователь, членства). В кэше лежат только
неизменяемые данные (`Principal`, примитивы, кортеж `MembershipView`) — ORM-объекты, привязанные
к закрытой сессии, сюда не попадают.

Ключ — SHA-256 токена, сам токен в память кэша не кладётся.

Инвалидация действует в пределах процесса: выход, отзыв сеансов, одобрение и отклонение,
отключение, смена роли и членства сбрасывают кэш целиком (`invalidate_auth_cache`). При
нескольких воркерах uvicorn соседние процессы об этом не знают, поэтому там устаревание
ограничено TTL (`AUTH_CACHE_TTL_SECONDS`, 5 с). Просроченный сеанс из кэша не отдаётся
никогда: срок проверяется при каждом попадании.

На попадании `touch` не вызывается: отметка активности и продление сеанса случаются при
следующем промахе, то есть не реже, чем раз в TTL после истечения записи, а база по-прежнему
обновляется не чаще, чем раз в `_TOUCH_INTERVAL`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.auth.context import Principal

if TYPE_CHECKING:
    # Только для типов: сервис идентичности сам вызывает инвалидацию, цикла быть не должно.
    from app.services.identity import MembershipView

# Срок жизни записи в процессе. Константа модуля: тесты подменяют `time.monotonic`.
AUTH_CACHE_TTL_SECONDS = 5.0

# Предохранитель от разрастания: на портале десятки пользователей, но кэш не должен
# зависеть от этого допущения.
_MAX_ENTRIES = 1024


@dataclass(frozen=True, slots=True)
class AuthCacheEntry:
    """Что известно о сеансе без обращения к базе."""

    principal: Principal
    session_id: uuid.UUID
    session_expires_at: datetime
    # `None` — членства ещё не загружались (их читает `_resolve_workspace`).
    memberships: tuple[MembershipView, ...] | None
    valid_until: float


_entries: dict[str, AuthCacheEntry] = {}


def get_auth_entry(token_hash: str) -> AuthCacheEntry | None:
    """Запись, если она свежа и сеанс не просрочен."""
    entry = _entries.get(token_hash)
    if entry is None:
        return None
    if entry.valid_until <= time.monotonic() or entry.session_expires_at <= datetime.now(UTC):
        _entries.pop(token_hash, None)
        return None
    return entry


def put_auth_entry(
    token_hash: str,
    *,
    principal: Principal,
    session_id: uuid.UUID,
    session_expires_at: datetime,
) -> None:
    """Запоминает результат разбора сеанса (членства добавляются позже)."""
    if len(_entries) >= _MAX_ENTRIES:
        _purge_expired()
        if len(_entries) >= _MAX_ENTRIES:
            _entries.clear()
    _entries[token_hash] = AuthCacheEntry(
        principal=principal,
        session_id=session_id,
        session_expires_at=session_expires_at,
        memberships=None,
        valid_until=time.monotonic() + AUTH_CACHE_TTL_SECONDS,
    )


def set_cached_memberships(token_hash: str, memberships: tuple[MembershipView, ...]) -> None:
    """Дописывает членства в живую запись; срок записи не продлевается."""
    entry = _entries.get(token_hash)
    if entry is not None:
        _entries[token_hash] = replace(entry, memberships=memberships)


def invalidate_auth_cache(token_hash: str | None = None) -> None:
    """Сбрасывает запись по хешу токена; `None` — весь кэш процесса."""
    if token_hash is None:
        _entries.clear()
    else:
        _entries.pop(token_hash, None)


def _purge_expired() -> None:
    now = time.monotonic()
    for key in [key for key, entry in _entries.items() if entry.valid_until <= now]:
        del _entries[key]
