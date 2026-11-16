"""Профиль оформления проектировщика в пилоте CAD (ADR-0049, решения 1, 2, 5, 6).

Один профиль на том (документ); версии неизменяемы. Тело версии - готовый объект для движка
`cad_engine.style_profile.v1` и его хеш. Версию меняет только новая версия: UPDATE строки версии
запрещён триггером базы, DELETE разрешён ради каскада от профиля и документа.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Connection,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, TimestampMixin, uuid_pk


class CadStyleProfile(TimestampMixin, Base):
    """Профиль оформления тома: ключ для движка и связь с документом."""

    __tablename__ = "cad_style_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (UniqueConstraint("document_id", name="uq_cad_style_profiles_document_id"),)


class CadStyleProfileVersion(CreatedAtMixin, Base):
    """Неизменяемая версия профиля: объект для движка, его хеш и происхождение."""

    __tablename__ = "cad_style_profile_versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("cad_style_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    style: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[dict[str, Any]] = mapped_column(pg.JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        UniqueConstraint(
            "profile_id", "version", name="uq_cad_style_profile_versions_profile_id_version"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("char_length(title) <= 200", name="title_length"),
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        CheckConstraint("jsonb_typeof(style) = 'object'", name="style_is_object"),
        CheckConstraint("jsonb_typeof(source) = 'object'", name="source_is_object"),
    )


# Тот же текст, что в миграции 0041: тестовая база строится из моделей, бой - из миграций;
# совпадение проверяет test_schema_matches_migrations. UPDATE версии запрещён, DELETE - нет:
# он нужен каскаду от профиля и документа.
GUARD_FUNCTION = """
create or replace function cad_style_profile_versions_immutable() returns trigger
language plpgsql as $$
begin
    raise exception 'cad_style_profile_versions: a version is immutable, create a new version';
end
$$
"""

GUARD_TRIGGER = """
create trigger trg_cad_style_profile_versions_immutable
before update on cad_style_profile_versions
for each row execute function cad_style_profile_versions_immutable()
"""


def _install(*statements: str) -> Callable[..., None]:
    def listener(target: Table, connection: Connection, **kwargs: object) -> None:
        if connection.dialect.name != "postgresql":
            return
        for statement in statements:
            connection.exec_driver_sql(statement)

    return listener


event.listen(
    CadStyleProfileVersion.__table__,
    "after_create",
    _install(GUARD_FUNCTION, GUARD_TRIGGER),
)
