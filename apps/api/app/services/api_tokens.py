"""Персональные API-токены `qtk_…` (ADR-0051): выпуск, список, отзыв, опознание.

Токен — `qtk_` и 40 знаков `secrets.token_urlsafe`; в базе только sha256 и первые 12 знаков для
показа. Токен привязан к пространству и областям (`scopes`: `read`, `tender`, `upload`,
`tender_import`; права токена - права роли владельца, суженные объединением прав его областей).
Отзыв и истечение действуют сразу: токен проверяется по базе при каждом запросе, кэша у него нет.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import (
    API_TOKEN_PERMISSIONS,
    READ_TOKEN_PERMISSIONS,
    TENDER_IMPORT_TOKEN_PERMISSIONS,
    UPLOAD_TOKEN_PERMISSIONS,
    Permission,
    permissions_for,
)
from app.domain import Role
from app.models import ApiToken
from app.models.api_token import API_TOKEN_PREFIX_LENGTH

QTK_PREFIX: Final = "qtk_"
SCOPE_TENDER: Final = "tender"
# API для агентов: только чтение и загрузка документов/модели.
SCOPE_READ: Final = "read"
SCOPE_UPLOAD: Final = "upload"
# Создание объекта по тендеру TenderHUB при пакетном импорте (с `upload` - для дашборда).
SCOPE_TENDER_IMPORT: Final = "tender_import"
SCOPES: Final = (SCOPE_READ, SCOPE_TENDER, SCOPE_UPLOAD, SCOPE_TENDER_IMPORT)
SCOPE_PERMISSIONS: Final[dict[str, frozenset[Permission]]] = {
    SCOPE_READ: READ_TOKEN_PERMISSIONS,
    SCOPE_TENDER: API_TOKEN_PERMISSIONS,
    SCOPE_UPLOAD: UPLOAD_TOKEN_PERMISSIONS,
    SCOPE_TENDER_IMPORT: TENDER_IMPORT_TOKEN_PERMISSIONS,
}
# 30 байт дают ровно 40 знаков urlsafe-base64 без добивки.
_TOKEN_BYTES: Final = 30
# Не чаще раза в минуту: токен используется потоком запросов, а метка нужна человеку в списке.
LAST_USED_INTERVAL: Final = timedelta(minutes=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def permissions_for_scopes(role: Role, scopes: Iterable[str]) -> frozenset[Permission]:
    """Права токена: права роли владельца, суженные объединением прав его областей."""
    allowed: frozenset[Permission] = frozenset()
    for scope in scopes:
        allowed |= SCOPE_PERMISSIONS.get(scope, frozenset())
    return permissions_for(role) & allowed


def normalize_scopes(scopes: Iterable[str]) -> list[str]:
    """Известные области без повторов в порядке SCOPES; пусто - `tender`, как в версии 1."""
    chosen = {scope for scope in scopes if scope in SCOPE_PERMISSIONS}
    return [scope for scope in SCOPES if scope in chosen] or [SCOPE_TENDER]


def is_active(row: ApiToken, *, now: datetime | None = None) -> bool:
    """Токен годен: не отозван и не истёк."""
    moment = now or datetime.now(UTC)
    return row.revoked_at is None and (row.expires_at is None or row.expires_at > moment)


async def create(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    name: str,
    expires_in_days: int | None,
    scopes: Sequence[str] = (SCOPE_TENDER,),
) -> tuple[ApiToken, str]:
    """Новый токен. Полное значение возвращается здесь один раз и нигде не сохраняется."""
    token = QTK_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    row = ApiToken(
        user_id=user_id,
        workspace_id=workspace_id,
        name=name.strip(),
        prefix=token[:API_TOKEN_PREFIX_LENGTH],
        token_hash=hash_token(token),
        scopes=normalize_scopes(scopes),
        expires_at=(
            None if expires_in_days is None else datetime.now(UTC) + timedelta(days=expires_in_days)
        ),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row, token


async def list_for_user(
    session: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> list[ApiToken]:
    rows = await session.scalars(
        select(ApiToken)
        .where(ApiToken.user_id == user_id, ApiToken.workspace_id == workspace_id)
        .order_by(ApiToken.created_at.desc(), ApiToken.id)
    )
    return list(rows)


async def get_own(
    session: AsyncSession, *, token_id: uuid.UUID, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> ApiToken | None:
    row: ApiToken | None = await session.scalar(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.user_id == user_id,
            ApiToken.workspace_id == workspace_id,
        )
    )
    return row


async def revoke(session: AsyncSession, row: ApiToken) -> ApiToken:
    """Отзыв; повторный отзыв не меняет время первого."""
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    return row


async def find_active(session: AsyncSession, token: str) -> ApiToken | None:
    """Токен по значению: найден по хешу, не отозван, не истёк."""
    row = await session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    if row is None or not is_active(row):
        return None
    return row


def needs_touch(row: ApiToken, *, now: datetime | None = None) -> bool:
    moment = now or datetime.now(UTC)
    return row.last_used_at is None or moment - row.last_used_at >= LAST_USED_INTERVAL


async def touch(session: AsyncSession, row: ApiToken) -> None:
    row.last_used_at = datetime.now(UTC)
    await session.flush()
