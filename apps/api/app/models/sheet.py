"""Лист документа и распознанные области на нём."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import RegionShape
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.document import DocumentRevision
    from app.models.page_geometry import PageGeometry


class Sheet(CreatedAtMixin, Base):
    """Страница документа. Нумерация с нуля, как в исходном пакете."""

    __tablename__ = "sheets"

    id: Mapped[uuid.UUID] = uuid_pk()
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )

    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_label: Mapped[str | None] = mapped_column(String(64))
    width_px: Mapped[int | None] = mapped_column(Integer)
    height_px: Mapped[int | None] = mapped_column(Integer)
    rotation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    sheet_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    revision: Mapped[DocumentRevision] = relationship(back_populates="sheets")
    regions: Mapped[list[Region]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", passive_deletes=True
    )
    # Каноническая геометрия страницы (ADR-0016). Пусто — не извлечена; частично
    # извлечённой не бывает. Именно она, а не width_px, участвует в расчёте величин.
    geometry: Mapped[PageGeometry | None] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("revision_id", "page_index", name="uq_sheets_revision_id_page_index"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("rotation in (0, 90, 180, 270)", name="rotation_allowed"),
    )


class Region(CreatedAtMixin, Base):
    """Область, которую увидела распознавалка.

    Это свидетельство, а не намерение: Region никогда не превращается в Measurement и не
    переиспользуется под обмеры (ADR-0008).

    Координаты нормализованы от левого верхнего угла страницы: [x0, y0, x1, y1] в диапазоне [0, 1].
    """

    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = uuid_pk()
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("sheets.id", ondelete="CASCADE"), nullable=False
    )

    external_block_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int | None] = mapped_column(Integer)

    # Тип области приходит из внешнего пакета (text, image, stamp, …) и может пополняться
    # без изменения схемы, поэтому это строка, а не перечисление портала.
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    shape_type: Mapped[RegionShape] = mapped_column(
        str_enum(RegionShape, name="shape_type"),
        nullable=False,
    )

    coords_norm: Mapped[list[float]] = mapped_column(pg.JSONB, nullable=False)
    polygon_points: Mapped[list[list[float]] | None] = mapped_column(pg.JSONB)

    recognition_status: Mapped[str | None] = mapped_column(String(64))
    raw_content_md: Mapped[str | None] = mapped_column(Text)

    # Всё, что пришло из пакета и не разложено по колонкам: crop_url, export_status и прочее.
    legacy_metadata: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    sheet: Mapped[Sheet] = relationship(back_populates="regions")

    __table_args__ = (
        UniqueConstraint(
            "sheet_id", "external_block_id", name="uq_regions_sheet_id_external_block_id"
        ),
        Index("ix_regions_sheet_id_block_type", "sheet_id", "block_type"),
        Index("ix_regions_sheet_id_ordinal", "sheet_id", "ordinal"),
    )
