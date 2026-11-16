"""Обмен расчётами с TENDER (ADR-0051): выпуски базы объекта, репозитории расчётов и их версии.

Выпуск базы и версия расчёта неизменяемы: после создания меняются только отметки отзыва и
статус версии. ZIP-пакеты и файлы видов лежат в объектном хранилище (ADR-0002); в базе —
метаданные, свод объёмов и ключи с sha256. Геометрия расчёта в базу не пишется. Объёмы расчёта —
внешний результат с происхождением (навык, версия, автор), не `Measurement` и не
`ExpectedQuantity`: в итоги обмера и calc они не входят.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import uuid_pk

TENDER_DISCIPLINES: tuple[str, ...] = ("mech", "eom", "ss")
TENDER_VERSION_STATUSES: tuple[str, ...] = ("active", "superseded", "withdrawn")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} in (" + ", ".join(f"'{value}'" for value in values) + ")"


class TenderBaseRelease(Base):
    """Выпуск базы объекта: неизменяемый ZIP с кадрами, осями, зонами и конструкциями видов."""

    __tablename__ = "tender_base_releases"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Номер выпуска по проекту, с 1.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    released_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    include_dxf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Виды выпуска: key, dir, revision_id, page_index, view, job_id, dxf_sha256, document_title,
    # label, corps, section, floors.
    views: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    package_key: Mapped[str] = mapped_column(Text, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_tender_base_releases_project_id_number"),
        Index("ix_tender_base_releases_workspace_id", "workspace_id"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("jsonb_typeof(views) = 'array'", name="views_is_array"),
    )


class TenderCalc(Base):
    """Репозиторий расчёта: проект + раздел + система + название."""

    __tablename__ = "tender_calcs"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    discipline: Mapped[str] = mapped_column(String(8), nullable=False)
    system: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "discipline",
            "system",
            "title",
            name="uq_tender_calcs_project_id_discipline_system_title",
        ),
        Index("ix_tender_calcs_workspace_id", "workspace_id"),
        CheckConstraint(_in("discipline", TENDER_DISCIPLINES), name="discipline_known"),
    )


class TenderCalcVersion(Base):
    """Версия расчёта: неизменяемая загрузка пакета `quantor.tender_calc.v1`."""

    __tablename__ = "tender_calc_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    calc_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("tender_calcs.id", ondelete="CASCADE"), nullable=False
    )
    # Номер версии внутри репозитория, с 1.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    base_release_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("tender_base_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    producer: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    fit: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    package_key: Mapped[str] = mapped_column(Text, nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Виды: view_key, revision_id, page_index, view, floors, dxf_sha256, object_key,
    # polylines и elements (числа).
    views: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    # Строки объёмов (не больше 5000), вопросы и предупреждения приёма.
    quantities: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(pg.JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    withdrawn_by: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("calc_id", "number", name="uq_tender_calc_versions_calc_id_number"),
        UniqueConstraint(
            "calc_id", "package_sha256", name="uq_tender_calc_versions_calc_id_package_sha256"
        ),
        # Одна действующая версия на репозиторий: прежняя при загрузке новой становится superseded.
        Index(
            "uq_tender_calc_versions_active",
            "calc_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_tender_calc_versions_base_release_id", "base_release_id"),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint(_in("status", TENDER_VERSION_STATUSES), name="status_known"),
        CheckConstraint("jsonb_typeof(fit) = 'array'", name="fit_is_array"),
        CheckConstraint("jsonb_typeof(views) = 'array'", name="views_is_array"),
        CheckConstraint("jsonb_typeof(quantities) = 'array'", name="quantities_is_array"),
        CheckConstraint("jsonb_typeof(questions) = 'array'", name="questions_is_array"),
        CheckConstraint("jsonb_typeof(warnings) = 'array'", name="warnings_is_array"),
        CheckConstraint(
            "(status = 'withdrawn') = (withdrawn_at is not null)", name="withdrawn_matches_status"
        ),
    )
