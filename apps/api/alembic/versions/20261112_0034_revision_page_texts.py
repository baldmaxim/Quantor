"""Текст страниц ревизии: указатель на сжатый объект в хранилище

Revision ID: 0034_revision_page_texts
Revises: 0033_cad_section_levels
Create Date: 2026-11-12

Этап В1 плана «вопросы к документации»: `revision_page_texts` - по строке на ревизию PDF с ключом
объекта (gzip, JSON Lines `consistency.page_text.v1`), версией разборщика, числом страниц и
страниц без текста, размером и SHA-256 сжатого файла. Сам текст в базе не хранится (ADR-0002).
Строка есть - ревизия доразобрана; по ней повторный запуск разбора паспортов решает, что пропускать.

Откат удаляет таблицу; объекты в хранилище остаются и перезаписываются повторным разбором.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_revision_page_texts"
down_revision: str | None = "0033_cad_section_levels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revision_page_texts",
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("empty_pages", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "pages >= 0 and empty_pages >= 0 and empty_pages <= pages",
            name=op.f("ck_revision_page_texts_page_counts_valid"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_revision_page_texts_size_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_revision_page_texts_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_revision_page_texts_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("revision_id", name=op.f("pk_revision_page_texts")),
    )
    op.create_index(
        op.f("ix_revision_page_texts_project_id"), "revision_page_texts", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_revision_page_texts_project_id"), table_name="revision_page_texts")
    op.drop_table("revision_page_texts")
