"""Исполнение заданий отдельным процессом: аренда, попытки, воркеры

Revision ID: 0006_job_worker_lease
Revises: 0005_project_local_alias
Create Date: 2026-09-08

Задание перестаёт быть фоновой задачей внутри процесса API и получает всё, что нужно
для захвата отдельным исполнителем: счётчик попыток, владельца, срок аренды, пульс
и время, раньше которого его брать нельзя.

Отдельная таблица `workers` заведена ради различия, которое иначе неразличимо: пустая
очередь и отсутствующий исполнитель выглядят в `jobs` одинаково.

Частичные индексы — под два горячих запроса воркера. Без условия они покрывали бы и
завершённые задания, которых со временем становится большинство.

Существующие задания получают `attempt = 1`, если они уже запускались: они действительно
исполнялись однажды, и вид «ни одной попытки» у выполненного задания вводил бы в
заблуждение.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_job_worker_lease"
down_revision: str | None = "0005_project_local_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('attempt', sa.Integer(), server_default='0', nullable=False))
    op.add_column('jobs', sa.Column('max_attempts', sa.Integer(), server_default='1', nullable=False))
    op.add_column('jobs', sa.Column('worker_id', sa.String(length=64), nullable=True))
    op.add_column('jobs', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('jobs', sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))

    # Уже исполнявшееся задание сделало одну попытку. Ноль у выполненного задания
    # читался бы как «не запускалось».
    op.execute("update jobs set attempt = 1 where started_at is not null")

    op.create_check_constraint('attempt_range', 'jobs', 'attempt >= 0 and attempt <= max_attempts + 1')
    op.create_index('ix_jobs_claim', 'jobs', ['available_at', 'created_at'], unique=False, postgresql_where=sa.text("status = 'queued'"))
    op.create_index('ix_jobs_lease', 'jobs', ['lease_expires_at'], unique=False, postgresql_where=sa.text("status = 'running'"))

    op.create_table('workers',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('host', sa.String(length=255), nullable=False),
    sa.Column('pid', sa.Integer(), nullable=False),
    sa.Column('version', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('job_types', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('current_job_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['current_job_id'], ['jobs.id'], name=op.f('fk_workers_current_job_id_jobs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workers'))
    )
    op.create_index('ix_workers_heartbeat_at', 'workers', ['heartbeat_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_workers_heartbeat_at', table_name='workers')
    op.drop_table('workers')

    op.drop_index('ix_jobs_lease', table_name='jobs')
    op.drop_index('ix_jobs_claim', table_name='jobs')
    op.drop_constraint(op.f('ck_jobs_attempt_range'), 'jobs', type_='check')

    op.drop_column('jobs', 'available_at')
    op.drop_column('jobs', 'heartbeat_at')
    op.drop_column('jobs', 'lease_expires_at')
    op.drop_column('jobs', 'worker_id')
    op.drop_column('jobs', 'max_attempts')
    op.drop_column('jobs', 'attempt')
