"""Доменная модель Stage 1: проекты, документы, ревизии, листы, области, задания

Revision ID: 0001_domain_stage1
Revises:
Create Date: 2026-09-04

Первая миграция портала. Создаёт сущности из docs/adr/0003 и docs/adr/0008: неизменяемые
ревизии документов, листы, области распознавания и задания.

Бинарных данных здесь нет — файлы живут в объектном хранилище, в базе только ключи
и контрольные суммы (ADR-0002).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_domain_stage1"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('projects',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.Enum('active', 'archived', name='status', native_enum=False, length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_projects'))
    )
    op.create_index(op.f('ix_projects_created_at'), 'projects', ['created_at'], unique=False)
    op.create_index('ix_projects_workspace_id_name', 'projects', ['workspace_id', 'name'], unique=False)
    op.create_index('ix_projects_workspace_id_updated_at', 'projects', ['workspace_id', 'updated_at'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(length=500), nullable=False),
    sa.Column('discipline', sa.String(length=64), nullable=True),
    sa.Column('document_kind', sa.Enum('pdf', 'recognized_package', 'revit', 'navisworks', 'ifc', 'other', name='document_kind', native_enum=False, length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_documents_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    op.create_index(op.f('ix_documents_created_at'), 'documents', ['created_at'], unique=False)
    op.create_index('ix_documents_project_id_created_at', 'documents', ['project_id', 'created_at'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.Column('job_type', sa.Enum('legacy_import', name='job_type', native_enum=False, length=32), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'succeeded', 'failed', 'cancelled', name='status', native_enum=False, length=32), nullable=False),
    sa.Column('progress', sa.Float(), nullable=True),
    sa.Column('stage', sa.String(length=64), nullable=True),
    sa.Column('idempotency_key', sa.String(length=128), nullable=True),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('progress is null or (progress >= 0 and progress <= 1)', name=op.f('ck_jobs_progress_range')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_jobs_project_id_projects'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_jobs_idempotency_key'))
    )
    op.create_index(op.f('ix_jobs_created_at'), 'jobs', ['created_at'], unique=False)
    op.create_index('ix_jobs_project_id_created_at', 'jobs', ['project_id', 'created_at'], unique=False)
    op.create_index('ix_jobs_status_created_at', 'jobs', ['status', 'created_at'], unique=False)
    op.create_table('document_revisions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('revision_label', sa.String(length=64), nullable=True),
    sa.Column('source_filename', sa.String(length=500), nullable=False),
    sa.Column('source_mime', sa.String(length=255), nullable=False),
    sa.Column('source_size', sa.BigInteger(), nullable=False),
    sa.Column('source_sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('processing_status', sa.Enum('pending', 'unprocessed', 'processor_unavailable', 'importing', 'ready', 'failed', name='processing_status', native_enum=False, length=32), nullable=False),
    sa.Column('processing_error_code', sa.String(length=64), nullable=True),
    sa.Column('source_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(source_sha256) = 64', name=op.f('ck_document_revisions_source_sha256_length')),
    sa.CheckConstraint('source_size >= 0', name=op.f('ck_document_revisions_source_size_non_negative')),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_document_revisions_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_revisions')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_document_revisions_storage_key'))
    )
    op.create_index(op.f('ix_document_revisions_created_at'), 'document_revisions', ['created_at'], unique=False)
    op.create_index('ix_document_revisions_document_id_created_at', 'document_revisions', ['document_id', 'created_at'], unique=False)
    op.create_index('uq_document_revisions_document_id_source_sha256', 'document_revisions', ['document_id', 'source_sha256'], unique=True)
    op.create_table('recognition_artifacts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('revision_id', sa.UUID(), nullable=False),
    sa.Column('artifact_kind', sa.Enum('blocks_json', 'results_md', 'results_html', 'package_zip', 'other', name='artifact_kind', native_enum=False, length=32), nullable=False),
    sa.Column('schema_version', sa.Integer(), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.String(length=512), nullable=False),
    sa.Column('source_filename', sa.String(length=500), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(sha256) = 64', name=op.f('ck_recognition_artifacts_sha256_length')),
    sa.ForeignKeyConstraint(['revision_id'], ['document_revisions.id'], name=op.f('fk_recognition_artifacts_revision_id_document_revisions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recognition_artifacts')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_recognition_artifacts_storage_key'))
    )
    op.create_index(op.f('ix_recognition_artifacts_created_at'), 'recognition_artifacts', ['created_at'], unique=False)
    op.create_index('ix_recognition_artifacts_revision_id_artifact_kind', 'recognition_artifacts', ['revision_id', 'artifact_kind'], unique=False)
    op.create_table('sheets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('revision_id', sa.UUID(), nullable=False),
    sa.Column('page_index', sa.Integer(), nullable=False),
    sa.Column('page_label', sa.String(length=64), nullable=True),
    sa.Column('width_px', sa.Integer(), nullable=True),
    sa.Column('height_px', sa.Integer(), nullable=True),
    sa.Column('rotation', sa.Integer(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('page_index >= 0', name=op.f('ck_sheets_page_index_non_negative')),
    sa.CheckConstraint('rotation in (0, 90, 180, 270)', name=op.f('ck_sheets_rotation_allowed')),
    sa.ForeignKeyConstraint(['revision_id'], ['document_revisions.id'], name=op.f('fk_sheets_revision_id_document_revisions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sheets')),
    sa.UniqueConstraint('revision_id', 'page_index', name='uq_sheets_revision_id_page_index')
    )
    op.create_index(op.f('ix_sheets_created_at'), 'sheets', ['created_at'], unique=False)
    op.create_table('regions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('sheet_id', sa.UUID(), nullable=False),
    sa.Column('external_block_id', sa.String(length=128), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=True),
    sa.Column('block_type', sa.String(length=64), nullable=False),
    sa.Column('shape_type', sa.Enum('rectangle', 'polygon', name='shape_type', native_enum=False, length=32), nullable=False),
    sa.Column('coords_norm', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('polygon_points', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('recognition_status', sa.String(length=64), nullable=True),
    sa.Column('raw_content_md', sa.Text(), nullable=True),
    sa.Column('legacy_metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['sheet_id'], ['sheets.id'], name=op.f('fk_regions_sheet_id_sheets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_regions')),
    sa.UniqueConstraint('sheet_id', 'external_block_id', name='uq_regions_sheet_id_external_block_id')
    )
    op.create_index(op.f('ix_regions_created_at'), 'regions', ['created_at'], unique=False)
    op.create_index('ix_regions_sheet_id_block_type', 'regions', ['sheet_id', 'block_type'], unique=False)
    op.create_index('ix_regions_sheet_id_ordinal', 'regions', ['sheet_id', 'ordinal'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_regions_created_at'), table_name='regions')
    op.drop_index('ix_regions_sheet_id_block_type', table_name='regions')
    op.drop_index('ix_regions_sheet_id_ordinal', table_name='regions')
    op.drop_table('regions')
    op.drop_index(op.f('ix_sheets_created_at'), table_name='sheets')
    op.drop_table('sheets')
    op.drop_index(op.f('ix_recognition_artifacts_created_at'), table_name='recognition_artifacts')
    op.drop_index('ix_recognition_artifacts_revision_id_artifact_kind', table_name='recognition_artifacts')
    op.drop_table('recognition_artifacts')
    op.drop_index(op.f('ix_document_revisions_created_at'), table_name='document_revisions')
    op.drop_index('ix_document_revisions_document_id_created_at', table_name='document_revisions')
    op.drop_index('uq_document_revisions_document_id_source_sha256', table_name='document_revisions')
    op.drop_table('document_revisions')
    op.drop_index(op.f('ix_jobs_created_at'), table_name='jobs')
    op.drop_index('ix_jobs_project_id_created_at', table_name='jobs')
    op.drop_index('ix_jobs_status_created_at', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_documents_created_at'), table_name='documents')
    op.drop_index('ix_documents_project_id_created_at', table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_projects_created_at'), table_name='projects')
    op.drop_index('ix_projects_workspace_id_name', table_name='projects')
    op.drop_index('ix_projects_workspace_id_updated_at', table_name='projects')
    op.drop_table('projects')
