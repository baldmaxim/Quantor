"""Местное имя проекта и отметка привязки к тендеру

Revision ID: 0005_project_local_alias
Revises: 0004_control_plane
Create Date: 2026-09-07

У проекта из внешней системы `name` — это её название, а не наше. Обычное переименование
в портале затирало его молча, и восстановить каноническое было уже нечем. Местное имя
хранится отдельно; пусто — показывается каноническое (промт 06).

Отметка привязки нужна разбору перепривязок: без неё историю связи видно только в журнале.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_project_local_alias"
down_revision: str | None = "0004_control_plane"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('local_alias', sa.String(length=200), nullable=True))
    op.add_column('projects', sa.Column('external_bound_at', sa.DateTime(timezone=True), nullable=True))
    # Существующие проекты из TenderHUB считаются привязанными в момент создания:
    # более точного времени в данных нет, а пустая отметка выглядела бы как «не привязан».
    op.execute("update projects set external_bound_at = created_at where source = 'tenderhub'")


def downgrade() -> None:
    op.drop_column('projects', 'external_bound_at')
    op.drop_column('projects', 'local_alias')
