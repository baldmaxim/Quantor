"""ВОР Заказчика в контуре «Конструкции CAD»: документы, строки, связи с группами

Revision ID: 0026_cad_vor
Revises: 0025_cad_constructions
Create Date: 2026-11-11

ADR-0038 п. 5: `cad_vor_documents` - загруженный XLSX (оригинал в хранилище, здесь ключ и хеш),
`cad_vor_items` - его строки с подсказками толщины и вида, `cad_vor_links` - связи группы
конструкций (`вид|толщина_мм|материал`) со строкой ВОР на уровне проекта. Это объект сверки:
количества строк на подсчёт не влияют и в calc не попадают.

Откат удаляет все три таблицы вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_cad_vor"
down_revision: str | None = "0025_cad_constructions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cad_vor_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column(
            "sheet_names",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("header_row", sa.Integer(), nullable=False),
        sa.Column(
            "columns",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("rows_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("size >= 0", name=op.f("ck_cad_vor_documents_size_non_negative")),
        sa.CheckConstraint(
            "rows_count >= 0", name=op.f("ck_cad_vor_documents_rows_count_non_negative")
        ),
        sa.CheckConstraint(
            "header_row >= 1", name=op.f("ck_cad_vor_documents_header_row_positive")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(sheet_names) = 'array'",
            name=op.f("ck_cad_vor_documents_sheet_names_is_array"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(columns) = 'array'", name=op.f("ck_cad_vor_documents_columns_is_array")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_vor_documents_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_vor_documents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_vor_documents")),
    )
    op.create_index(op.f("ix_cad_vor_documents_created_at"), "cad_vor_documents", ["created_at"])
    op.create_index(op.f("ix_cad_vor_documents_project_id"), "cad_vor_documents", ["project_id"])

    op.create_table(
        "cad_vor_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("sheet", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("thickness_hint_mm", sa.Integer(), nullable=True),
        sa.Column("kind_hint", sa.String(length=16), nullable=True),
        sa.CheckConstraint("row_no >= 1", name=op.f("ck_cad_vor_items_row_no_positive")),
        sa.CheckConstraint(
            "kind_hint is null or kind_hint in ('masonry', 'monolith')",
            name=op.f("ck_cad_vor_items_kind_hint_values"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["cad_vor_documents.id"],
            name=op.f("fk_cad_vor_items_document_id_cad_vor_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_vor_items")),
    )
    op.create_index(
        "ix_cad_vor_items_document_id_row_no", "cad_vor_items", ["document_id", "row_no"]
    )

    op.create_table(
        "cad_vor_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("group_key", sa.String(length=64), nullable=False),
        sa.Column("vor_item_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(group_key) between 3 and 64",
            name=op.f("ck_cad_vor_links_group_key_length"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_cad_vor_links_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_cad_vor_links_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vor_item_id"],
            ["cad_vor_items.id"],
            name=op.f("fk_cad_vor_links_vor_item_id_cad_vor_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cad_vor_links")),
        sa.UniqueConstraint(
            "project_id", "group_key", "vor_item_id", name="uq_cad_vor_links_project_group_item"
        ),
    )
    op.create_index(op.f("ix_cad_vor_links_vor_item_id"), "cad_vor_links", ["vor_item_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_cad_vor_links_vor_item_id"), table_name="cad_vor_links")
    op.drop_table("cad_vor_links")
    op.drop_index("ix_cad_vor_items_document_id_row_no", table_name="cad_vor_items")
    op.drop_table("cad_vor_items")
    op.drop_index(op.f("ix_cad_vor_documents_project_id"), table_name="cad_vor_documents")
    op.drop_index(op.f("ix_cad_vor_documents_created_at"), table_name="cad_vor_documents")
    op.drop_table("cad_vor_documents")
