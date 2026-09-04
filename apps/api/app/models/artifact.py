"""Артефакты распознавания: файлы исходного пакета, сохранённые как есть."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import ArtifactKind
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.document import DocumentRevision


class RecognitionArtifact(CreatedAtMixin, Base):
    """Файл из распознанного пакета.

    Хранится неизменно и с контрольной суммой: без этого невозможно доказать, из чего именно
    получены области. results.html сохраняется как артефакт, но источником правды не является
    и доверенным HTML никогда не отображается (ADR-0007).
    """

    __tablename__ = "recognition_artifacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    revision_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )

    artifact_kind: Mapped[ArtifactKind] = mapped_column(
        str_enum(ArtifactKind, name="artifact_kind"),
        nullable=False,
    )
    schema_version: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)

    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    revision: Mapped[DocumentRevision] = relationship(back_populates="artifacts")

    __table_args__ = (
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        Index("ix_recognition_artifacts_revision_id_artifact_kind", "revision_id", "artifact_kind"),
    )
