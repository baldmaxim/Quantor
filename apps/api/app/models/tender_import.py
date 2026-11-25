"""Пакетный импорт тендерной документации: перечень комплекта и его позиции.

```text
Project
  └── TenderImport × N        комплект, отпечаток content_key (по PDF и blocks.json позиций)
        └── TenderImportItem × N   один ZIP распознавалки: ожидаемые хеши и ссылка на приём
```

Состояние позиции в базе не хранится: оно выводится при чтении из задания импорта и ревизий
проекта (`services/tender_imports.py`). Здесь только то, что заявлено клиентом, и ссылки на то,
что приняло ядро. Файлы лежат в объектном хранилище, в строках позиций — только хеши.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, uuid_pk


class TenderImport(TimestampMixin, Base):
    __tablename__ = "tender_imports"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    # Тендер TenderHUB, по которому заявлен импорт (если объект искали или создавали по нему).
    tenderhub_id: Mapped[str | None] = mapped_column(String(64))
    # Как найден объект при первом создании импорта: project_id | tenderhub_id | tender_number
    # | created.
    matched_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # Отпечаток комплекта: sha256 отсортированного списка [ключ, sha256 PDF, sha256 blocks.json].
    # Хеши самих ZIP в него не входят: архив пересобирается с новыми временными метками.
    content_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        UniqueConstraint("project_id", "content_key", name="uq_tender_imports_project_content"),
        CheckConstraint("char_length(content_key) = 64", name="content_key_length"),
        Index("ix_tender_imports_workspace_id", "workspace_id"),
    )


class TenderImportItem(TimestampMixin, Base):
    __tablename__ = "tender_import_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("tender_imports.id", ondelete="CASCADE"), nullable=False
    )
    item_key: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    blocks_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Принятый ZIP-пакет и задание его импорта. SET NULL: позиция переживает удаление ревизии
    # и снова становится «ожидает загрузки».
    package_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("document_revisions.id", ondelete="SET NULL")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("import_id", "item_key", name="uq_tender_import_items_import_key"),
        CheckConstraint("size > 0", name="size_positive"),
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        CheckConstraint("char_length(pdf_sha256) = 64", name="pdf_sha256_length"),
        CheckConstraint("char_length(blocks_sha256) = 64", name="blocks_sha256_length"),
        Index("ix_tender_import_items_job_id", "job_id"),
        Index("ix_tender_import_items_package_revision_id", "package_revision_id"),
    )
