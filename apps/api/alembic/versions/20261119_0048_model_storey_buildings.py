"""Этажи модели по зданиям: здание этажа и его место в storeys.json

Revision ID: 0048_model_storey_buildings
Revises: 0047_oauth
Create Date: 2026-11-19

ADR-0053, QMP v1 раздел 4. В IFC с несколькими IfcBuilding (объект 346: восемь корпусов,
стилобат, подземная часть) этажи остаются в своём здании: у строки storeys.json есть
`building_key` и `building_name`, порядок - по зданиям, внутри здания по отметке. `position` - номер
строки в storeys.json, по нему этажи и отдаются; у прежних версий он пуст, они идут по отметке.

Колонки необязательные, прежние строки не меняются. Откат удаляет колонки вместе с данными о
зданиях; этажи и версии остаются.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_model_storey_buildings"
down_revision: str | None = "0047_oauth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_storeys", sa.Column("building_key", sa.String(length=64), nullable=True))
    op.add_column(
        "model_storeys", sa.Column("building_name", sa.String(length=200), nullable=True)
    )
    op.add_column("model_storeys", sa.Column("position", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_storeys", "position")
    op.drop_column("model_storeys", "building_name")
    op.drop_column("model_storeys", "building_key")
