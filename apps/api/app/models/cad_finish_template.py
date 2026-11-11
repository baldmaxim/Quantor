"""Шаблоны отделки помещений проекта в пилоте CAD (ADR-0042).

Шаблон - параметры проекта, которые вводит человек: типы помещений для автоназначения, высота стен
под отделку и слои трёх поверхностей. Количества в таблице не хранятся: ведомость считает сервер
при чтении по геометрии зон и уровням листа. В итоги обмера, calc и MEP таблица не входит.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
from app.models.mixins import uuid_pk

NAME_MAX = 200
WALL_HEIGHT_MIN_MM = 1000
WALL_HEIGHT_MAX_MM = 6000


class CadFinishTemplate(Base):
    __tablename__ = "cad_finish_templates"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX), nullable=False)
    # Список кодов `CadRoomType`: типы помещений, которым шаблон назначается автоматически.
    room_types: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    wall_height_mm: Mapped[int | None] = mapped_column(Integer)
    # Откосы дверных проёмов входят в площадь слоёв стен (ADR-0042, п. 6).
    walls_include_reveals: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Списки слоёв `CadFinishLayer` (app/contracts/cad_finishes.py) в порядке нанесения.
    floor_layers: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    wall_layers: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    ceiling_layers: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_cad_finish_templates_project_name"),
        CheckConstraint("char_length(name) between 1 and 200", name="name_length"),
        CheckConstraint(
            f"wall_height_mm is null or wall_height_mm between {WALL_HEIGHT_MIN_MM} "
            f"and {WALL_HEIGHT_MAX_MM}",
            name="wall_height_valid",
        ),
        CheckConstraint("jsonb_typeof(room_types) = 'array'", name="room_types_is_array"),
        CheckConstraint("jsonb_typeof(floor_layers) = 'array'", name="floor_layers_is_array"),
        CheckConstraint("jsonb_typeof(wall_layers) = 'array'", name="wall_layers_is_array"),
        CheckConstraint("jsonb_typeof(ceiling_layers) = 'array'", name="ceiling_layers_is_array"),
    )
