"""Калибровка масштаба чертежа

Revision ID: 0009_scale_calibration
Revises: 0008_page_geometry
Create Date: 2026-09-09

Точки PDF сами по себе ничего не измеряют: чтобы линия превратилась в метры, нужен
коэффициент, и взять его неоткуда, кроме как от человека (ADR-0018).

Коэффициент привязан к точке PDF, а не к нормализованной координате. Прежний контракт
`units_per_normalized` был математически неверен на прямоугольной странице: 0,1 по X и
0,1 по Y — разные расстояния. Таблиц под него не заводили, поэтому мигрировать нечего.

Хранится не только результат, но и доказательство: обе точки, введённое значение с
исходной единицей, вычисленное расстояние и отпечаток геометрии страницы. Строка
неизменяема — исправление создаёт новую калибровку, а старая остаётся, иначе вчерашний
расчёт перестал бы воспроизводиться.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_scale_calibration"
down_revision: str | None = "0008_page_geometry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_KINDS = ("sheet", "region")
_SOURCES = ("manual", "detected_dimension", "imported")
_VERIFICATION = ("unverified", "verified", "disputed")
_UNITS = ("mm", "cm", "m")


def upgrade() -> None:
    op.create_table(
        "scale_calibrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sheet_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope_kind",
            sa.Enum(*_SCOPE_KINDS, name="scale_scope_kind", native_enum=False, length=32),
            server_default="sheet",
            nullable=False,
        ),
        sa.Column("scope_polygon_norm", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # Доказательство: без этих полей осталcя бы коэффициент, про который никто не помнит,
        # откуда он взялся.
        sa.Column("point_a_x", sa.Numeric(precision=9, scale=8), nullable=False),
        sa.Column("point_a_y", sa.Numeric(precision=9, scale=8), nullable=False),
        sa.Column("point_b_x", sa.Numeric(precision=9, scale=8), nullable=False),
        sa.Column("point_b_y", sa.Numeric(precision=9, scale=8), nullable=False),
        sa.Column("input_value", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "input_unit",
            sa.Enum(*_UNITS, name="length_unit", native_enum=False, length=8),
            nullable=False,
        ),
        sa.Column("known_distance_mm", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("page_distance_pt", sa.Numeric(precision=14, scale=6), nullable=False),
        sa.Column("mm_per_pt", sa.Numeric(precision=18, scale=12), nullable=False),
        sa.Column("page_geometry_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source",
            sa.Enum(*_SOURCES, name="scale_source", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "verification_state",
            sa.Enum(*_VERIFICATION, name="verification_state", native_enum=False, length=32),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        # Автор и проверяющий без внешнего ключа намеренно, как и в журнале действий:
        # доказательство обязано пережить удаление личности, о которой рассказывает.
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "calibration_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Нулевой отрезок дал бы деление на ноль, а слишком короткий — коэффициент,
        # в котором ошибка клика превращается в ошибку всех объёмов листа.
        sa.CheckConstraint(
            "page_distance_pt > 0", name=op.f("ck_scale_calibrations_page_distance_positive")
        ),
        sa.CheckConstraint(
            "known_distance_mm > 0", name=op.f("ck_scale_calibrations_known_distance_positive")
        ),
        sa.CheckConstraint(
            "input_value > 0", name=op.f("ck_scale_calibrations_input_value_positive")
        ),
        sa.CheckConstraint("mm_per_pt > 0", name=op.f("ck_scale_calibrations_mm_per_pt_positive")),
        sa.CheckConstraint(
            "point_a_x between 0 and 1 and point_a_y between 0 and 1"
            " and point_b_x between 0 and 1 and point_b_y between 0 and 1",
            name=op.f("ck_scale_calibrations_points_normalized"),
        ),
        sa.CheckConstraint(
            "length(page_geometry_fingerprint) = 64",
            name=op.f("ck_scale_calibrations_fingerprint_length"),
        ),
        # Полигон у листовой калибровки означал бы, что область задана и не действует —
        # состояние, которое нечем объяснить.
        sa.CheckConstraint(
            "scope_kind = 'region' or scope_polygon_norm is null",
            name=op.f("ck_scale_calibrations_scope_polygon_only_for_region"),
        ),
        sa.ForeignKeyConstraint(
            ["sheet_id"],
            ["sheets.id"],
            name=op.f("fk_scale_calibrations_sheet_id_sheets"),
            ondelete="CASCADE",
        ),
        # Вытеснение — ссылка, а не удаление: цепочка версий должна оставаться читаемой.
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["scale_calibrations.id"],
            name=op.f("fk_scale_calibrations_supersedes_id_scale_calibrations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scale_calibrations")),
    )
    op.create_index(
        op.f("ix_scale_calibrations_created_at"),
        "scale_calibrations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_scale_calibrations_sheet_id_created_at",
        "scale_calibrations",
        ["sheet_id", "created_at"],
        unique=False,
    )
    # Действующая калибровка у листа ровно одна. Частичный уникальный индекс, а не проверка
    # в сервисе: два «основных» масштаба — это два разных ответа на вопрос, сколько метров
    # в стене, и выбирать между ними было бы некому.
    op.create_index(
        "uq_scale_calibrations_default_per_sheet",
        "scale_calibrations",
        ["sheet_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_scale_calibrations_default_per_sheet", table_name="scale_calibrations")
    op.drop_index("ix_scale_calibrations_sheet_id_created_at", table_name="scale_calibrations")
    op.drop_index(op.f("ix_scale_calibrations_created_at"), table_name="scale_calibrations")
    op.drop_table("scale_calibrations")
