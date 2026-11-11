"""Параметры конструкций и уровни листа в контуре «Конструкции CAD» (ADR-0038 п. 4).

Это данные человека, а не результат скрипта. Привязка — к листу (ревизия, страница, вид), а не
к заданию `cad_walls`: id конструкции в `walls.json` стабилен (хеш вида, номинала, центроида и
площади), поэтому параметры сами переходят на новое задание того же листа. В итоги обмера,
таблицы MEP и calc эти таблицы не входят.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, uuid_pk

CONSTRUCTION_KEY_MAX = 32


class CadConstructionProps(TimestampMixin, Base):
    """Параметры одной конструкции листа: материал, блок, шов, назначение и т. п."""

    __tablename__ = "cad_construction_props"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    # id конструкции из walls.json.
    construction_key: Mapped[str] = mapped_column(String(CONSTRUCTION_KEY_MAX), nullable=False)
    # Поля схемы `CadConstructionProps` (app/contracts/cad_constructions.py); пустые не хранятся.
    props: Mapped[dict[str, object]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    accepted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "page_index",
            "view",
            "construction_key",
            name="uq_cad_construction_props_sheet_key",
        ),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint(
            f"char_length(construction_key) between 1 and {CONSTRUCTION_KEY_MAX}",
            name="construction_key_length",
        ),
        CheckConstraint("jsonb_typeof(props) = 'object'", name="props_is_object"),
    )


class CadSheetLevels(Base):
    """Переопределения человека для высот листа; пустое поле — значение из walls.json."""

    __tablename__ = "cad_sheet_levels"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    view: Mapped[int] = mapped_column(Integer, nullable=False)
    floor_height_mm: Mapped[int | None] = mapped_column(Integer)
    slab_thickness_mm: Mapped[int | None] = mapped_column(Integer)
    door_height_mm: Mapped[int | None] = mapped_column(Integer)
    # Отметка этажа = верх плиты, мм (ADR-0039).
    floor_elevation_mm: Mapped[int | None] = mapped_column(Integer)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("revision_id", "page_index", "view", name="uq_cad_sheet_levels_sheet"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("view >= 0", name="view_non_negative"),
        CheckConstraint(
            "floor_height_mm is null or floor_height_mm between 2000 and 6000",
            name="floor_height_range",
        ),
        CheckConstraint(
            "slab_thickness_mm is null or slab_thickness_mm between 100 and 1000",
            name="slab_thickness_range",
        ),
        CheckConstraint(
            "door_height_mm is null or door_height_mm between 1500 and 3500",
            name="door_height_range",
        ),
        CheckConstraint(
            "floor_elevation_mm is null or floor_elevation_mm between -100000 and 500000",
            name="floor_elevation_range",
        ),
    )
