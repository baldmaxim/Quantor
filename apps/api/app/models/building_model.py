"""Модель здания из пакета QMP (ADR-0053): версии, принятые части, этажи.

```text
Project
  └── BuildingModelVersion × N      неизменяемая выгрузка; статус: загрузка → кандидат → утверждена
        ├── ModelPart × N           принятая часть пакета (хеш и размер проверены при приёме)
        └── ModelStorey × N         этажи версии, появляются при фиксации
```

Элементы и геометрия лежат в объектном хранилище как части пакета; база держит только то, по чему
нужны запросы и права: версии, перечень частей и этажи. Не больше одной утверждённой версии на
проект держит частичный уникальный индекс.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain import ModelVersionStatus
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk


class BuildingModelVersion(CreatedAtMixin, Base):
    __tablename__ = "building_model_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    # Версия тендера (ADR-0035), к которой выгружена модель; необязательна.
    tender_version_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("tender_versions.id", ondelete="RESTRICT")
    )
    # Порядковый номер в проекте; выдаётся сервисом под блокировкой проекта.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ModelVersionStatus] = mapped_column(
        str_enum(ModelVersionStatus, name="model_version_status"),
        nullable=False,
        default=ModelVersionStatus.UPLOADING,
        server_default=ModelVersionStatus.UPLOADING.value,
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # Ключ идемпотентности выгрузки: тот же манифест повторно версию не создаёт.
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generator: Mapped[str | None] = mapped_column(String(120))
    storage_prefix: Mapped[str] = mapped_column(String(200), nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Предупреждения проверки: список {code, where, message}.
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        pg.JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    comment: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Согласованность пространства: проект версии - в том же пространстве.
        ForeignKeyConstraint(
            ["project_id", "workspace_id"],
            ["projects.id", "projects.workspace_id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="RESTRICT"),
        UniqueConstraint("project_id", "number", name="uq_building_model_versions_project_number"),
        UniqueConstraint(
            "project_id", "manifest_sha256", name="uq_building_model_versions_project_manifest"
        ),
        CheckConstraint("number >= 1", name="number_positive"),
        CheckConstraint("length(manifest_sha256) = 64", name="manifest_sha256_length"),
        CheckConstraint(
            "status <> 'approved' or approved_at is not null", name="approved_has_time"
        ),
        CheckConstraint(
            "status = 'uploading' or committed_at is not null", name="committed_has_time"
        ),
        Index(
            "uq_building_model_versions_approved",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
    )


class ModelPart(CreatedAtMixin, Base):
    """Принятая часть пакета: путь, вид, размер и sha256 совпали с манифестом."""

    __tablename__ = "model_parts"

    id: Mapped[uuid.UUID] = uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("building_model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    storey_key: Mapped[str | None] = mapped_column(String(64))
    discipline: Mapped[str | None] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False, unique=True)

    __table_args__ = (
        UniqueConstraint("version_id", "path", name="uq_model_parts_version_path"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
    )


class ModelStorey(Base):
    """Этаж версии модели; создаётся при фиксации из `storeys.json`."""

    __tablename__ = "model_storeys"

    id: Mapped[uuid.UUID] = uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("building_model_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    storey_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    elevation_mm: Mapped[float] = mapped_column(Float, nullable=False)
    height_mm: Mapped[float | None] = mapped_column(Float)
    bbox_mm: Mapped[list[float] | None] = mapped_column(pg.JSONB)
    element_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("version_id", "storey_key", name="uq_model_storeys_version_key"),
        CheckConstraint("element_count >= 0", name="element_count_non_negative"),
    )
