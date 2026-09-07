"""Личности, рабочие пространства, членство и сессии

Revision ID: 0003_identity_workspaces
Revises: 0002_project_source
Create Date: 2026-09-07

Рабочее пространство перестаёт быть свободным UUID и становится сущностью (ADR-0012).
Порядок в upgrade важен и обратному не подлежит:

  1. создаются таблицы;
  2. вставляется строка dev-пространства и восстанавливаются пространства, встретившиеся
     в уже существующих проектах;
  3. только после этого на projects.workspace_id накладывается внешний ключ.

Шаг 2 пропустить нельзя: на непустой базе ключ не встанет, а данные проектов потерять
недопустимо. На пустой базе (так миграции гоняет CI) оба запроса — пустые операции.

Паролей здесь не появляется: личность удостоверяет внешний провайдер, портал хранит
только его издателя и субъект.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_identity_workspaces"
down_revision: str | None = "0002_project_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_STATUSES = ("active", "suspended")
USER_KINDS = ("human", "service")
ROLES = ("platform_admin", "workspace_admin", "engineer", "reviewer", "viewer", "service")

# Тот же идентификатор, что и app.core.workspace.DEV_WORKSPACE_ID. Вписан литералом
# намеренно: миграция не должна зависеть от кода приложения, который со временем меняется.
DEV_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"

SEED_DEV_WORKSPACE = sa.text(
    """
    insert into workspaces (id, slug, name, status, created_at, updated_at)
    values (:dev_id, 'default', 'Рабочее пространство по умолчанию', 'active', now(), now())
    on conflict (id) do nothing
    """
)

# Страховка от данных, заведённых в обход dev-пространства. На пустой базе не делает ничего,
# на рабочей — не даёт внешнему ключу уронить миграцию и потерять проекты.
RECOVER_WORKSPACES = sa.text(
    """
    insert into workspaces (id, slug, name, status, created_at, updated_at)
    select distinct
        p.workspace_id,
        'ws-' || replace(p.workspace_id::text, '-', ''),
        'Восстановлено миграцией 0003',
        'active',
        now(),
        now()
    from projects p
    where not exists (select 1 from workspaces w where w.id = p.workspace_id)
    on conflict (id) do nothing
    """
)


def upgrade() -> None:
    op.create_table('workspaces',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.Enum(*WORKSPACE_STATUSES, name='workspace_status', native_enum=False, length=32), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces')),
    sa.UniqueConstraint('slug', name=op.f('uq_workspaces_slug'))
    )
    op.create_index(op.f('ix_workspaces_created_at'), 'workspaces', ['created_at'], unique=False)
    op.create_index('ix_workspaces_status_name', 'workspaces', ['status', 'name'], unique=False)
    op.create_table('user_identities',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('issuer', sa.String(length=255), nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=True),
    sa.Column('kind', sa.Enum(*USER_KINDS, name='user_kind', native_enum=False, length=32), server_default='human', nullable=False),
    sa.Column('platform_role', sa.Enum(*ROLES, name='platform_role', native_enum=False, length=32), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("platform_role is null or platform_role in ('platform_admin', 'service')", name=op.f('ck_user_identities_platform_role_is_platform_level')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_identities')),
    sa.UniqueConstraint('issuer', 'subject', name=op.f('uq_user_identities_issuer_subject'))
    )
    op.create_index(op.f('ix_user_identities_created_at'), 'user_identities', ['created_at'], unique=False)
    op.create_index('ix_user_identities_email', 'user_identities', ['email'], unique=False)
    op.create_table('auth_sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user_identities.id'], name=op.f('fk_auth_sessions_user_id_user_identities'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_sessions_token_hash'))
    )
    op.create_index(op.f('ix_auth_sessions_created_at'), 'auth_sessions', ['created_at'], unique=False)
    op.create_index('ix_auth_sessions_expires_at', 'auth_sessions', ['expires_at'], unique=False)
    op.create_index('ix_auth_sessions_user_id_created_at', 'auth_sessions', ['user_id', 'created_at'], unique=False)
    op.create_table('workspace_memberships',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Enum(*ROLES, name='membership_role', native_enum=False, length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role in ('engineer', 'reviewer', 'viewer', 'workspace_admin')", name=op.f('ck_workspace_memberships_role_is_workspace_level')),
    sa.ForeignKeyConstraint(['user_id'], ['user_identities.id'], name=op.f('fk_workspace_memberships_user_id_user_identities'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_workspace_memberships_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspace_memberships')),
    sa.UniqueConstraint('workspace_id', 'user_id', name=op.f('uq_workspace_memberships_workspace_user'))
    )
    op.create_index(op.f('ix_workspace_memberships_created_at'), 'workspace_memberships', ['created_at'], unique=False)
    op.create_index('ix_workspace_memberships_user_id_created_at', 'workspace_memberships', ['user_id', 'created_at'], unique=False)

    # Данные до ключа: см. пояснение в заголовке модуля.
    connection = op.get_bind()
    connection.execute(SEED_DEV_WORKSPACE, {"dev_id": DEV_WORKSPACE_ID})
    connection.execute(RECOVER_WORKSPACES)

    op.create_foreign_key(op.f('fk_projects_workspace_id_workspaces'), 'projects', 'workspaces', ['workspace_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_projects_workspace_id_workspaces'), 'projects', type_='foreignkey')
    op.drop_index('ix_workspace_memberships_user_id_created_at', table_name='workspace_memberships')
    op.drop_index(op.f('ix_workspace_memberships_created_at'), table_name='workspace_memberships')
    op.drop_table('workspace_memberships')
    op.drop_index('ix_auth_sessions_user_id_created_at', table_name='auth_sessions')
    op.drop_index('ix_auth_sessions_expires_at', table_name='auth_sessions')
    op.drop_index(op.f('ix_auth_sessions_created_at'), table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_index('ix_user_identities_email', table_name='user_identities')
    op.drop_index(op.f('ix_user_identities_created_at'), table_name='user_identities')
    op.drop_table('user_identities')
    op.drop_index('ix_workspaces_status_name', table_name='workspaces')
    op.drop_index(op.f('ix_workspaces_created_at'), table_name='workspaces')
    op.drop_table('workspaces')
