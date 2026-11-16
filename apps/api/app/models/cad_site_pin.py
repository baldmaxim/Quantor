"""Ручная привязка корпуса к площадке по двум парам точек (ADR-0052).

Человек указывает две точки на листе корпуса (источник) и те же две точки на листе уже
поставленного здания, обычно подземной части (цель). Точки - числа в мм кадра своего вида (DXF
листа). Сервер выводит перевод «вид источника -> вид цели»: поворот и сдвиг, без масштаба и
зеркала. Запись неизменяема, кроме отзыва (`revoked_*`, как у `CadDecision`); изменение - отзыв и
новая запись. Действующая привязка на лист-источник одна (частичный уникальный индекс). Лист
опознаётся тройкой «ревизия документа, страница, вид»: при новой ревизии привязка не применяется.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

MAX_SITE_PIN_TEXT: Final = 2000


def _revision_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )


def _mm() -> Mapped[float]:
    return mapped_column(Float, nullable=False)


class CadSitePin(Base):
    __tablename__ = "cad_site_pins"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_revision_id: Mapped[uuid.UUID] = _revision_fk()
    source_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_view: Mapped[int] = mapped_column(Integer, nullable=False)
    target_revision_id: Mapped[uuid.UUID] = _revision_fk()
    target_page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_view: Mapped[int] = mapped_column(Integer, nullable=False)
    # Две точки источника и две точки цели, мм кадра своего вида.
    source_x1_mm: Mapped[float] = _mm()
    source_y1_mm: Mapped[float] = _mm()
    source_x2_mm: Mapped[float] = _mm()
    source_y2_mm: Mapped[float] = _mm()
    target_x1_mm: Mapped[float] = _mm()
    target_y1_mm: Mapped[float] = _mm()
    target_x2_mm: Mapped[float] = _mm()
    target_y2_mm: Mapped[float] = _mm()
    # Выводит сервер: `q = R(rotation_deg) · p + (offset_x_mm, offset_y_mm)`.
    rotation_deg: Mapped[float] = _mm()
    offset_x_mm: Mapped[float] = _mm()
    offset_y_mm: Mapped[float] = _mm()
    baseline_mm: Mapped[float] = _mm()
    residual_mm: Mapped[float] = _mm()
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id")
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "uq_cad_site_pins_active_source",
            "source_revision_id",
            "source_page_index",
            "source_view",
            unique=True,
            postgresql_where=text("revoked_at is null"),
        ),
        Index("ix_cad_site_pins_project_id", "project_id"),
        CheckConstraint(
            "source_page_index >= 0 and source_view >= 0 "
            "and target_page_index >= 0 and target_view >= 0",
            name="sheet_address_non_negative",
        ),
        CheckConstraint(
            "(source_revision_id, source_page_index, source_view) "
            "<> (target_revision_id, target_page_index, target_view)",
            name="source_differs_from_target",
        ),
        CheckConstraint("baseline_mm > 0 and residual_mm >= 0", name="distances_valid"),
        CheckConstraint(
            f"note is null or char_length(note) <= {MAX_SITE_PIN_TEXT}", name="note_length"
        ),
        CheckConstraint(
            "(revoked_at is null) = (revoked_by is null) "
            "and (revoke_reason is null or revoked_at is not null)",
            name="revoke_consistent",
        ),
        CheckConstraint(
            f"revoke_reason is null or char_length(revoke_reason) <= {MAX_SITE_PIN_TEXT}",
            name="revoke_reason_length",
        ),
    )
