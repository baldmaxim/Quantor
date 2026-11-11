"""Статус PDF-ревизий с прикреплённым распознанным пакетом: unprocessed -> ready

Revision ID: 0024_pdf_status_attached
Revises: 0023_cad_zones
Create Date: 2026-11-11

ADR-0037 (поправка 2026-11-11): при прикреплении пакета PDF-ревизия получает
`processing_status = ready`. Ранее прикреплённые остались `unprocessed` и в портале выглядели
как «Не распознан». Признак прикрепления — успешное задание `legacy_import` с
`payload.attached_to_existing = true`, где `payload.imported_revision_id` — ревизия PDF.

Откат возвращает `unprocessed` по тому же признаку.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0024_pdf_status_attached"
down_revision: str | None = "0023_cad_zones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        update document_revisions r set processing_status = 'ready'
        where r.processing_status = 'unprocessed'
          and exists (
            select 1 from jobs j
            where j.job_type = 'legacy_import'
              and j.status = 'succeeded'
              and j.payload ->> 'attached_to_existing' = 'true'
              and j.payload ->> 'imported_revision_id' = r.id::text
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        update document_revisions r set processing_status = 'unprocessed'
        where r.processing_status = 'ready'
          and exists (
            select 1 from jobs j
            where j.job_type = 'legacy_import'
              and j.status = 'succeeded'
              and j.payload ->> 'attached_to_existing' = 'true'
              and j.payload ->> 'imported_revision_id' = r.id::text
          )
        """
    )
