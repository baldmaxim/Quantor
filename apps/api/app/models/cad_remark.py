"""Замечания проверяющего к виду результата CAD (QA-контур).

Замечание — след человека, а не измерение и не инженерная приёмка: в расчёт оно не входит
(`engineering_acceptance` всегда false). Привязано к конкретной попытке задания, странице и виду:
замечания другой попытки или вида не смешиваются. Прямоугольник — точки исходного PDF от левого
верхнего угла страницы (`pdf_pt_top_left`, ADR-0008).

`remark_key` — идентификатор замечания, который выдаёт клиент (UUID v4): он же `id` в файле обмена
`quantor.cad-remarks.v1`, и по нему идёт слияние при импорте.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, uuid_pk

# Те же значения, что `REMARK_TYPES` в apps/web/src/lib/cad/remarks.ts.
REMARK_TYPE_VALUES: tuple[str, ...] = (
    "missing_wall",
    "false_wall",
    "missing_door",
    "door_geometry",
    "missing_gate",
    "missing_glazing",
    "monolith",
    "room_boundary",
    "wrong_class",
    "other",
)
REMARK_STATUS_VALUES: tuple[str, ...] = ("open", "resolved")

_TYPE_CHECK = "type in (" + ", ".join(f"'{value}'" for value in REMARK_TYPE_VALUES) + ")"


class CadRemark(TimestampMixin, Base):
    __tablename__ = "cad_remarks"

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
    job_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 DXF вида на момент замечания; NULL — у вида DXF не было.
    dxf_sha256: Mapped[str | None] = mapped_column(Text)

    remark_key: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)

    bbox_x0: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y0: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x1: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y1: Mapped[float] = mapped_column(Float, nullable=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "attempt",
            "page_index",
            "view",
            "remark_key",
            name="uq_cad_remarks_job_attempt_page_view_key",
        ),
        Index("ix_cad_remarks_job_attempt_page_view", "job_id", "attempt", "page_index", "view"),
        CheckConstraint("attempt >= 1", name="attempt_positive"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint(
            "dxf_sha256 is null or dxf_sha256 ~ '^[0-9a-f]{64}$'", name="dxf_sha256_hex"
        ),
        CheckConstraint("char_length(remark_key) between 1 and 64", name="remark_key_length"),
        CheckConstraint(_TYPE_CHECK, name="type_known"),
        CheckConstraint("char_length(comment) <= 4000", name="comment_length"),
        CheckConstraint("reviewer is null or char_length(reviewer) <= 200", name="reviewer_length"),
        CheckConstraint("status in ('open', 'resolved')", name="status_known"),
        CheckConstraint(
            "bbox_x0 >= 0 and bbox_y0 >= 0 and bbox_x1 > bbox_x0 and bbox_y1 > bbox_y0",
            name="bbox_valid",
        ),
    )
