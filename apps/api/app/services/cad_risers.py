"""Реестр стояков листа CAD (ADR-0041): хранение и канонический файл для генератора трасс.

Реестр вводит или подтверждает человек по проекту ИОС. Задание трасс берёт его входом: файл
`risers.json` контракта `cad_risers.v1` и его sha256 считаются здесь одним способом - и при
постановке задания, и при проверке в cad-worker. Доступ к проекту и ревизии проверяет вызывающий.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_risers import RISERS_SCHEMA, V10_OPTIONAL_FIELDS, CadRiserEntry
from app.models import CadSheetRisers


def entries_to_json(entries: list[CadRiserEntry]) -> list[dict[str, Any]]:
    """Записи для хранения и файла генератора.

    Поля cad_mep.v10 пишутся только заданные: запись без них сериализуется побайтно как до A3
    (все прежние поля, включая `null`), и sha256 реестра - ключ идемпотентности трасс - не меняется.
    """
    return [
        entry.model_dump(
            mode="json",
            exclude={name for name in V10_OPTIONAL_FIELDS if getattr(entry, name) is None},
        )
        for entry in entries
    ]


def registry_bytes(risers: list[dict[str, Any]]) -> bytes:
    """Канонический файл `{"schema":"cad_risers.v1","risers":[...]}`: sort_keys, без пробелов."""
    document = {"schema": RISERS_SCHEMA, "risers": risers}
    return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def registry_sha256(risers: list[dict[str, Any]]) -> str:
    return hashlib.sha256(registry_bytes(risers)).hexdigest()


async def load_row(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int, view: int
) -> CadSheetRisers | None:
    # populate_existing: запись идёт Core-вставкой с обновлением, объекты сессии не отстают.
    row: CadSheetRisers | None = await session.scalar(
        select(CadSheetRisers)
        .where(
            CadSheetRisers.revision_id == revision_id,
            CadSheetRisers.page_index == page_index,
            CadSheetRisers.view == view,
        )
        .execution_options(populate_existing=True)
    )
    return row


async def load_risers(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int, view: int
) -> list[CadRiserEntry]:
    """Реестр листа; нет строки - пустой список."""
    row = await load_row(session, revision_id=revision_id, page_index=page_index, view=view)
    if row is None:
        return []
    return [CadRiserEntry.model_validate(item) for item in row.risers]


async def save_risers(
    session: AsyncSession,
    *,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
    risers: list[CadRiserEntry],
    user_id: uuid.UUID | None,
) -> datetime:
    """Реестр листа заменяется целиком; возвращает время записи."""
    values = {"risers": entries_to_json(risers), "updated_by": user_id}
    statement = insert(CadSheetRisers).values(
        id=uuid.uuid4(), revision_id=revision_id, page_index=page_index, view=view, **values
    )
    updated_at = await session.scalar(
        statement.on_conflict_do_update(
            constraint="uq_cad_sheet_risers_sheet", set_={**values, "updated_at": func.now()}
        ).returning(CadSheetRisers.updated_at)
    )
    if updated_at is None:  # pragma: no cover - upsert с RETURNING всегда возвращает строку
        raise RuntimeError("Реестр стояков не записан")
    return updated_at
