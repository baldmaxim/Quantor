"""Пакетный импорт тендерной документации: перечень комплекта и позиции

Revision ID: 0049_tender_imports
Revises: 0048_model_storey_buildings
Create Date: 2026-11-25

`tender_imports` - комплект по объекту с отпечатком `content_key` (по PDF и blocks.json позиций),
`tender_import_items` - позиции (один ZIP распознавалки) с заявленными хешами и ссылками на приём.
Состояние позиций в базе не хранится: оно выводится при чтении.

Откат удаляет обе таблицы вместе с перечнями; загруженные документы и задания остаются.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_tender_imports"
down_revision: str | None = "0048_model_storey_buildings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "tender_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("tenderhub_id", sa.String(length=64), nullable=True),
        sa.Column("matched_by", sa.String(length=20), nullable=False),
        sa.Column("content_key", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.CheckConstraint(
            "char_length(content_key) = 64", name=op.f("ck_tender_imports_content_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            name=op.f("fk_tender_imports_project_id_workspace_id_projects"),
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_imports")),
        sa.UniqueConstraint("project_id", "content_key", name="uq_tender_imports_project_content"),
    )
    op.create_index(op.f("ix_tender_imports_created_at"), "tender_imports", ["created_at"])
    op.create_index("ix_tender_imports_workspace_id", "tender_imports", ["workspace_id"])

    op.create_table(
        "tender_import_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("item_key", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("pdf_sha256", sa.String(length=64), nullable=False),
        sa.Column("blocks_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_revision_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.CheckConstraint("size > 0", name=op.f("ck_tender_import_items_size_positive")),
        sa.CheckConstraint(
            "char_length(sha256) = 64", name=op.f("ck_tender_import_items_sha256_length")
        ),
        sa.CheckConstraint(
            "char_length(pdf_sha256) = 64", name=op.f("ck_tender_import_items_pdf_sha256_length")
        ),
        sa.CheckConstraint(
            "char_length(blocks_sha256) = 64",
            name=op.f("ck_tender_import_items_blocks_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["tender_imports.id"],
            name=op.f("fk_tender_import_items_import_id_tender_imports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["package_revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_tender_import_items_package_revision_id_document_revisions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_tender_import_items_job_id_jobs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_import_items")),
        sa.UniqueConstraint("import_id", "item_key", name="uq_tender_import_items_import_key"),
    )
    op.create_index(
        op.f("ix_tender_import_items_created_at"), "tender_import_items", ["created_at"]
    )
    op.create_index("ix_tender_import_items_job_id", "tender_import_items", ["job_id"])
    op.create_index(
        "ix_tender_import_items_package_revision_id",
        "tender_import_items",
        ["package_revision_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tender_import_items_package_revision_id", table_name="tender_import_items")
    op.drop_index("ix_tender_import_items_job_id", table_name="tender_import_items")
    op.drop_index(op.f("ix_tender_import_items_created_at"), table_name="tender_import_items")
    op.drop_table("tender_import_items")
    op.drop_index("ix_tender_imports_workspace_id", table_name="tender_imports")
    op.drop_index(op.f("ix_tender_imports_created_at"), table_name="tender_imports")
    op.drop_table("tender_imports")
