"""Реестр фактов расчётного контура (ADR-0030, PROMPT 01).

```text
CalcSource              откуда факты: класс, заявленная стадия, серия, ревизия
  └── CalcFact × N      утверждение: ключ, значение, метод, проверка; значение неизменно
        └── CalcFactEvidence × N   где прочитано или почему принято
CalcFactConflict        расхождение по ключу: какие утверждения, в каком состоянии
CalcManualOverride      решение человека по ключу: какое утверждение выбрано и почему
```

Ссылки на ревизии и листы документов — значения без внешнего ключа: свидетельство — это
снимок (ревизия, страница, фрагмент), а внешний ключ к таблицам документов менял бы поведение
их удаления, которое этот контур трогать не должен.

Таблиц запусков, результатов, ВОР и вопросов здесь нет: они появятся в своих промтах вместе с
теми, кто в них пишет и читает.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcConflictStatus,
    CalcDiscipline,
    CalcDocumentStage,
    CalcEvidenceKind,
    CalcFactMethod,
    CalcFactStatus,
    CalcReviewStatus,
    CalcSourceClass,
    CalcValueKind,
)
from app.contracts.calc.subjects import CalcFactSubject
from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, str_enum, uuid_pk

# ВОР Заказчика — объект сверки, а не эталон: его утверждения не допускаются к расчёту
# никогда. Ограничение в базе, а не только в сервисе: проверка в приложении ловит ошибку
# пользователя, проверка здесь — ошибку программиста.
_VOR_NEVER_ELIGIBLE = "source_class <> 'CUSTOMER_VOR' or calculation_eligible = false"


class CalcSource(CreatedAtMixin, Base):
    """Источник фактов. Неизменяем: исправление — новый источник той же серии."""

    __tablename__ = "calc_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_class: Mapped[CalcSourceClass] = mapped_column(
        str_enum(CalcSourceClass, name="calc_source_class"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_stage: Mapped[CalcDocumentStage] = mapped_column(
        str_enum(CalcDocumentStage, name="calc_document_stage", length=16),
        nullable=False,
        default=CalcDocumentStage.UNKNOWN,
        server_default=CalcDocumentStage.UNKNOWN.value,
    )
    section_code: Mapped[str | None] = mapped_column(String(16))
    series_key: Mapped[str | None] = mapped_column(String(100))
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    calculation_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(_VOR_NEVER_ELIGIBLE, name="vor_never_eligible"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        Index("ix_calc_sources_project_id", "project_id"),
    )


class CalcFact(CreatedAtMixin, Base):
    """Утверждение источника о факте.

    Значение, единица и место не меняются после записи. Меняется только жизненный цикл:
    проверка человеком, замена новой версией того же источника, отзыв с причиной.
    """

    __tablename__ = "calc_facts"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # NO ACTION, а не RESTRICT: удаление проекта каскадом уносит и источники, и утверждения
    # одной операцией, а точечное удаление источника из-под утверждений — нет.
    source_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_sources.id", ondelete="NO ACTION"), nullable=False
    )
    # Копия класса источника: без неё ограничение «ВОР не идёт в расчёт» пришлось бы проверять
    # через соседнюю таблицу, а CHECK так не умеет.
    source_class: Mapped[CalcSourceClass] = mapped_column(
        str_enum(CalcSourceClass, name="calc_source_class"), nullable=False
    )
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False)

    building: Mapped[str | None] = mapped_column(String(64))
    section: Mapped[str | None] = mapped_column(String(64))
    floor: Mapped[str | None] = mapped_column(String(64))
    room: Mapped[str | None] = mapped_column(String(64))
    discipline: Mapped[CalcDiscipline | None] = mapped_column(
        str_enum(CalcDiscipline, name="calc_discipline", length=8)
    )
    system_code: Mapped[str | None] = mapped_column(String(64))
    subject_key: Mapped[str] = mapped_column(String(480), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(560), nullable=False)

    value_kind: Mapped[CalcValueKind] = mapped_column(
        str_enum(CalcValueKind, name="calc_value_kind", length=16), nullable=False
    )
    value: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    stated_value: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String(16))

    method: Mapped[CalcFactMethod] = mapped_column(
        str_enum(CalcFactMethod, name="calc_fact_method"), nullable=False
    )
    confidence: Mapped[CalcConfidence] = mapped_column(
        str_enum(CalcConfidence, name="calc_confidence", length=8), nullable=False
    )
    review_status: Mapped[CalcReviewStatus] = mapped_column(
        str_enum(CalcReviewStatus, name="calc_review_status", length=16),
        nullable=False,
        default=CalcReviewStatus.UNREVIEWED,
        server_default=CalcReviewStatus.UNREVIEWED.value,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)

    status: Mapped[CalcFactStatus] = mapped_column(
        str_enum(CalcFactStatus, name="calc_fact_status", length=16),
        nullable=False,
        default=CalcFactStatus.ACTIVE,
        server_default=CalcFactStatus.ACTIVE.value,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_facts.id", ondelete="NO ACTION")
    )
    calculation_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    source: Mapped[CalcSource] = relationship()
    evidence: Mapped[list[CalcFactEvidence]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CalcFactEvidence.created_at",
    )

    __table_args__ = (
        CheckConstraint(_VOR_NEVER_ELIGIBLE, name="vor_never_eligible"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(status = 'WITHDRAWN') = (withdrawn_at is not null)", name="withdrawn_consistent"
        ),
        UniqueConstraint(
            "project_id", "fact_key", "source_id", "version", name="uq_calc_facts_version"
        ),
        # У источника по ключу действует одно утверждение: новое значение — новая версия.
        Index(
            "uq_calc_facts_active_per_source",
            "project_id",
            "fact_key",
            "source_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_calc_facts_project_id_fact_key", "project_id", "fact_key"),
        Index("ix_calc_facts_project_id_fact_type", "project_id", "fact_type"),
    )

    @property
    def subject(self) -> CalcFactSubject:
        return CalcFactSubject(
            building=self.building,
            section=self.section,
            floor=self.floor,
            room=self.room,
            discipline=self.discipline,
            system_code=self.system_code,
        )


class CalcFactEvidence(CreatedAtMixin, Base):
    """Свидетельство утверждения. Снимок места и основания, а не живая ссылка."""

    __tablename__ = "calc_fact_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    fact_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_facts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[CalcEvidenceKind] = mapped_column(
        str_enum(CalcEvidenceKind, name="calc_evidence_kind"), nullable=False
    )
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    page_index: Mapped[int | None] = mapped_column(Integer)
    sheet_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    bbox: Mapped[list[float] | None] = mapped_column(pg.JSONB)
    locator: Mapped[str | None] = mapped_column(String(200))
    excerpt: Mapped[str | None] = mapped_column(Text)
    basis: Mapped[str | None] = mapped_column(Text)
    alternatives: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    fact: Mapped[CalcFact] = relationship(back_populates="evidence")

    __table_args__ = (
        # Свидетельство без содержания — не свидетельство.
        CheckConstraint(
            "(kind = 'DOCUMENT_FRAGMENT' and document_revision_id is not null)"
            " or (kind = 'ASSUMPTION_BASIS' and basis is not null)"
            " or (kind = 'MANUAL_ENTRY' and author_id is not null)",
            name="kind_has_content",
        ),
        Index("ix_calc_fact_evidence_fact_id", "fact_id"),
    )


class CalcFactConflict(TimestampMixin, Base):
    """Расхождение по ключу факта. Одна строка на ключ: история — в журнале аудита."""

    __tablename__ = "calc_fact_conflicts"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fact_key: Mapped[str] = mapped_column(String(560), nullable=False)
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(480), nullable=False)
    status: Mapped[CalcConflictStatus] = mapped_column(
        str_enum(CalcConflictStatus, name="calc_conflict_status", length=16), nullable=False
    )
    claim_ids: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default="[]"
    )
    claim_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "fact_key", name="uq_calc_fact_conflicts_key"),
    )


class CalcManualOverride(CreatedAtMixin, Base):
    """Решение человека по ключу: выбранное утверждение, основание и набор, по которому решали."""

    __tablename__ = "calc_manual_overrides"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    fact_key: Mapped[str] = mapped_column(String(560), nullable=False)
    conflict_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_fact_conflicts.id", ondelete="NO ACTION")
    )
    chosen_fact_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("calc_facts.id", ondelete="NO ACTION"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    claim_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint("length(btrim(reason)) > 0", name="reason_not_blank"),
        # Действует одно решение на ключ: новое отзывает прежнее.
        Index(
            "uq_calc_manual_overrides_active",
            "project_id",
            "fact_key",
            unique=True,
            postgresql_where=text("revoked_at is null"),
        ),
    )
