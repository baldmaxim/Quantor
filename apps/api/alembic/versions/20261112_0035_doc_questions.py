"""Вопросы к документации: кандидаты поиска и подтверждённые ответы

Revision ID: 0035_doc_questions
Revises: 0034_revision_page_texts
Create Date: 2026-11-12

Этап В3 плана «вопросы к документации» (ADR-0043): `doc_question_candidates` - кандидаты задания
`doc_questions_search` (значение, цитата, страница, область, оценка, статус candidate / rejected) и
`doc_question_answers` - ответы, подтверждённые человеком (документ, ручной ввод, норматив-допущение
или «в проекте нет») со снимком происхождения. Уникальный индекс по выражению даёт один ответ на
вопрос в области (NULL области - весь проект). Значение `doc_questions_search` типа задания
(`jobs.job_type`) миграции не требует: перечисление хранится как VARCHAR без CHECK.

Откат удаляет обе таблицы вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0035_doc_questions"
down_revision: str | None = "0034_revision_page_texts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc_question_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("question_code", sa.String(length=64), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=False),
        sa.Column("value_kind", sa.String(length=16), nullable=False),
        sa.Column("value", pg.JSONB(), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("page_label", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("building", sa.Text(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("level", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("versions", pg.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "page_index >= 0", name=op.f("ck_doc_question_candidates_page_index_non_negative")
        ),
        sa.CheckConstraint(
            "score >= 0 and score <= 100", name=op.f("ck_doc_question_candidates_score_in_range")
        ),
        sa.CheckConstraint(
            "occurrences >= 1", name=op.f("ck_doc_question_candidates_occurrences_positive")
        ),
        sa.CheckConstraint(
            "status in ('candidate', 'rejected')",
            name=op.f("ck_doc_question_candidates_status_known"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(value) = 'object'",
            name=op.f("ck_doc_question_candidates_value_is_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(versions) = 'object'",
            name=op.f("ck_doc_question_candidates_versions_is_object"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_doc_question_candidates_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_doc_question_candidates_revision_id_document_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doc_question_candidates")),
    )
    op.create_index(
        "ix_doc_question_candidates_project_question",
        "doc_question_candidates",
        ["project_id", "question_code"],
    )

    op.create_table(
        "doc_question_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("question_code", sa.String(length=64), nullable=False),
        sa.Column("scope_building", sa.Text(), nullable=True),
        sa.Column("scope_section", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("value", pg.JSONB(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("candidate_id", sa.Uuid(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("revision_id", sa.Uuid(), nullable=True),
        sa.Column("page_index", sa.Integer(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("norm_ref", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("catalog_version", sa.Text(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source in ('document', 'manual', 'norm_assumption', 'not_in_project')",
            name=op.f("ck_doc_question_answers_source_known"),
        ),
        sa.CheckConstraint(
            "value is null or jsonb_typeof(value) = 'object'",
            name=op.f("ck_doc_question_answers_value_is_object"),
        ),
        sa.CheckConstraint(
            "(source = 'not_in_project') = (value is null)",
            name=op.f("ck_doc_question_answers_value_matches_source"),
        ),
        sa.CheckConstraint(
            "page_index is null or page_index >= 0",
            name=op.f("ck_doc_question_answers_page_index_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_doc_question_answers_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["doc_question_candidates.id"],
            name=op.f("fk_doc_question_answers_candidate_id_doc_question_candidates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.id"],
            name=op.f("fk_doc_question_answers_revision_id_document_revisions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doc_question_answers")),
    )
    op.create_index(
        "uq_doc_question_answers_scope",
        "doc_question_answers",
        [
            "project_id",
            "question_code",
            sa.text("coalesce(scope_building, '')"),
            sa.text("coalesce(scope_section, '')"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_doc_question_answers_scope", table_name="doc_question_answers")
    op.drop_table("doc_question_answers")
    op.drop_index(
        "ix_doc_question_candidates_project_question", table_name="doc_question_candidates"
    )
    op.drop_table("doc_question_candidates")
