"""Происхождение проекта: источник и внешний идентификатор

Revision ID: 0002_project_source
Revises: 0001_domain_stage1
Create Date: 2026-09-07

Проект может быть заведён руками или подтянут из внешней системы (TenderHUB).
Уникальность по (workspace_id, source, external_id) не даёт создать два проекта
по одному тендеру: повторное нажатие «Создать» должно быть безобидным.

Существующие проекты получают source='manual' — они и правда заведены руками.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_project_source"
down_revision: str | None = "0001_domain_stage1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCES = ("manual", "tenderhub")


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "source",
            sa.Enum(*SOURCES, name="source", native_enum=False, length=32),
            nullable=False,
            server_default="manual",
        ),
    )
    op.add_column("projects", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.add_column("projects", sa.Column("external_ref", sa.String(length=128), nullable=True))
    op.create_unique_constraint(
        "uq_projects_workspace_source_external",
        "projects",
        ["workspace_id", "source", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_projects_workspace_source_external", "projects", type_="unique")
    op.drop_column("projects", "external_ref")
    op.drop_column("projects", "external_id")
    op.drop_column("projects", "source")
