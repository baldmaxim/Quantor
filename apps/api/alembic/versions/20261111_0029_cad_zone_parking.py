"""Машино-места паркинга в зонах листа CAD: вид parking_space и тип по легенде

Revision ID: 0029_cad_zone_parking
Revises: 0028_cad_sheet_risers
Create Date: 2026-11-11

В `cad_zones` добавляется вид `parking_space` и колонка `parking_type` (тип места по легенде
листа). Тип задан у места и только у него. Откат удаляет места паркинга и колонку.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_cad_zone_parking"
down_revision: str | None = "0028_cad_sheet_risers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = ("room_apartment", "room_mop", "door")
NEW_KINDS = (*OLD_KINDS, "parking_space")
# Те же значения, что `PARKING_TYPE_VALUES` в `app/models/cad_zone.py`.
PARKING_TYPES = (
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


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column("cad_zones", sa.Column("parking_type", sa.String(length=32), nullable=True))
    op.drop_constraint(op.f("ck_cad_zones_kind_known"), "cad_zones", type_="check")
    op.create_check_constraint(
        op.f("ck_cad_zones_kind_known"), "cad_zones", f"kind in ({_quoted(NEW_KINDS)})"
    )
    op.create_check_constraint(
        op.f("ck_cad_zones_parking_type_known"),
        "cad_zones",
        f"parking_type is null or parking_type in ({_quoted(PARKING_TYPES)})",
    )
    op.create_check_constraint(
        op.f("ck_cad_zones_parking_type_matches_kind"),
        "cad_zones",
        "(kind = 'parking_space') = (parking_type is not null)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM cad_zones WHERE kind = 'parking_space'")
    op.drop_constraint(op.f("ck_cad_zones_parking_type_matches_kind"), "cad_zones", type_="check")
    op.drop_constraint(op.f("ck_cad_zones_parking_type_known"), "cad_zones", type_="check")
    op.drop_constraint(op.f("ck_cad_zones_kind_known"), "cad_zones", type_="check")
    op.create_check_constraint(
        op.f("ck_cad_zones_kind_known"), "cad_zones", f"kind in ({_quoted(OLD_KINDS)})"
    )
    op.drop_column("cad_zones", "parking_type")
