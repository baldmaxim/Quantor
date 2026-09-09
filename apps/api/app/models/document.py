"""Документ проекта и его неизменяемые ревизии."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import DocumentKind, GeometryStatus, ProcessingStatus
from app.models.mixins import CreatedAtMixin, TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.artifact import RecognitionArtifact
    from app.models.project import Project
    from app.models.sheet import Sheet


class Document(TimestampMixin, Base):
    """Логический документ. Переименовывается; содержимое живёт в ревизиях."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    discipline: Mapped[str | None] = mapped_column(String(64))
    document_kind: Mapped[DocumentKind] = mapped_column(
        str_enum(DocumentKind, name="document_kind"),
        nullable=False,
    )

    project: Mapped[Project] = relationship(back_populates="documents")
    revisions: Mapped[list[DocumentRevision]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentRevision.created_at",
    )

    __table_args__ = (Index("ix_documents_project_id_created_at", "project_id", "created_at"),)


class DocumentRevision(CreatedAtMixin, Base):
    """Загруженная версия документа.

    Неизменяема: имя, размер, MIME, хэш и ключ объекта после создания не переписываются
    (ADR-0003). Меняются только состояния обработки — `processing_status` и
    `geometry_status`. Они описывают ход работы над файлом, а не сам файл, и относятся
    к двум независимым процессам: импорту распознанного пакета и извлечению геометрии.
    """

    __tablename__ = "document_revisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    revision_label: Mapped[str | None] = mapped_column(String(64))

    # Имя в том виде, в каком его дал пользователь: кириллица, пробелы и точки допустимы.
    # В ключ объекта оно не попадает — см. ADR-0002.
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    source_mime: Mapped[str] = mapped_column(String(255), nullable=False)
    source_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        str_enum(ProcessingStatus, name="processing_status"),
        nullable=False,
        default=ProcessingStatus.PENDING,
    )
    processing_error_code: Mapped[str | None] = mapped_column(String(64))

    # Состояние извлечения канонической геометрии страниц (ADR-0016). Отдельно от
    # processing_status: тот описывает импорт распознанного пакета и у обычного PDF навсегда
    # остаётся `unprocessed`. Одно поле на два независимых процесса означало бы, что успех
    # одного стирает отказ другого.
    #
    # Состояние принадлежит ревизии, а не странице: при расхождении числа страниц доверять
    # нельзя ни одной, поэтому частично извлечённой геометрии не бывает.
    geometry_status: Mapped[GeometryStatus] = mapped_column(
        str_enum(GeometryStatus, name="geometry_status"),
        nullable=False,
        default=GeometryStatus.NOT_APPLICABLE,
        server_default=GeometryStatus.NOT_APPLICABLE.value,
    )
    geometry_error_code: Mapped[str | None] = mapped_column(String(64))

    # Схема и происхождение исходника: версия пакета, пространство координат, число страниц.
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    document: Mapped[Document] = relationship(back_populates="revisions")
    sheets: Mapped[list[Sheet]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Sheet.page_index",
    )
    artifacts: Mapped[list[RecognitionArtifact]] = relationship(
        back_populates="revision", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("source_size >= 0", name="source_size_non_negative"),
        CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
        Index("ix_document_revisions_document_id_created_at", "document_id", "created_at"),
        # Повторная загрузка того же файла в тот же документ не должна плодить ревизии.
        Index(
            "uq_document_revisions_document_id_source_sha256",
            "document_id",
            "source_sha256",
            unique=True,
        ),
    )
