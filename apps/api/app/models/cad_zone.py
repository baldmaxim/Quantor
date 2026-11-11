"""Зоны листа, размеченные человеком во вкладке CAD: помещения, двери, машино-места паркинга.

Зона — эталон разметки для движка CAD и вход будущего расчёта отделки, а не измерение:
в итоги обмера (`Measurement`) она не входит и туда не пишется. Координаты — нормализованные
точки листа от левого верхнего угла (ADR-0008), как у обмера. Площадь, периметр и ширина в
таблице не хранятся: сервер считает их при чтении по канонической геометрии страницы и
действующей калибровке листа.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, uuid_pk

# Те же значения, что `CadZoneKind` в `app/contracts/cad_zones.py`.
ZONE_KIND_VALUES: tuple[str, ...] = ("room_apartment", "room_mop", "door", "parking_space")

# Тип машино-места по легенде листа; те же значения, что `CadParkingType` в контрактах.
PARKING_TYPE_VALUES: tuple[str, ...] = (
    "permanent",
    "temporary",
    "guest",
    "medium",
    "medium_guest",
    "large",
    "large_guest",
    "mgn_m1_3",
    "mgn_m4",
    "unknown",
)

DOOR_HEIGHT_MIN_MM = 1500
DOOR_HEIGHT_MAX_MM = 3500

_KIND_CHECK = "kind in (" + ", ".join(f"'{value}'" for value in ZONE_KIND_VALUES) + ")"
_PARKING_TYPE_CHECK = (
    "parking_type is null or parking_type in ("
    + ", ".join(f"'{value}'" for value in PARKING_TYPE_VALUES)
    + ")"
)


class CadZone(TimestampMixin, Base):
    __tablename__ = "cad_zones"

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
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    apartment_no: Mapped[str | None] = mapped_column(Text)
    room_mark: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    # [[x, y], ...] в [0, 1]; многоугольник не замыкается повтором первой точки, у двери ровно две.
    points: Mapped[list[list[float]]] = mapped_column(pg.JSONB, nullable=False)
    door_height_mm: Mapped[int | None] = mapped_column(Integer)
    # Тип машино-места паркинга; задан у `parking_space` и только у него.
    parking_type: Mapped[str | None] = mapped_column(String(32))

    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        Index("ix_cad_zones_revision_page", "revision_id", "page_index"),
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint(_KIND_CHECK, name="kind_known"),
        CheckConstraint(
            "kind <> 'room_apartment' or (apartment_no is not null and apartment_no <> '')",
            name="apartment_no_required",
        ),
        CheckConstraint(
            "door_height_mm is null or (kind = 'door' and door_height_mm between "
            f"{DOOR_HEIGHT_MIN_MM} and {DOOR_HEIGHT_MAX_MM})",
            name="door_height_valid",
        ),
        CheckConstraint(_PARKING_TYPE_CHECK, name="parking_type_known"),
        CheckConstraint(
            "(kind = 'parking_space') = (parking_type is not null)",
            name="parking_type_matches_kind",
        ),
        CheckConstraint("jsonb_typeof(points) = 'array'", name="points_is_array"),
        CheckConstraint(
            "(kind = 'door' and jsonb_array_length(points) = 2) or "
            "(kind <> 'door' and jsonb_array_length(points) >= 3)",
            name="points_count",
        ),
    )
