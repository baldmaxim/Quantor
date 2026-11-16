"""Профиль оформления тома: создание версий и чтение (ADR-0049, решения 1, 2, 5, 6).

Версии неизменяемы: сервис только добавляет. Номер следующей версии назначается под блокировкой
строки профиля; первый профиль тома защищён уникальностью `document_id`. Хеш считается от
канонического JSON объекта `style` - как `operator_profile_hash` в движке.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_style_profiles import (
    STYLE_SCHEMA,
    CadStyleProfileRead,
    CadStyleVersionBrief,
    CadStyleVersionRead,
    CadStyleVersionWrite,
)
from app.errors import DomainError, ErrorCode
from app.models import CadStyleProfile, CadStyleProfileVersion


def profile_key_for(document_id: uuid.UUID) -> str:
    """`d-<32 hex>`: 34 символа, внутри `[A-Za-z0-9._-]{1,64}`."""
    return f"d-{document_id.hex}"


def style_sha256(style: Mapping[str, object]) -> str:
    canonical = json.dumps(style, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_style(profile_key: str, version: int, profile: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema": STYLE_SCHEMA,
        "id": profile_key,
        "version": version,
        "profile": dict(profile),
    }


def _version_read(row: CadStyleProfileVersion) -> CadStyleVersionRead:
    return CadStyleVersionRead(
        version=row.version,
        title=row.title,
        style=row.style,
        sha256=row.sha256,
        source=row.source,
        created_at=row.created_at,
        created_by=row.created_by,
    )


async def _find_profile(
    session: AsyncSession, *, workspace_id: uuid.UUID, document_id: uuid.UUID, lock: bool = False
) -> CadStyleProfile | None:
    query = select(CadStyleProfile).where(
        CadStyleProfile.workspace_id == workspace_id, CadStyleProfile.document_id == document_id
    )
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()


async def get_profile(
    session: AsyncSession, *, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> CadStyleProfileRead | None:
    profile = await _find_profile(session, workspace_id=workspace_id, document_id=document_id)
    if profile is None:
        return None
    rows = (
        (
            await session.execute(
                select(CadStyleProfileVersion)
                .where(CadStyleProfileVersion.profile_id == profile.id)
                .order_by(CadStyleProfileVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    return CadStyleProfileRead(
        id=profile.id,
        document_id=profile.document_id,
        profile_key=profile.profile_key,
        current=_version_read(rows[0]),
        versions=[
            CadStyleVersionBrief(version=row.version, title=row.title, created_at=row.created_at)
            for row in rows
        ],
    )


async def get_version(
    session: AsyncSession, *, workspace_id: uuid.UUID, document_id: uuid.UUID, version: int
) -> CadStyleVersionRead | None:
    profile = await _find_profile(session, workspace_id=workspace_id, document_id=document_id)
    if profile is None:
        return None
    row = (
        await session.execute(
            select(CadStyleProfileVersion).where(
                CadStyleProfileVersion.profile_id == profile.id,
                CadStyleProfileVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    return None if row is None else _version_read(row)


def _conflict(current: int | None) -> DomainError:
    return DomainError(
        ErrorCode.CAD_STYLE_PROFILE_VERSION_CONFLICT,
        issue={"current_version": current},
    )


async def create_version(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: CadStyleVersionWrite,
    created_by: uuid.UUID | None,
) -> CadStyleVersionRead:
    """Создаёт профиль тома, если его нет, и следующую версию."""
    profile = await _find_profile(
        session, workspace_id=workspace_id, document_id=document_id, lock=True
    )
    if profile is None:
        if body.expected_current_version is not None:
            raise _conflict(None)
        # Гонка двух первых записей: проигравшая видит конфликт, а не 500.
        await session.execute(
            pg_insert(CadStyleProfile)
            .values(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                project_id=project_id,
                document_id=document_id,
                profile_key=profile_key_for(document_id),
                created_by=created_by,
            )
            .on_conflict_do_nothing(index_elements=["document_id"])
        )
        profile = await _find_profile(
            session, workspace_id=workspace_id, document_id=document_id, lock=True
        )
        if profile is None:
            raise _conflict(None)
    current = (
        await session.execute(
            select(CadStyleProfileVersion.version)
            .where(CadStyleProfileVersion.profile_id == profile.id)
            .order_by(CadStyleProfileVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current != body.expected_current_version:
        raise _conflict(current)

    number = (current or 0) + 1
    style = build_style(profile.profile_key, number, body.profile.model_dump(mode="json"))
    row = CadStyleProfileVersion(
        profile_id=profile.id,
        version=number,
        title=body.title,
        style=style,
        sha256=style_sha256(style),
        source=body.source.model_dump(mode="json", by_alias=True, exclude_none=True),
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    # PostgreSQL нормализует числа в JSONB: хеш обязан совпасть с тем, что лежит в базе.
    if style_sha256(row.style) != row.sha256:
        raise RuntimeError("sha256 версии профиля не совпал с телом, сохранённым в базе")
    return _version_read(row)
