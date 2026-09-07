"""Переопределения настроек и флагов.

В базе лежит только то, что отличается от кода: определения настроек и флагов живут
в исходниках и под контролем версий. Строка здесь означает «здесь кто-то намеренно
отступил от умолчания» — и хранит, кто и когда.

Уникальность с необязательным `workspace_id` сделана двумя частичными индексами, а не
одним обычным: в SQL `null` не равен `null`, и обычный уникальный индекс пропустил бы
сколько угодно системных переопределений одного ключа.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain import OverrideScope
from app.models.mixins import TimestampMixin, str_enum, uuid_pk

# Системный уровень — без пространства, уровень пространства — с ним. Третьего не дано,
# и проверка не даёт записи разъехаться со смыслом поля.
_SCOPE_MATCHES_WORKSPACE = "(scope = 'system') = (workspace_id is null)"


class SettingOverride(TimestampMixin, Base):
    """Переопределение настройки на одном из уровней."""

    __tablename__ = "setting_overrides"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[OverrideScope] = mapped_column(
        str_enum(OverrideScope, name="setting_scope"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )

    # JSONB, а не текст: настройка бывает числом, строкой и списком, и хранить их
    # строками означает разбирать типы при каждом чтении.
    value: Mapped[Any] = mapped_column(pg.JSONB, nullable=False)

    # Кто поставил. SET NULL, а не CASCADE: уволенный сотрудник не должен уносить
    # с собой сведения о том, что настройка была изменена.
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(_SCOPE_MATCHES_WORKSPACE, name="scope_matches_workspace"),
        Index(
            "uq_setting_overrides_system_key",
            "key",
            unique=True,
            postgresql_where=text("workspace_id is null"),
        ),
        Index(
            "uq_setting_overrides_workspace_key",
            "workspace_id",
            "key",
            unique=True,
            postgresql_where=text("workspace_id is not null"),
        ),
    )


class FeatureFlagOverride(TimestampMixin, Base):
    """Переопределение флага возможности.

    Причина обязательна не формально: флаг, включённый без объяснения, через месяц
    становится вопросом «а зачем это включено и можно ли выключить».
    """

    __tablename__ = "feature_flag_overrides"

    id: Mapped[uuid.UUID] = uuid_pk()
    flag_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[OverrideScope] = mapped_column(
        str_enum(OverrideScope, name="flag_scope"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )

    enabled: Mapped[bool] = mapped_column(nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("user_identities.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint(_SCOPE_MATCHES_WORKSPACE, name="scope_matches_workspace"),
        Index(
            "uq_feature_flag_overrides_system_key",
            "flag_key",
            unique=True,
            postgresql_where=text("workspace_id is null"),
        ),
        Index(
            "uq_feature_flag_overrides_workspace_key",
            "workspace_id",
            "flag_key",
            unique=True,
            postgresql_where=text("workspace_id is not null"),
        ),
    )
