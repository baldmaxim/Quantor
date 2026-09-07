"""Сеансы работы в браузере.

В cookie уходит случайный непрозрачный токен, в базе лежит его SHA-256. Дамп базы не даёт
войти ни в один сеанс, а выход и отзыв администратором работают по-настоящему — чего
самодостаточный токен в cookie не умеет в принципе (ADR-0012).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthSession

# 32 байта энтропии: перебор по сети бессмыслен, а длина cookie остаётся разумной.
_TOKEN_BYTES = 32

# Свежесть отметки последней активности. Обновлять её на каждом запросе — значит писать
# в базу при каждом чтении списка проектов; выигрыша в диагностике это не даёт.
_TOUCH_INTERVAL = timedelta(minutes=5)


def new_token() -> str:
    """Непрозрачный токен для cookie."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 токена. Сравнение идёт по хешу, сам токен в базу не попадает."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    ttl_seconds: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> tuple[AuthSession, str]:
    """Заводит сеанс и возвращает его вместе с токеном для cookie.

    Токен возвращается ровно один раз — восстановить его из базы нельзя.
    """
    token = new_token()
    now = datetime.now(UTC)
    row = AuthSession(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(seconds=ttl_seconds),
        last_seen_at=now,
        ip=ip,
        # Строка агента бывает длиннее колонки; обрезаем, а не роняем вход.
        user_agent=user_agent[:500] if user_agent else None,
    )
    session.add(row)
    await session.flush()
    return row, token


async def resolve(session: AsyncSession, token: str) -> AuthSession | None:
    """Действующий сеанс по токену из cookie.

    Отозванный и просроченный неотличимы для вызывающего намеренно: и то и другое означает
    «войдите снова», а разница интересна только журналу.
    """
    row = (
        await session.execute(
            select(AuthSession).where(AuthSession.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= datetime.now(UTC):
        return None
    return row


async def touch(session: AsyncSession, row: AuthSession) -> None:
    """Отмечает активность, но не чаще, чем раз в интервал."""
    now = datetime.now(UTC)
    if row.last_seen_at is not None and now - row.last_seen_at < _TOUCH_INTERVAL:
        return
    row.last_seen_at = now


async def revoke(session: AsyncSession, row: AuthSession) -> None:
    """Гасит сеанс. Повторный вызов безобиден."""
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Гасит все сеансы личности. Нужно при отключении пользователя и разборе инцидента."""
    rows = (
        (
            await session.execute(
                select(AuthSession).where(
                    AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    return len(rows)
