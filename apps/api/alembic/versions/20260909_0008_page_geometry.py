"""Каноническая геометрия страницы PDF и состояние её извлечения

Revision ID: 0008_page_geometry
Revises: 0007_job_workspace_scope
Create Date: 2026-09-09

Сервер до сих пор не знал размер страницы документа: `Sheet.width_px` — это пиксели растра
распознавалки, снятые с непостоянной плотностью, а при обычной загрузке PDF листов не
создавалось вовсе. Считать физические длины и площади было не от чего (ADR-0016).

Геометрия живёт отдельной таблицей, а не колонками в `sheets`: там она смешалась бы с
растровыми метаданными, и набор nullable-колонок допускал бы состояние «половина геометрии».
Строка есть — геометрия известна целиком; строки нет — неизвестна.

Состояние извлечения добавлено к ревизии, а не к странице: при расхождении числа страниц
доверять нельзя ни одной. `processing_status` для этого не переиспользуется — он описывает
импорт распознанного пакета и у обычного PDF навсегда остаётся `unprocessed`.

Существующие ревизии получают `not_applicable`: геометрия у них не извлекалась, и это не
отказ. Задания на извлечение для уже загруженных PDF ставятся отдельно, а не миграцией:
миграция меняет схему, а не запускает работу.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_page_geometry"
down_revision: str | None = "0007_job_workspace_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SPACE = "pdf_display_points_top_left"
_GEOMETRY_STATUSES = ("not_applicable", "pending", "extracting", "ready", "failed")


def upgrade() -> None:
    op.create_table(
        "page_geometries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sheet_id", sa.Uuid(), nullable=False),
        sa.Column(
            "coordinate_space",
            sa.String(length=64),
            server_default=_SPACE,
            nullable=False,
        ),
        # Numeric, а не float: отпечаток и происхождение требуют одной канонической записи
        # числа в PostgreSQL, Python и TypeScript. 0,0001 pt — 35 нанометров чертежа.
        sa.Column("display_width_pt", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("display_height_pt", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("pdf_rotation", sa.Integer(), nullable=False),
        sa.Column("media_box", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("crop_box", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("parser_name", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("geometry_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "extraction_metadata",
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
        sa.CheckConstraint(
            f"coordinate_space = '{_SPACE}'",
            name=op.f("ck_page_geometries_coordinate_space_known"),
        ),
        # Нулевая страница — не «странные данные», а неверный расчёт: на неё делят
        # при переводе нормализованных координат в точки.
        sa.CheckConstraint(
            "display_width_pt > 0 and display_height_pt > 0",
            name=op.f("ck_page_geometries_display_size_positive"),
        ),
        sa.CheckConstraint(
            "pdf_rotation in (0, 90, 180, 270)",
            name=op.f("ck_page_geometries_pdf_rotation_allowed"),
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64", name=op.f("ck_page_geometries_source_sha256_length")
        ),
        sa.CheckConstraint(
            "length(geometry_fingerprint) = 64",
            name=op.f("ck_page_geometries_fingerprint_length"),
        ),
        sa.ForeignKeyConstraint(
            ["sheet_id"],
            ["sheets.id"],
            name=op.f("fk_page_geometries_sheet_id_sheets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_geometries")),
        # Один к одному: у листа не может быть двух геометрий. Повторное извлечение
        # заменяет строку, а не добавляет вторую.
        sa.UniqueConstraint("sheet_id", name=op.f("uq_page_geometries_sheet_id")),
    )
    op.create_index(
        op.f("ix_page_geometries_created_at"), "page_geometries", ["created_at"], unique=False
    )

    # Перечисление хранится строкой, а не нативным типом PostgreSQL: новое значение не
    # требует ALTER TYPE. Тип объявлен через sa.Enum, как и остальные в проекте, — так
    # колонка получается той же, что строит модель.
    #
    # CHECK при этом не создаётся ни здесь, ни моделью: у SQLAlchemy начиная с 1.4
    # `create_constraint` по умолчанию выключен, и `processing_status` рядом живёт так же.
    # Состав значений проверяет приложение. Схема и модель совпадают — это главное.
    op.add_column(
        "document_revisions",
        sa.Column(
            "geometry_status",
            sa.Enum(*_GEOMETRY_STATUSES, name="geometry_status", native_enum=False, length=32),
            server_default="not_applicable",
            nullable=False,
        ),
    )
    op.add_column(
        "document_revisions", sa.Column("geometry_error_code", sa.String(length=64), nullable=True)
    )

    # Существующие ревизии PDF переводятся в `pending`: геометрия у них применима, просто
    # ещё не извлечена. Оставить их `not_applicable` значило бы записать неправду —
    # «извлекать нечего» вместо «не извлекали».
    #
    # Задания при этом не создаются: миграция меняет схему, а не запускает работу. Их
    # поставит промт 03 явным действием.
    op.execute(
        """
        update document_revisions
           set geometry_status = 'pending'
         where source_mime = 'application/pdf'
        """
    )


def downgrade() -> None:
    op.drop_column("document_revisions", "geometry_error_code")
    op.drop_column("document_revisions", "geometry_status")
    op.drop_index(op.f("ix_page_geometries_created_at"), table_name="page_geometries")
    op.drop_table("page_geometries")
