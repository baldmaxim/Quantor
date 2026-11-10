"""Решения человека по результатам CAD (ADR-0036 п. 8): одобрение вида и принятие трасс.

Запись не правится и не удаляется. `view_approval` — человек посмотрел DXF вида и открытых
замечаний нет, по нему можно строить трассы; `mep_acceptance` — человек принял трассы этажа
целиком, по нему открывается скачивание DXF трасс. `artifact_sha256` — DXF, на который решение
дано: решение не переносится на другой файл. Отзыв (`revoked_*`) ставится один раз и снимает
действие решения, история остаётся; действующее решение на вид одно (частичный уникальный
индекс по неотозванным), после отзыва решение даётся заново - новой записью.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    DateTime,
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

DECISION_VIEW_APPROVAL: Final = "view_approval"
DECISION_MEP_ACCEPTANCE: Final = "mep_acceptance"
DECISION_KINDS: Final = (DECISION_VIEW_APPROVAL, DECISION_MEP_ACCEPTANCE)
MAX_DECISION_COMMENT: Final = 2000

_KIND_CHECK = "kind in (" + ", ".join(f"'{value}'" for value in DECISION_KINDS) + ")"


class CadDecision(Base):
    __tablename__ = "cad_decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    comment: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id")
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "uq_cad_decisions_active_kind_job_attempt_page_view",
            "kind",
            "job_id",
            "attempt",
            "page_index",
            "view",
            unique=True,
            postgresql_where=text("revoked_at is null"),
        ),
        Index("ix_cad_decisions_job_id", "job_id"),
        CheckConstraint(_KIND_CHECK, name="kind_known"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint("artifact_sha256 ~ '^[0-9a-f]{64}$'", name="artifact_sha256_hex"),
        CheckConstraint(
            f"comment is null or char_length(comment) <= {MAX_DECISION_COMMENT}",
            name="comment_length",
        ),
        CheckConstraint(
            "(revoked_at is null) = (revoked_by is null) "
            "and (revoke_reason is null or revoked_at is not null)",
            name="revoke_consistent",
        ),
        CheckConstraint(
            f"revoke_reason is null or char_length(revoke_reason) <= {MAX_DECISION_COMMENT}",
            name="revoke_reason_length",
        ),
    )
