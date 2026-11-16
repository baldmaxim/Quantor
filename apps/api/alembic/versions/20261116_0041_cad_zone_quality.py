"""Зоны CAD: происхождение и сверка с экспликацией

Revision ID: 0041_cad_zone_quality
Revises: 0040_cad_facade_views
Create Date: 2026-11-16

Ревью движка 2026-11-16 (ЖК Знаки): зона с отклонением от экспликации в разы писалась как рабочая,
а авто-зоны нельзя было отличить от разметки человека и пересоздать. Поля `cad_zones`:

- `source` (`auto | human | unknown`) и `generator_version` - происхождение;
- `expl_area_m2`, `generator_area_m2`, `notes` - то, что генератор пишет в zones.json;
- `quality_status` (`ok | review | failed`), `quality_reason` - итог сверки, считает портал;
- `quality_accepted_by`, `quality_accepted_at` - кто и когда принял зону вне допуска.

Старые строки. `human` - у зоны есть автор (`created_by`). `auto` - только если зона без автора,
ни разу не менялась (`updated_at = created_at`) и создана во время успешного задания `cad_zones`
этой страницы с итогом `zones_ready`; версия генератора берётся из задания. Всё остальное -
`unknown`: такие зоны ведут себя как разметка человека и автоматически не удаляются. Сверка
старых строк не выполняется (экспликации в базе не было): `quality_status = ok`.

Откат удаляет поля вместе с данными.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0041_cad_zone_quality"
down_revision: str | None = "0040_cad_facade_views"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "cad_zones"
_SOURCES = ("auto", "human", "unknown")
_STATUSES = ("ok", "review", "failed")

# Происхождение старых строк; запросы вынесены, чтобы их проверял тест на синтетике.
BACKFILL_HUMAN_SQL = "update cad_zones set source = 'human' where created_by is not null"
BACKFILL_AUTO_SQL = """
    update cad_zones as z
       set source = 'auto',
           generator_version = left(j.payload->>'generator_version', 64)
      from jobs as j
     where z.created_by is null
       and z.updated_at = z.created_at
       and j.job_type = 'cad_zones'
       and j.status = 'succeeded'
       and j.workspace_id = z.workspace_id
       and j.payload->>'revision_id' = z.revision_id::text
       and j.payload->>'page_index' = z.page_index::text
       and j.payload->'cad_result'->>'result_status' = 'zones_ready'
       and j.started_at is not null
       and j.finished_at is not null
       and z.created_at between j.started_at and j.finished_at
"""


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column(
        _T, sa.Column("source", sa.String(length=16), server_default="unknown", nullable=False)
    )
    op.add_column(_T, sa.Column("generator_version", sa.String(length=64), nullable=True))
    op.add_column(_T, sa.Column("expl_area_m2", sa.Float(), nullable=True))
    op.add_column(_T, sa.Column("generator_area_m2", sa.Float(), nullable=True))
    op.add_column(_T, sa.Column("notes", pg.JSONB(), nullable=True))
    op.add_column(
        _T, sa.Column("quality_status", sa.String(length=16), server_default="ok", nullable=False)
    )
    op.add_column(_T, sa.Column("quality_reason", sa.Text(), nullable=True))
    op.add_column(_T, sa.Column("quality_accepted_by", sa.Uuid(), nullable=True))
    op.add_column(_T, sa.Column("quality_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_cad_zones_source_known"), _T, f"source in ({_quoted(_SOURCES)})"
    )
    op.create_check_constraint(
        op.f("ck_cad_zones_quality_status_known"),
        _T,
        f"quality_status in ({_quoted(_STATUSES)})",
    )

    op.execute(BACKFILL_HUMAN_SQL)
    op.execute(BACKFILL_AUTO_SQL)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_cad_zones_quality_status_known"), _T, type_="check")
    op.drop_constraint(op.f("ck_cad_zones_source_known"), _T, type_="check")
    for column in (
        "quality_accepted_at",
        "quality_accepted_by",
        "quality_reason",
        "quality_status",
        "notes",
        "generator_area_m2",
        "expl_area_m2",
        "generator_version",
        "source",
    ):
        op.drop_column(_T, column)
