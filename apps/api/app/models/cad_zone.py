"""Зоны листа, размеченные человеком во вкладке CAD: помещения, двери, машино-места паркинга.

Зона — эталон разметки для движка CAD и вход будущего расчёта отделки, а не измерение:
в итоги обмера (`Measurement`) она не входит и туда не пишется. Координаты — нормализованные
точки листа от левого верхнего угла (ADR-0008), как у обмера. Площадь, периметр и ширина в
таблице не хранятся: сервер считает их при чтении по канонической геометрии страницы и
действующей калибровке листа.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.cad_room_types import ROOM_TYPE_VALUES
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

# Происхождение зоны: `auto` - создана заданием `cad_zones` и человеком не правилась, `human` -
# создана или правлена человеком, `unknown` - строка до миграции 0041, которую нельзя надёжно
# отнести к авторазметке. `unknown` ведёт себя как `human`: автоматически не удаляется.
ZONE_SOURCE_VALUES: tuple[str, ...] = ("auto", "human", "unknown")
# Итог сверки с экспликацией: `failed` не участвует в плите, перегородках и отделке до принятия.
ZONE_QUALITY_VALUES: tuple[str, ...] = ("ok", "review", "failed")

DOOR_HEIGHT_MIN_MM = 1500
DOOR_HEIGHT_MAX_MM = 3500

_KIND_CHECK = "kind in (" + ", ".join(f"'{value}'" for value in ZONE_KIND_VALUES) + ")"
_ROOM_TYPE_CHECK = (
    "room_type is null or room_type in ("
    + ", ".join(f"'{value}'" for value in ROOM_TYPE_VALUES)
    + ")"
)
_SOURCE_CHECK = "source in (" + ", ".join(f"'{value}'" for value in ZONE_SOURCE_VALUES) + ")"
_QUALITY_CHECK = (
    "quality_status in (" + ", ".join(f"'{value}'" for value in ZONE_QUALITY_VALUES) + ")"
)
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
    # Тип помещения, заданный человеком (ADR-0042); пусто - действует тип, выведенный из названия.
    room_type: Mapped[str | None] = mapped_column(String(32))
    # Явно назначенный шаблон отделки; шаблон удалён - назначение снимается.
    finish_template_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("cad_finish_templates.id", ondelete="SET NULL")
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    # Происхождение и сверка с экспликацией (миграция 0041, ревью движка 2026-11-16).
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    # Версия генератора авто-зоны (`cad_mep.vN`); у зоны человека - пусто.
    generator_version: Mapped[str | None] = mapped_column(String(64))
    # Площадь по экспликации листа из zones.json; пусто - экспликации нет.
    expl_area_m2: Mapped[float | None] = mapped_column(Float)
    # Площадь контура по zones.json (масштаб преобразования CAD): только для сверки с
    # экспликацией, величиной зоны не является; после правки контура человеком - пусто.
    generator_area_m2: Mapped[float | None] = mapped_column(Float)
    # Заметки генератора о зоне: список строк.
    notes: Mapped[list[str] | None] = mapped_column(pg.JSONB)
    quality_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ok")
    quality_reason: Mapped[str | None] = mapped_column(Text)
    # Кто и когда принял зону вне допуска (`review`/`failed` -> `ok`).
    quality_accepted_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    quality_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_cad_zones_revision_page", "revision_id", "page_index"),
        Index("ix_cad_zones_finish_template_id", "finish_template_id"),
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
        CheckConstraint(_ROOM_TYPE_CHECK, name="room_type_known"),
        CheckConstraint(_PARKING_TYPE_CHECK, name="parking_type_known"),
        CheckConstraint(_SOURCE_CHECK, name="source_known"),
        CheckConstraint(_QUALITY_CHECK, name="quality_status_known"),
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
