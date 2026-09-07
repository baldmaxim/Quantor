"""Контур управления: переопределения настроек и флагов, журнал действий

Revision ID: 0004_control_plane
Revises: 0003_identity_workspaces
Create Date: 2026-09-07

Три таблицы одного назначения — сделать поведение установки управляемым и объяснимым.

Определения настроек и флагов сюда не переезжают: они живут в коде и под контролем
версий. В базе только то, что отличается от умолчания, и сведения о том, кто отступил.

Уникальность переопределений сделана частичными индексами, а не обычными: в SQL null
не равен null, и обычный уникальный индекс пропустил бы сколько угодно системных
переопределений одного ключа.

Журнал защищён от переписывания триггером базы, а не только отсутствием операций в API:
один уровень защиты можно обойти, и заметить это будет нечем.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_control_plane"
down_revision: str | None = "0003_identity_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = ("system", "workspace", "project")
AUDIT_RESULTS = ("success", "failure", "denied")

SCOPE_MATCHES_WORKSPACE = "(scope = 'system') = (workspace_id is null)"

APPEND_ONLY_UP = """
create or replace function audit_events_append_only() returns trigger
language plpgsql as $$
begin
    raise exception 'audit_events is append-only';
end
$$;

create trigger trg_audit_events_append_only
before update or delete on audit_events
for each row execute function audit_events_append_only();
"""

APPEND_ONLY_DOWN = """
drop trigger if exists trg_audit_events_append_only on audit_events;
drop function if exists audit_events_append_only();
"""


def upgrade() -> None:
    op.create_table('setting_overrides',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('scope', sa.Enum(*SCOPES, name='setting_scope', native_enum=False, length=32), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_by_user_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(SCOPE_MATCHES_WORKSPACE, name=op.f('ck_setting_overrides_scope_matches_workspace')),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['user_identities.id'], name=op.f('fk_setting_overrides_updated_by_user_id_user_identities'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_setting_overrides_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_setting_overrides'))
    )
    op.create_index(op.f('ix_setting_overrides_created_at'), 'setting_overrides', ['created_at'], unique=False)
    op.create_index('uq_setting_overrides_system_key', 'setting_overrides', ['key'], unique=True, postgresql_where=sa.text('workspace_id is null'))
    op.create_index('uq_setting_overrides_workspace_key', 'setting_overrides', ['workspace_id', 'key'], unique=True, postgresql_where=sa.text('workspace_id is not null'))
    op.create_table('feature_flag_overrides',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('flag_key', sa.String(length=64), nullable=False),
    sa.Column('scope', sa.Enum(*SCOPES, name='flag_scope', native_enum=False, length=32), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=True),
    sa.Column('updated_by_user_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(SCOPE_MATCHES_WORKSPACE, name=op.f('ck_feature_flag_overrides_scope_matches_workspace')),
    sa.ForeignKeyConstraint(['updated_by_user_id'], ['user_identities.id'], name=op.f('fk_feature_flag_overrides_updated_by_user_id_user_identities'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_feature_flag_overrides_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feature_flag_overrides'))
    )
    op.create_index(op.f('ix_feature_flag_overrides_created_at'), 'feature_flag_overrides', ['created_at'], unique=False)
    op.create_index('uq_feature_flag_overrides_system_key', 'feature_flag_overrides', ['flag_key'], unique=True, postgresql_where=sa.text('workspace_id is null'))
    op.create_index('uq_feature_flag_overrides_workspace_key', 'feature_flag_overrides', ['workspace_id', 'flag_key'], unique=True, postgresql_where=sa.text('workspace_id is not null'))
    op.create_table('audit_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('actor_user_id', sa.UUID(), nullable=True),
    sa.Column('actor_label', sa.String(length=320), nullable=True),
    sa.Column('actor_role', sa.String(length=32), nullable=True),
    sa.Column('credential', sa.String(length=16), nullable=True),
    sa.Column('workspace_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=False),
    sa.Column('resource_id', sa.String(length=128), nullable=True),
    sa.Column('result', sa.Enum(*AUDIT_RESULTS, name='audit_result', native_enum=False, length=32), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('before_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after_summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)
    op.create_index('ix_audit_events_action_created_at', 'audit_events', ['action', 'created_at'], unique=False)
    op.create_index('ix_audit_events_actor_user_id_created_at', 'audit_events', ['actor_user_id', 'created_at'], unique=False)
    op.create_index('ix_audit_events_resource_type_resource_id', 'audit_events', ['resource_type', 'resource_id'], unique=False)
    op.create_index('ix_audit_events_workspace_id_created_at', 'audit_events', ['workspace_id', 'created_at'], unique=False)

    op.execute(APPEND_ONLY_UP)


def downgrade() -> None:
    op.execute(APPEND_ONLY_DOWN)

    op.drop_index('ix_audit_events_workspace_id_created_at', table_name='audit_events')
    op.drop_index('ix_audit_events_resource_type_resource_id', table_name='audit_events')
    op.drop_index('ix_audit_events_actor_user_id_created_at', table_name='audit_events')
    op.drop_index('ix_audit_events_action_created_at', table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_created_at'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index('uq_feature_flag_overrides_workspace_key', table_name='feature_flag_overrides')
    op.drop_index('uq_feature_flag_overrides_system_key', table_name='feature_flag_overrides')
    op.drop_index(op.f('ix_feature_flag_overrides_created_at'), table_name='feature_flag_overrides')
    op.drop_table('feature_flag_overrides')
    op.drop_index('uq_setting_overrides_workspace_key', table_name='setting_overrides')
    op.drop_index('uq_setting_overrides_system_key', table_name='setting_overrides')
    op.drop_index(op.f('ix_setting_overrides_created_at'), table_name='setting_overrides')
    op.drop_table('setting_overrides')
