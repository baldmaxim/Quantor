"""Реестр стояков листа CAD по проекту ИОС (ADR-0041).

Данные человека, а не результат скрипта: человек вводит или подтверждает стояки секции, реестр -
вход задания трасс `cad_mep_route` (генератор cad_mep.v6). Привязка - к листу (ревизия, страница,
вид). В итоги обмера, таблицы MEP и calc таблица не входит.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk


class CadSheetRisers(Base):
    __tablename__ = "cad_sheet_risers"

    id: Mapped[uuid.UUID] = uuid_pk()
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    # Список записей контракта `cad_risers.v1` (CadRiserEntry в виде JSON).
    risers: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("revision_id", "page_index", "view", name="uq_cad_sheet_risers_sheet"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint("jsonb_typeof(risers) = 'array'", name="risers_is_array"),
    )
