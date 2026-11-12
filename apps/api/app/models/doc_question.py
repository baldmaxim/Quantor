"""Вопросы к документации (ADR-0043, шаг 2, этап В3): кандидаты поиска и подтверждённые ответы.

Кандидата собирает задание `doc_questions_search` по тексту страниц PDF; ответом он становится
только по решению человека. Ответ хранит снимок происхождения (файл, ревизия, страница, цитата),
поэтому живёт и после повторного поиска, который пересобирает кандидатов. Модель чисел не
выдаёт: значения приходят из шаблонов каталога, ручного ввода или норматива-допущения.
Данные контура согласованности, в итоги обмера, таблицы MEP и calc не входят.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk


class DocQuestionCandidate(Base):
    __tablename__ = "doc_question_candidates"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_version: Mapped[str] = mapped_column(Text, nullable=False)
    value_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Нормализованное значение как в doc_search: {kind, display, numbers, qualifier, code}.
    value: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_label: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    building: Mapped[str | None] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="candidate", server_default="candidate"
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Версии каталога, поиска и словарей, по которым собран кандидат.
    versions: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("page_index >= 0", name="page_index_non_negative"),
        CheckConstraint("score >= 0 and score <= 100", name="score_in_range"),
        CheckConstraint("occurrences >= 1", name="occurrences_positive"),
        CheckConstraint("status in ('candidate', 'rejected')", name="status_known"),
        CheckConstraint("jsonb_typeof(value) = 'object'", name="value_is_object"),
        CheckConstraint("jsonb_typeof(versions) = 'object'", name="versions_is_object"),
        Index("ix_doc_question_candidates_project_question", "project_id", "question_code"),
    )


class DocQuestionAnswer(Base):
    __tablename__ = "doc_question_answers"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    question_code: Mapped[str] = mapped_column(String(64), nullable=False)
    # Область ответа; оба NULL - весь проект.
    scope_building: Mapped[str | None] = mapped_column(Text)
    scope_section: Mapped[str | None] = mapped_column(Text)
    # document | manual | norm_assumption | not_in_project.
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    # Для not_in_project значения нет: «не определено» не превращается в 0.
    # none_as_null: Python None - это SQL NULL, а не JSON null (на этом держится CHECK источника).
    value: Mapped[dict[str, Any] | None] = mapped_column(pg.JSONB(none_as_null=True))
    value_text: Mapped[str | None] = mapped_column(Text)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("doc_question_candidates.id", ondelete="SET NULL"),
    )
    # Снимок происхождения: ответ не зависит от судьбы кандидата.
    file_name: Mapped[str | None] = mapped_column(Text)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    page_index: Mapped[int | None] = mapped_column(Integer)
    quote: Mapped[str | None] = mapped_column(Text)
    norm_ref: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    catalog_version: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "source in ('document', 'manual', 'norm_assumption', 'not_in_project')",
            name="source_known",
        ),
        CheckConstraint("value is null or jsonb_typeof(value) = 'object'", name="value_is_object"),
        CheckConstraint(
            "(source = 'not_in_project') = (value is null)", name="value_matches_source"
        ),
        CheckConstraint("page_index is null or page_index >= 0", name="page_index_non_negative"),
        # Один ответ на вопрос в области: повторное подтверждение заменяет прежний.
        Index(
            "uq_doc_question_answers_scope",
            "project_id",
            "question_code",
            text("coalesce(scope_building, '')"),
            text("coalesce(scope_section, '')"),
            unique=True,
        ),
    )
